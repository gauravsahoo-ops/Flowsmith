"""Unit tests for Kafka, Oracle, and MQTT connectors."""

import pytest
from app.connectors import ConnectorError
from app.connectors.kafka_connector import KafkaConnector
from app.connectors.oracle_connector import OracleConnector
from app.connectors.mqtt_connector import MQTTConnector
from app.connectors.kafka_definition import build_kafka_definition
from app.connectors.oracle_definition import build_oracle_definition
from app.connectors.mqtt_definition import build_mqtt_definition
from app.credentials.registry import is_known_type, is_implemented, validate_data


@pytest.mark.asyncio
async def test_kafka_connector_lifecycle_and_operations(monkeypatch):
    connector = KafkaConnector()
    definition = build_kafka_definition()

    assert definition.connector_key == "kafka"
    assert "produce" in definition.operations
    assert "consume" in definition.operations
    assert "list_topics" in definition.operations

    # Test connect
    assert not await connector.connect({})
    assert await connector.connect({"bootstrap_servers": "localhost:9092"})

    # Unconfigured operations fail typed instead of fabricating data.
    fresh = KafkaConnector()
    with pytest.raises(ConnectorError):
        await fresh.op_execute("produce", {"topic": "test-events", "payload": {}})

    # Routing is covered without opening a broker connection; the real
    # round-trip lives in scripts/live_kafka_certify.py.
    async def fake_produce(creds, params):
        return {
            "status": "published",
            "topic": params.topic,
            "partition": params.partition or 0,
            "offset": 1,
            "timestamp": 0,
            "key": params.message_key,
            "headers": params.headers,
        }

    async def fake_consume(creds, params):
        return {
            "output": [{
                "topic": params.topic,
                "partition": 0,
                "offset": 1,
                "key": "k1",
                "value": {"ok": True},
                "headers": {},
                "timestamp": 0,
            }],
            "count": 1,
        }

    async def fake_list(creds, timeout):
        return ["events", "orders"]

    monkeypatch.setattr(connector, "_produce", fake_produce)
    monkeypatch.setattr(connector, "_consume", fake_consume)
    monkeypatch.setattr(connector, "_list_topics", fake_list)

    ctx = {"credentials": {"kafka": {"bootstrap_servers": "localhost:9092"}}}
    prod_res = await connector.op_execute(
        "produce",
        {"topic": "test-events", "message_key": "k1", "payload": {"event": "user_signup", "id": 123}},
        context=ctx,
    )
    assert prod_res["status"] == "published"
    assert prod_res["topic"] == "test-events"

    cons_res = await connector.op_execute("consume", {"topic": "test-events", "max_messages": 5}, context=ctx)
    assert len(cons_res["output"]) == 1
    assert cons_res["output"][0]["key"] == "k1"

    top_res = await connector.op_execute("list_topics", {}, context=ctx)
    assert top_res["topics"] == ["events", "orders"]


@pytest.mark.asyncio
async def test_oracle_connector_lifecycle_and_operations(monkeypatch):
    connector = OracleConnector()
    definition = build_oracle_definition()

    assert definition.connector_key == "oracle"
    assert "query" in definition.operations
    assert "insert" in definition.operations
    assert "table_list" in definition.operations

    # Test connect
    assert not await connector.connect({})
    assert await connector.connect({"host": "oracle.local", "username": "admin", "password": "pwd"})

    # Unconfigured operations fail typed instead of returning sample rows.
    fresh = OracleConnector()
    with pytest.raises(ConnectorError):
        await fresh.op_execute("query", {"query": "SELECT * FROM EMPLOYEES"})

    # Routing is covered without opening a database connection; the real
    # round-trip lives in scripts/live_oracle_certify.py.
    async def fake_query(creds, sql, binds, max_rows, timeout):
        return {"rows": [{"id": 101, "name": "Enterprise Account"}], "row_count": 1}

    async def fake_execute(creds, sql, binds, timeout):
        return {"status": "success", "affected_rows": 1}

    async def fake_table_list(creds, timeout):
        return {"tables": ["EMPLOYEES", "CUSTOMERS"], "count": 2}

    monkeypatch.setattr(connector, "_query", fake_query)
    monkeypatch.setattr(connector, "_execute", fake_execute)
    monkeypatch.setattr(connector, "_table_list", fake_table_list)

    ctx = {"credentials": {"oracle": {
        "host": "oracle.local", "username": "admin", "password": "pwd", "service_name": "FREEPDB1",
    }}}
    q_res = await connector.op_execute("query", {"query": "SELECT * FROM EMPLOYEES"}, context=ctx)
    assert q_res["row_count"] == 1

    ins_res = await connector.op_execute(
        "insert", {"table": "CUSTOMERS", "data": {"NAME": "ACME"}}, context=ctx,
    )
    assert ins_res["status"] == "success"

    t_res = await connector.op_execute("table_list", {}, context=ctx)
    assert "EMPLOYEES" in t_res["tables"]


@pytest.mark.asyncio
async def test_mqtt_connector_lifecycle_and_operations(monkeypatch):
    connector = MQTTConnector()
    definition = build_mqtt_definition()

    assert definition.connector_key == "mqtt"
    assert "publish" in definition.operations
    assert "consume" in definition.operations

    # Test connect
    assert not await connector.connect({})
    assert await connector.connect({"broker_url": "mqtt://localhost:1883"})

    # The real broker round-trip is covered by tests/test_mqtt_live.py.
    # Here we verify operation routing without opening a network connection.
    def fake_publish(creds, params):
        return {"output": [{"status": "published", "topic": params.topic, "qos": params.qos}]}

    def fake_consume(creds, params):
        return {"output": [{"topic": params.topic, "payload": {"ok": True}}]}

    monkeypatch.setattr(connector, "_publish_sync", fake_publish)
    monkeypatch.setattr(connector, "_consume_sync", fake_consume)

    pub_res = await connector.op_execute("publish", {
        "topic": "sensors/ambient",
        "payload": {"temp": 24.5},
        "qos": 1,
    })
    assert pub_res["output"][0]["status"] == "published"
    assert pub_res["output"][0]["topic"] == "sensors/ambient"

    cons_res = await connector.op_execute("consume", {"topic": "sensors/ambient"})
    assert "output" in cons_res


def test_credential_schemas_for_kafka_oracle_mqtt():
    for cred_type in ["kafka", "oracle", "mqtt"]:
        assert is_known_type(cred_type)
        assert is_implemented(cred_type)

    # Validate Kafka
    k_data = validate_data("kafka", {"bootstrap_servers": "kafka.internal:9092", "client_id": "test_client"})
    assert k_data["bootstrap_servers"] == "kafka.internal:9092"

    # Validate Oracle
    o_data = validate_data("oracle", {"host": "db.corp.net", "username": "sys", "password": "pass"})
    assert o_data["host"] == "db.corp.net"

    # Validate MQTT
    m_data = validate_data("mqtt", {"broker_url": "mqtt://10.0.0.1:1883"})
    assert m_data["broker_url"] == "mqtt://10.0.0.1:1883"
