"""Alerting system for monitoring execution health.

Provides functions to send alerts via email, Slack, or other channels
when critical events occur (execution failures, system errors, etc.).
"""

from __future__ import annotations

import logging
import smtplib
from datetime import UTC, datetime
from email.mime.text import MIMEText
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)


class AlertLevel:
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class AlertManager:
    """Manages alert dispatch through configured channels."""

    def __init__(self):
        self._channels: list[str] = []

    def add_channel(self, channel: str) -> None:
        if channel not in self._channels:
            self._channels.append(channel)

    def remove_channel(self, channel: str) -> None:
        self._channels = [c for c in self._channels if c != channel]

    def send(
        self,
        level: str,
        title: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> dict[str, bool]:
        """Send an alert through all configured channels.

        Returns dict mapping channel -> success.
        """
        results = {}
        for channel in self._channels:
            try:
                if channel == "email":
                    results["email"] = self._send_email(title, message)
                elif channel == "slack":
                    results["slack"] = self._send_slack(level, title, message)
                elif channel == "webhook":
                    results["webhook"] = self._send_webhook(level, title, message, details)
                else:
                    logger.warning("Unknown alert channel: %s", channel)
                    results[channel] = False
            except Exception as e:
                logger.error("Alert failed for channel %s: %s", channel, e)
                results[channel] = False

        # Always log
        logger.warning("[ALERT %s] %s: %s", level.upper(), title, message)
        return results

    def _send_email(self, title: str, message: str) -> bool:
        """Send email alert."""
        settings = get_settings()
        smtp_host = getattr(settings, "smtp_host", None)
        smtp_port = getattr(settings, "smtp_port", 587)
        smtp_user = getattr(settings, "smtp_user", None)
        smtp_pass = getattr(settings, "smtp_password", None)
        alert_email = getattr(settings, "alert_email", None)

        if not all([smtp_host, smtp_user, alert_email]):
            logger.warning("Email alerting not configured (missing smtp_host/alert_email)")
            return False

        try:
            msg = MIMEText(message)
            msg["Subject"] = f"[MAT Alert] {title}"
            assert smtp_user is not None and alert_email is not None and smtp_host is not None
            msg["From"] = smtp_user
            msg["To"] = alert_email

            with smtplib.SMTP(smtp_host, smtp_port) as server:
                server.starttls()
                if smtp_user and smtp_pass:
                    server.login(smtp_user, smtp_pass)
                server.send_message(msg)

            return True
        except Exception as e:
            logger.error("Email alert failed: %s", e)
            return False

    def _send_slack(self, level: str, title: str, message: str) -> bool:
        """Send Slack alert via webhook."""
        import os
        webhook_url = os.getenv("ALERT_SLACK_WEBHOOK_URL")
        if not webhook_url:
            logger.warning("Slack alerting not configured (missing ALERT_SLACK_WEBHOOK_URL)")
            return False

        try:
            import httpx
            color_map = {
                AlertLevel.INFO: "#36a64f",
                AlertLevel.WARNING: "#ff9900",
                AlertLevel.ERROR: "#ff0000",
                AlertLevel.CRITICAL: "#990000",
            }
            payload = {
                "attachments": [{
                    "color": color_map.get(level, "#808080"),
                    "title": f"[{level.upper()}] {title}",
                    "text": message,
                    "ts": int(datetime.now(UTC).timestamp()),
                }]
            }
            with httpx.Client() as client:
                resp = client.post(webhook_url, json=payload, timeout=10)
                return resp.status_code == 200
        except Exception as e:
            logger.error("Slack alert failed: %s", e)
            return False

    def _send_webhook(
        self,
        level: str,
        title: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> bool:
        """Send alert to a generic webhook endpoint."""
        import os
        webhook_url = os.getenv("ALERT_WEBHOOK_URL")
        if not webhook_url:
            logger.warning("Webhook alerting not configured (missing ALERT_WEBHOOK_URL)")
            return False

        try:
            import httpx
            payload = {
                "level": level,
                "title": title,
                "message": message,
                "timestamp": datetime.now(UTC).isoformat(),
                "details": details or {},
            }
            with httpx.Client() as client:
                resp = client.post(webhook_url, json=payload, timeout=10)
                return resp.status_code < 400
        except Exception as e:
            logger.error("Webhook alert failed: %s", e)
            return False


# Global instance
alert_manager = AlertManager()


# Convenience functions

def alert_execution_failed(workflow_id: str, execution_id: str, error: str) -> dict:
    """Send alert for failed execution."""
    return alert_manager.send(
        level=AlertLevel.ERROR,
        title=f"Execution failed: {execution_id}",
        message=f"Workflow {workflow_id} execution {execution_id} failed.\n\nError: {error}",
        details={"workflow_id": workflow_id, "execution_id": execution_id, "error": error},
    )


def alert_system_error(title: str, error: str) -> dict:
    """Send alert for system-level error."""
    return alert_manager.send(
        level=AlertLevel.CRITICAL,
        title=title,
        message=f"System error: {error}",
        details={"error": error},
    )


def alert_queue_stuck(queue_size: int, oldest_age_seconds: float) -> dict:
    """Send alert when queue appears stuck."""
    return alert_manager.send(
        level=AlertLevel.WARNING,
        title="Job queue may be stuck",
        message=f"Queue size: {queue_size}, oldest job age: {oldest_age_seconds:.0f}s",
        details={"queue_size": queue_size, "oldest_age_seconds": oldest_age_seconds},
    )
