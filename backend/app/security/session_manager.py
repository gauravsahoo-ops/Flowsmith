"""Session Manager for Flowsmith Smart Application Sessions.

Manages active login sessions, idle timeouts, sliding window renewals,
per-device tracking, and session revocation.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.auth_session import AuthSession
from app.models.user import User
from app.security.jwt import create_token, decode_token, revoke_token

logger = logging.getLogger("auth.session_manager")


class SessionManager:
    """Manages application user sessions with sliding-window renewal and revocation."""

    @staticmethod
    def _parse_device_name(user_agent: str) -> str:
        """Derive a friendly device label from the User-Agent header."""
        ua = (user_agent or "").lower()
        if not ua:
            return "Web Browser"
        browser = "Browser"
        if "edg/" in ua:
            browser = "Edge"
        elif "chrome/" in ua:
            browser = "Chrome"
        elif "firefox/" in ua:
            browser = "Firefox"
        elif "safari/" in ua and "chrome/" not in ua:
            browser = "Safari"

        os_name = "Desktop"
        if "windows" in ua:
            os_name = "Windows"
        elif "macintosh" in ua or "mac os" in ua:
            os_name = "macOS"
        elif "linux" in ua:
            os_name = "Linux"
        elif "iphone" in ua or "ipad" in ua:
            os_name = "iOS"
        elif "android" in ua:
            os_name = "Android"

        return f"{browser} on {os_name}"

    @classmethod
    def create_session(
        cls,
        db: Session,
        user: User,
        token: str,
        ip_address: str = "unknown",
        user_agent: str = "",
        auto_renew: bool = True,
        remember_device: bool = False,
    ) -> AuthSession:
        """Create and persist an authoritative AuthSession row bound to a JWT."""
        payload = decode_token(token)
        jti = payload.get("jti") or str(uuid.uuid4())
        now = datetime.now(UTC)

        settings = get_settings()
        idle_mins = 1440 * 7 if remember_device else 1440  # 7 days if remember_device, else 24 hours
        max_mins = 1440 * 30 if remember_device else 1440 * 7  # 30 days vs 7 days

        # Token expiry from payload
        exp_ts = payload.get("exp")
        if exp_ts:
            expires_at = datetime.fromtimestamp(exp_ts, tz=UTC)
        else:
            expires_at = now + timedelta(minutes=settings.jwt_expires_minutes)

        session = AuthSession(
            id=str(uuid.uuid4()),
            user_id=user.id,
            token_jti=jti,
            ip_address=ip_address or "unknown",
            user_agent=user_agent[:500] if user_agent else "",
            device_name=cls._parse_device_name(user_agent),
            is_active=True,
            auto_renew=auto_renew,
            remember_device=remember_device,
            idle_timeout_minutes=idle_mins,
            max_lifetime_minutes=max_mins,
            created_at=now,
            last_active_at=now,
            expires_at=expires_at,
        )
        db.add(session)
        db.commit()
        db.refresh(session)
        logger.info("Created AuthSession %s for user %s (%s)", session.id, user.email, session.device_name)
        return session

    @classmethod
    def renew_session(
        cls,
        db: Session,
        current_token: str,
        ip_address: str = "unknown",
        user_agent: str = "",
    ) -> dict[str, Any]:
        """Validate and renew an active session without user interruption.

        Returns {token, session_id, expires_at}. Raises ValueError if not renewable.
        """
        try:
            payload = decode_token(current_token)
        except Exception as exc:
            raise ValueError(f"Cannot renew session: invalid token ({exc})")

        user_id = int(payload["sub"])
        jti = payload.get("jti")
        if not jti:
            raise ValueError("Cannot renew session: missing token identity (jti)")

        session = db.scalar(
            select(AuthSession).where(
                AuthSession.token_jti == jti,
                AuthSession.user_id == user_id,
            )
        )
        now = datetime.now(UTC)

        # If no DB session row existed yet, verify user and bootstrap session
        user = db.get(User, user_id)
        if not user or not user.active:
            raise ValueError("User account is inactive or deleted.")
        from app.api.auth import token_is_stale

        if token_is_stale(payload, user):
            raise ValueError("Session is older than the account's security policy. Sign in again.")

        if session is None:
            # Bootstrap session row for existing bearer token
            session = cls.create_session(
                db=db,
                user=user,
                token=current_token,
                ip_address=ip_address,
                user_agent=user_agent,
            )

        if not session.is_active or session.revoked_at is not None:
            raise ValueError("Session has been revoked.")

        if not session.auto_renew:
            raise ValueError("Automatic session renewal is disabled for this session.")

        # Check idle timeout
        idle_limit = session.last_active_at + timedelta(minutes=session.idle_timeout_minutes)
        if now > idle_limit:
            session.is_active = False
            session.revoked_at = now
            db.commit()
            revoke_token(session.token_jti)
            raise ValueError("Session expired due to inactivity.")

        # Check max lifetime
        max_limit = session.created_at + timedelta(minutes=session.max_lifetime_minutes)
        if now > max_limit:
            session.is_active = False
            session.revoked_at = now
            db.commit()
            revoke_token(session.token_jti)
            raise ValueError("Session reached maximum allowed lifetime.")

        # Mint rotated fresh token
        new_token = create_token(user.id, email=user.email)
        new_payload = decode_token(new_token)
        new_jti = new_payload.get("jti") or str(uuid.uuid4())
        new_exp_ts = new_payload.get("exp")
        new_expires_at = datetime.fromtimestamp(new_exp_ts, tz=UTC) if new_exp_ts else now + timedelta(hours=24)

        # Revoke old JTI and update session record
        revoke_token(session.token_jti, session.expires_at)
        session.token_jti = new_jti
        session.last_active_at = now
        session.expires_at = new_expires_at
        if ip_address and ip_address != "unknown":
            session.ip_address = ip_address
        if user_agent:
            session.user_agent = user_agent[:500]
            session.device_name = cls._parse_device_name(user_agent)

        db.commit()
        logger.info("Renewed session %s for user %s", session.id, user.email)
        return {
            "token": new_token,
            "session_id": session.id,
            "expires_at": new_expires_at.isoformat(),
            "auto_renew": session.auto_renew,
        }

    @classmethod
    def list_user_sessions(cls, db: Session, user_id: int, current_jti: str | None = None) -> list[dict[str, Any]]:
        """List all active sessions for a user."""
        recs = db.scalars(
            select(AuthSession)
            .where(
                AuthSession.user_id == user_id,
                AuthSession.is_active == True,
            )
            .order_by(AuthSession.last_active_at.desc())
        ).all()

        now = datetime.now(UTC)
        out = []
        for s in recs:
            # Check if expired
            if s.expires_at and s.expires_at < now:
                s.is_active = False
                continue

            out.append({
                "id": s.id,
                "device_name": s.device_name,
                "ip_address": s.ip_address,
                "is_current": bool(current_jti and s.token_jti == current_jti),
                "auto_renew": s.auto_renew,
                "remember_device": s.remember_device,
                "created_at": s.created_at.isoformat() if s.created_at else None,
                "last_active_at": s.last_active_at.isoformat() if s.last_active_at else None,
                "expires_at": s.expires_at.isoformat() if s.expires_at else None,
            })
        db.commit()
        return out

    @classmethod
    def revoke_session(cls, db: Session, user_id: int, session_id: str) -> bool:
        """Revoke a specific session for a user."""
        session = db.get(AuthSession, session_id)
        if not session or session.user_id != user_id:
            return False

        now = datetime.now(UTC)
        session.is_active = False
        session.revoked_at = now
        db.commit()
        revoke_token(session.token_jti, session.expires_at)
        logger.info("Revoked session %s for user %d", session_id, user_id)
        return True

    @classmethod
    def revoke_all_sessions(cls, db: Session, user_id: int, except_jti: str | None = None) -> int:
        """Revoke all active sessions for a user, optionally sparing the current session."""
        query = select(AuthSession).where(
            AuthSession.user_id == user_id,
            AuthSession.is_active == True,
        )
        if except_jti:
            query = query.where(AuthSession.token_jti != except_jti)

        sessions = list(db.scalars(query).all())
        now = datetime.now(UTC)
        count = 0
        for s in sessions:
            s.is_active = False
            s.revoked_at = now
            revoke_token(s.token_jti, s.expires_at)
            count += 1

        db.commit()
        logger.info("Revoked %d sessions for user %d", count, user_id)
        return count

    @classmethod
    def update_session_settings(
        cls,
        db: Session,
        user_id: int,
        auto_renew: bool | None = None,
        remember_device: bool | None = None,
        current_jti: str | None = None,
    ) -> dict[str, Any]:
        """Update auto_renew or remember_device for user sessions."""
        now = datetime.now(UTC)
        if current_jti:
            session = db.scalar(select(AuthSession).where(AuthSession.token_jti == current_jti, AuthSession.user_id == user_id))
            if session:
                if auto_renew is not None:
                    session.auto_renew = auto_renew
                if remember_device is not None:
                    session.remember_device = remember_device
                session.last_active_at = now
                db.commit()
                return {
                    "auto_renew": session.auto_renew,
                    "remember_device": session.remember_device,
                    "updated": True,
                }

        # Otherwise update all active sessions
        updates = {}
        if auto_renew is not None:
            updates["auto_renew"] = auto_renew
        if remember_device is not None:
            updates["remember_device"] = remember_device

        if updates:
            db.execute(
                update(AuthSession)
                .where(AuthSession.user_id == user_id, AuthSession.is_active == True)
                .values(**updates)
            )
            db.commit()

        return {
            "auto_renew": auto_renew if auto_renew is not None else True,
            "remember_device": remember_device if remember_device is not None else False,
            "updated": True,
        }
