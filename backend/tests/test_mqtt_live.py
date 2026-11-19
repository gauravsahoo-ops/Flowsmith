"""Opt-in live MQTT round-trip against a real broker."""

from __future__ import annotations

import json
import os

import pytest

from app.connectors.mqtt_connector import MQTTConnector

pytestmark = pytest.mark.live


@pytest.mark.asyncio
async def test_mqtt_live_publish_consume():
    broker_url = os.getenv("MQTT_LIVE_BROKER_URL", "").strip()
    if not broker_url:
        pytest.skip("Set MQTT_LIVE_BROKER_URL to run the live MQTT test")

    creds = {"broker_url": broker_url, "client_id": "flowsmith-live-cert"}
    connector = MQTTConnector()
    assert await connector.connect(creds)

    topic = "flowsmith/cert/live"
    published = await connector.op_execute(
        "publish",
        {
            "topic": topic,
            "payload": {"hello": "mqtt", "n": 7},
            "qos": 1,
            "retain": True,
        },
        context={"credentials": {"mqtt": creds}},
    )
    assert "published" in json.dumps(published)

    consumed = await connector.op_execute(
        "consume",
        {"topic": topic, "max_messages": 1, "timeout_seconds": 3, "qos": 1},
        context={"credentials": {"mqtt": creds}},
    )
    output = consumed.get("output") or []
    assert output
    assert output[0]["payload"]["hello"] == "mqtt"

    # Clear the retained message so the broker is left clean.
    await connector.op_execute(
        "publish",
        {"topic": topic, "payload": "", "qos": 1, "retain": True},
        context={"credentials": {"mqtt": creds}},
    )
