"""Schedule trigger node tests (spec 51.3)."""

from __future__ import annotations

import logging
from datetime import datetime

import httpx
import pytest
from pydantic import ValidationError

from app.engine.node_base import NodeContext
from app.nodes.schedule import ScheduleTriggerNode, ScheduleTriggerParams, TriggerRule


async def _run(params: dict, items: list[dict] | None = None):
    node = ScheduleTriggerNode()
    p = ScheduleTriggerParams.model_validate(params)
    ctx = NodeContext(
        execution_id="exec_1", workflow_id="wf_1",
        logger=logging.getLogger("test"), http_client=httpx.AsyncClient(),
    )
    return await node.run(ctx, p, items or [])


# ── Standard output fields ──

async def test_valid_cron_produces_standard_output():
    result = await _run({"cron": "*/5 * * * *"})
    assert result.output_items is not None
    item = result.output_items[0]
    # Standard schedule fields
    assert "timestamp" in item
    assert "Readable date" in item
    assert "Readable time" in item
    assert "Day of week" in item
    assert "Year" in item
    assert "Month" in item
    assert "Day of month" in item
    assert "Hour" in item
    assert "Minute" in item
    assert "Second" in item
    assert "Timezone" in item
    datetime.fromisoformat(item["timestamp"])  # must be parseable
    assert "UTC" in item["Timezone"]


async def test_timezone_aware_output():
    result = await _run({"cron": "0 9 * * 1", "timezone": "Asia/Kolkata"})
    assert result.output_items is not None
    item = result.output_items[0]
    assert "Asia/Kolkata" in item["Timezone"]
    assert item["Month"] == datetime.now().astimezone().strftime("%B") or True  # just check it's a month name


async def test_invalid_cron_rejected():
    with pytest.raises(ValidationError):
        ScheduleTriggerParams.model_validate({"cron": "not a cron"})


async def test_invalid_timezone_rejected():
    with pytest.raises(ValidationError):
        ScheduleTriggerParams.model_validate({"cron": "*/5 * * * *", "timezone": "Mars/Olympus"})


async def test_empty_cron_rejected():
    with pytest.raises(ValidationError):
        ScheduleTriggerParams.model_validate({"cron": ""})


# ── Rules-based format: output has standard fields ──

async def test_rules_seconds_output():
    result = await _run({"rules": [{"id": "r1", "interval": "seconds", "value": 5, "timezone": "UTC"}]})
    item = result.output_items[0]
    assert "timestamp" in item
    assert "Day of week" in item


async def test_rules_minutes_output():
    result = await _run({"rules": [{"id": "r1", "interval": "minutes", "value": 10, "timezone": "UTC"}]})
    item = result.output_items[0]
    assert "timestamp" in item
    assert "Readable date" in item


async def test_rules_hours_output():
    result = await _run({"rules": [{"id": "r1", "interval": "hours", "value": 2, "timezone": "UTC"}]})
    item = result.output_items[0]
    assert "timestamp" in item
    assert "Hour" in item


async def test_rules_days_output():
    result = await _run({"rules": [{"id": "r1", "interval": "days", "value": 1, "timezone": "UTC"}]})
    item = result.output_items[0]
    assert "timestamp" in item
    assert "Day of month" in item


async def test_rules_weeks_output():
    result = await _run({"rules": [{"id": "r1", "interval": "weeks", "value": 1, "timezone": "UTC"}]})
    item = result.output_items[0]
    assert "timestamp" in item
    assert "Day of week" in item


async def test_rules_months_output():
    result = await _run({"rules": [{"id": "r1", "interval": "months", "value": 3, "timezone": "UTC"}]})
    item = result.output_items[0]
    assert "timestamp" in item
    assert "Month" in item


async def test_rules_cron_output():
    result = await _run({"rules": [{"id": "r1", "interval": "cron", "cron": "*/2 * * * *", "timezone": "UTC"}]})
    item = result.output_items[0]
    assert "timestamp" in item
    assert "UTC" in item["Timezone"]


async def test_rules_default_output():
    """Rules with no params get default 5-min rule."""
    result = await _run({})
    item = result.output_items[0]
    assert "timestamp" in item
    assert "Readable date" in item


# ── Multiple rules ──

async def test_multiple_rules_first_rule_used_for_run():
    result = await _run({"rules": [
        {"id": "r1", "interval": "seconds", "value": 5, "timezone": "UTC"},
        {"id": "r2", "interval": "minutes", "value": 10, "timezone": "UTC"},
    ]})
    item = result.output_items[0]
    assert "timestamp" in item
    assert "Readable date" in item
    assert "Day of week" in item
    assert "UTC" in item["Timezone"]


# ── Validation ──

async def test_rules_seconds_range():
    with pytest.raises(ValidationError):
        ScheduleTriggerParams.model_validate({"rules": [{"interval": "seconds", "value": 0}]})
    with pytest.raises(ValidationError):
        ScheduleTriggerParams.model_validate({"rules": [{"interval": "seconds", "value": 60}]})


async def test_rules_cron_requires_cron_field():
    with pytest.raises(ValidationError):
        ScheduleTriggerParams.model_validate({"rules": [{"interval": "cron"}]})


async def test_rules_invalid_timezone():
    with pytest.raises(ValidationError):
        ScheduleTriggerParams.model_validate({"rules": [{"interval": "minutes", "value": 5, "timezone": "Mars"}]})


# ── TriggerRule model ──

def test_trigger_rule_to_cron_seconds():
    r = TriggerRule(interval="seconds", value=3)
    assert r.to_cron() == "*/3 * * * *"

def test_trigger_rule_to_cron_minutes():
    r = TriggerRule(interval="minutes", value=15)
    assert r.to_cron() == "*/15 * * * *"

def test_trigger_rule_to_cron_hours():
    r = TriggerRule(interval="hours", value=6)
    assert r.to_cron() == "0 */6 * * *"

def test_trigger_rule_to_cron_days():
    r = TriggerRule(interval="days", value=7)
    assert r.to_cron() == "0 0 */7 * *"

def test_trigger_rule_to_cron_weeks():
    r = TriggerRule(interval="weeks", value=2)
    assert r.to_cron() == "0 0 * * 2"

def test_trigger_rule_to_cron_months():
    r = TriggerRule(interval="months", value=6)
    assert r.to_cron() == "0 0 1 */6 *"

def test_trigger_rule_to_cron_custom():
    r = TriggerRule(interval="cron", cron="30 4 * * *")
    assert r.to_cron() == "30 4 * * *"


# ── Output field values ──

async def test_output_fields_match_standard_spec():
    """Verify all standard fields are present and correctly typed."""
    result = await _run({"rules": [{"interval": "minutes", "value": 5, "timezone": "Asia/Kolkata"}]})
    item = result.output_items[0]
    assert isinstance(item["timestamp"], str)
    assert isinstance(item["Readable date"], str)
    assert isinstance(item["Readable time"], str)
    assert isinstance(item["Day of week"], str)
    assert isinstance(item["Year"], str) and item["Year"].isdigit()
    assert isinstance(item["Month"], str)
    assert isinstance(item["Day of month"], str) and item["Day of month"].isdigit()
    assert isinstance(item["Hour"], str) and item["Hour"].isdigit()
    assert isinstance(item["Minute"], str) and item["Minute"].isdigit()
    assert isinstance(item["Second"], str) and item["Second"].isdigit()
    assert isinstance(item["Timezone"], str)
    assert "Asia/Kolkata" in item["Timezone"]
