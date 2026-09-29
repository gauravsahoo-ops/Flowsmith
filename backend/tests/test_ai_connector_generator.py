"""Tests for AI-Assisted Connector Generator (Phase 40H).

Verifies:
- 14-step pipeline execution
- Source provenance attribution without hallucinated endpoints
- Strategy selection hierarchy
- Validation state assignment
"""

import pytest
from app.connectors import register_builtin_connectors
from app.integrations.catalog.ai_connector_generator import AIConnectorGenerator


def test_ai_connector_generator_pipeline():
    register_builtin_connectors()
    generator = AIConnectorGenerator()
    plan = generator.run_14_step_pipeline("Connect FlowSmith to Zendesk")

    assert plan.application_name == "Zendesk"
    assert plan.canonical_id == "zendesk"
    assert len(plan.steps_completed) == 14
    assert plan.strategy == "EXISTING_NATIVE"  # Since Zendesk is native in FlowSmith
    assert plan.validation_status == "VALIDATED_FUNCTIONAL"
    assert plan.provenance.verified is True
    assert plan.provenance.source_url.startswith("https://")
    assert len(plan.operations) >= 4
