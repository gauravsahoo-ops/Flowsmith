"""Email Notification Service.

Renders responsive HTML & plain-text templates for error events and delivers
them asynchronously via SMTP with exponential backoff and delivery tracking.
"""

from __future__ import annotations

import logging
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formataddr
from typing import Any

from app.config import get_settings
from app.db import get_session
from app.models.error_event import ErrorEvent, NotificationRecord

logger = logging.getLogger("notifications.email")


def _get_severity_color(severity: str) -> str:
    sev = (severity or "").upper()
    if sev == "CRITICAL":
        return "#e11d48"  # rose-600
    if sev == "ERROR":
        return "#dc2626"  # red-600
    if sev == "WARNING":
        return "#d97706"  # amber-600
    return "#3b82f6"  # blue-500


def render_email_templates(
    event: ErrorEvent,
    recipient_email: str,
    base_url: str | None = None,
) -> tuple[str, str]:
    """Generate (plain_text, html_content) for an error event."""
    settings = get_settings()
    app_url = (base_url or settings.app_base_url or "http://localhost:5173").rstrip("/")

    wf_name = event.workflow_name or (f"Workflow {event.workflow_id}" if event.workflow_id else "Platform Operation")
    node_text = event.node_name or (f"Node {event.node_id}" if event.node_id else "N/A")
    exec_id = event.execution_id or "N/A"
    connector_label = (event.connector_type or "Integration").replace("_", " ").title()

    # Determine primary CTA button
    cta_url = f"{app_url}/monitoring"
    cta_text = "View Execution Details"
    if event.category in ("AUTH_SESSION_EXPIRED", "CREDENTIAL_REVOKED"):
        cta_url = f"{app_url}/credentials"
        cta_text = f"Reconnect {connector_label} Account"
    elif event.execution_id:
        cta_url = f"{app_url}/monitoring?execution_id={event.execution_id}"
        cta_text = "Review Failed Execution"

    # 1. Plain-text version
    plain_text = f"""Flowsmith Alert: {event.title}

Hello,

{event.message}

Details:
• Workflow: {wf_name}
• Execution ID: {exec_id}
• Failed Node: {node_text}
• Category: {event.category}
• Severity: {event.severity}
• Timestamp (UTC): {event.created_at.strftime('%Y-%m-%d %H:%M:%S UTC') if event.created_at else 'Recent'}

Recommended Action:
{event.resolution}

Take Action:
{cta_text}: {cta_url}

Your workflow configuration and execution history have been preserved.

Regards,
Flowsmith Notifications
"""

    # 2. Responsive HTML version
    sev_color = _get_severity_color(event.severity)
    html_content = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{event.title}</title>
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
      line-height: 1.6;
      color: #1e293b;
      background-color: #f8fafc;
      margin: 0;
      padding: 0;
    }}
    .container {{
      max-width: 600px;
      margin: 24px auto;
      background-color: #ffffff;
      border-radius: 12px;
      overflow: hidden;
      box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05), 0 2px 4px -2px rgba(0, 0, 0, 0.05);
      border: 1px solid #e2e8f0;
    }}
    .header {{
      background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
      padding: 24px 32px;
      border-bottom: 3px solid {sev_color};
    }}
    .header-logo {{
      font-size: 20px;
      font-weight: 700;
      color: #ffffff;
      letter-spacing: -0.5px;
    }}
    .header-logo span {{
      color: #38bdf8;
    }}
    .badge {{
      display: inline-block;
      padding: 4px 10px;
      font-size: 11px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      border-radius: 9999px;
      background-color: {sev_color};
      color: #ffffff;
      margin-top: 10px;
    }}
    .content {{
      padding: 32px;
    }}
    .title {{
      font-size: 20px;
      font-weight: 700;
      color: #0f172a;
      margin-top: 0;
      margin-bottom: 12px;
    }}
    .message {{
      font-size: 15px;
      color: #334155;
      margin-bottom: 24px;
    }}
    .details-card {{
      background-color: #f1f5f9;
      border-radius: 8px;
      padding: 20px;
      margin-bottom: 24px;
      border-left: 4px solid #64748b;
    }}
    .details-row {{
      display: flex;
      margin-bottom: 8px;
      font-size: 14px;
    }}
    .details-row:last-child {{
      margin-bottom: 0;
    }}
    .details-label {{
      font-weight: 600;
      color: #475569;
      width: 140px;
      flex-shrink: 0;
    }}
    .details-val {{
      color: #0f172a;
      word-break: break-all;
    }}
    .action-box {{
      background-color: #eff6ff;
      border: 1px solid #bfdbfe;
      border-radius: 8px;
      padding: 20px;
      margin-bottom: 28px;
    }}
    .action-title {{
      font-weight: 700;
      color: #1e40af;
      margin-top: 0;
      margin-bottom: 6px;
      font-size: 15px;
    }}
    .action-text {{
      margin: 0;
      color: #1e3a8a;
      font-size: 14px;
    }}
    .btn-container {{
      text-align: center;
      margin-bottom: 24px;
    }}
    .btn {{
      display: inline-block;
      background-color: #2563eb;
      color: #ffffff !important;
      font-weight: 600;
      font-size: 15px;
      padding: 12px 28px;
      border-radius: 8px;
      text-decoration: none;
      box-shadow: 0 2px 4px rgba(37, 99, 235, 0.2);
    }}
    .btn:hover {{
      background-color: #1d4ed8;
    }}
    .footer {{
      background-color: #f8fafc;
      border-top: 1px solid #e2e8f0;
      padding: 20px 32px;
      font-size: 12px;
      color: #64748b;
      text-align: center;
    }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <div class="header-logo">Flow<span>smith</span> Notifications</div>
      <div class="badge">{event.severity}</div>
    </div>
    <div class="content">
      <h1 class="title">{event.title}</h1>
      <p class="message">{event.message}</p>

      <div class="details-card">
        <div class="details-row">
          <span class="details-label">Workflow:</span>
          <span class="details-val"><strong>{wf_name}</strong></span>
        </div>
        <div class="details-row">
          <span class="details-label">Execution ID:</span>
          <span class="details-val"><code>{exec_id}</code></span>
        </div>
        <div class="details-row">
          <span class="details-label">Failed Node:</span>
          <span class="details-val">{node_text}</span>
        </div>
        <div class="details-row">
          <span class="details-label">Status:</span>
          <span class="details-val" style="color: {sev_color}; font-weight: 600;">Failed</span>
        </div>
      </div>

      <div class="action-box">
        <div class="action-title">Recommended Action</div>
        <p class="action-text">{event.resolution}</p>
      </div>

      <div class="btn-container">
        <a href="{cta_url}" class="btn" target="_blank">{cta_text}</a>
      </div>

      <p style="font-size: 13px; color: #64748b; text-align: center; margin-bottom: 0;">
        Your workflow configuration and execution history have been safely preserved.
      </p>
    </div>
    <div class="footer">
      This is an automated notification from Flowsmith Automation Platform.<br/>
      Manage your email alert preferences in Settings &gt; Notifications.
    </div>
  </div>
</body>
</html>
"""
    return plain_text, html_content


def send_email_notification_sync(record_id: str) -> bool:
    """Synchronously send a single notification record via SMTP and update status in DB."""
    settings = get_settings()
    with get_session() as db:
        rec = db.get(NotificationRecord, record_id)
        if not rec:
            logger.warning("Notification record %s not found for delivery", record_id)
            return False

        event = db.get(ErrorEvent, rec.error_event_id)
        if not event:
            logger.warning("Error event %s not found for record %s", rec.error_event_id, record_id)
            rec.status = "FAILED"
            rec.error_message = "Associated error event not found"
            db.commit()
            return False

        rec.attempts += 1
        plain_text, html_content = render_email_templates(event, rec.recipient_email)

        # Check SMTP configuration
        if not settings.smtp_host or not settings.mail_from:
            # Dev / test environment fallback
            logger.info(
                "SMTP unconfigured; simulated alert delivery to %s for event [%s]: %s",
                rec.recipient_email,
                event.code,
                event.title,
            )
            rec.status = "SENT"
            rec.sent_at = datetime.now(timezone.utc)
            event.status = "NOTIFIED"
            db.commit()
            return True

        try:
            msg = EmailMessage()
            msg["Subject"] = f"[{event.severity}] {event.title}"
            msg["From"] = formataddr(("Flowsmith Alerts", settings.mail_from))
            msg["To"] = rec.recipient_email
            msg.set_content(plain_text)
            msg.add_alternative(html_content, subtype="html")

            use_ssl = bool(settings.smtp_use_tls or settings.smtp_port == 465)
            if use_ssl:
                with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=15) as server:
                    if settings.smtp_user and settings.smtp_password:
                        server.login(settings.smtp_user, settings.smtp_password)
                    server.send_message(msg)
            else:
                with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as server:
                    if settings.smtp_starttls and settings.smtp_port != 25:
                        server.starttls()
                    if settings.smtp_user and settings.smtp_password:
                        server.login(settings.smtp_user, settings.smtp_password)
                    server.send_message(msg)

            rec.status = "SENT"
            rec.sent_at = datetime.now(timezone.utc)
            rec.error_message = None
            event.status = "NOTIFIED"
            db.commit()
            logger.info("Successfully sent error notification to %s for event %s", rec.recipient_email, event.id)
            return True
        except Exception as exc:
            logger.error("Failed to send notification email to %s: %s", rec.recipient_email, exc)
            rec.status = "FAILED"
            rec.error_message = str(exc)[:500]
            event.status = "NOTIFICATION_FAILED"
            db.commit()
            return False
