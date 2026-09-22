"""OAuth authorize-state rows (Connect Salesforce).

One row per in-flight authorization: the random `state` value, the user
it was issued to, the authorization-server base the user was sent to
(needed again at the token-exchange step), the PKCE `code_verifier` for
the token exchange, and a `used` flag so a callback cannot replay a
state. Expired rows are purged opportunistically.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

if TYPE_CHECKING:
    from app.models import User

class OAuthState(Base):
    __tablename__ = "oauth_states"

    state: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    login_url: Mapped[str] = mapped_column(String(512), nullable=False)
    code_verifier: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Declared so the unit of work orders inserts by FK dependency.
    user: Mapped["User"] = relationship()
