"""Unit tests for email notification template generation."""

from datetime import datetime, timezone
from app.models.error_event import ErrorEvent
from app.services.email_notifications import render_email_templates, _get_severity_color


def test_severity_colors():
    assert _get_severity_color("CRITICAL") == "#e11d48"
    assert _get_severity_color("ERROR") == "#dc2626"
    assert _get_severity_color("WARNING") == "#d97706"
    assert _get_severity_color("INFO") == "#3b82f6"


def test_render_email_templates_oauth_expired():
    ev = ErrorEvent(
        id="evt-12345",
        created_at=datetime(2026, 10, 10, 12, 0, 0, tzinfo=timezone.utc),
        severity="CRITICAL",
        category="AUTH_SESSION_EXPIRED",
        code="OAUTH_SESSION_EXPIRED",
        title="Action Required: Your Salesforce Session Has Expired",
        message="Your Flowsmith workflow could not complete because the Salesforce authentication session has expired.",
        resolution="Reconnect your Salesforce account in Flowsmith Settings > Credentials.",
        workflow_id="wf-abc",
        workflow_name="Salesforce Lead Synchronization",
        execution_id="exec-999",
        node_id="node-create-lead",
        node_name="Create Lead",
        connector_type="salesforce",
        status="DETECTED",
        fingerprint="dummyfp",
    )

    plain, html = render_email_templates(ev, recipient_email="user@example.com", base_url="http://flowsmith.app")

    # Plain text assertions
    assert "Salesforce Lead Synchronization" in plain
    assert "exec-999" in plain
    assert "Create Lead" in plain
    assert "http://flowsmith.app/credentials" in plain
    assert "Your workflow configuration and execution history have been preserved." in plain

    # HTML assertions
    assert "Action Required: Your Salesforce Session Has Expired" in html
    assert "Salesforce Lead Synchronization" in html
    assert "Create Lead" in html
    assert "Reconnect Salesforce Account" in html
    assert "http://flowsmith.app/credentials" in html
    assert "#e11d48" in html  # critical color
