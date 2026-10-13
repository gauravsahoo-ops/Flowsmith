"""Unit tests for Kafka, Oracle, and MQTT connectors."""

import pytest
from app.connectors.kafka_connector import KafkaConnector
from app.connectors.oracle_connector import OracleConnector
from app.connectors.mqtt_connector import MQTTConnector
from app.connectors.kafka_definition import build_kafka_definition
from app.connectors.oracle_definition import build_oracle_definition
from app.connectors.mqtt_definition import build_mqtt_definition
from app.credentials.registry import is_known_type, is_implemented, validate_data


@pytest.mark.asyncio
async def test_kafka_connector_lifecycle_and_operations():
    connector = KafkaConnector()
    definition = build_kafka_definition()

    assert definition.connector_key == "kafka"
    assert "produce" in definition.operations
    assert "consume" in definition.operations
    assert "list_topics" in definition.operations

    # Test connect
    assert not await connector.connect({})
    assert await connector.connect({"bootstrap_servers": "localhost:9092"})

    # Test produce
    prod_res = await connector.op_execute("produce", {
        "topic": "test-events",
        "message_key": "k1",
        "payload": {"event": "user_signup", "id": 123},
    })
    assert prod_res["status"] == "published"
    assert prod_res["topic"] == "test-events"

    # Test consume
    cons_res = await connector.op_execute("consume", {"topic": "test-events", "max_messages": 5})
    assert "output" in cons_res
    assert len(cons_res["output"]) <= 5

    # Test list_topics
    top_res = await connector.op_execute("list_topics", {})
    assert "topics" in top_res
    assert len(top_res["topics"]) > 0


@pytest.mark.asyncio
async def test_oracle_connector_lifecycle_and_operations():
    connector = OracleConnector()
    definition = build_oracle_definition()

    assert definition.connector_key == "oracle"
    assert "query" in definition.operations
    assert "insert" in definition.operations
    assert "table_list" in definition.operations

    # Test connect
    assert not await connector.connect({})
    assert await connector.connect({"host": "oracle.local", "username": "admin", "password": "pwd"})

    # Test query
    q_res = await connector.op_execute("query", {"query": "SELECT * FROM EMPLOYEES"})
    assert "rows" in q_res
    assert q_res["row_count"] >= 1

    # Test insert
    ins_res = await connector.op_execute("insert", {"table": "CUSTOMERS", "data": {"NAME": "ACME"}})
    assert ins_res["status"] == "success"

    # Test table_list
    t_res = await connector.op_execute("table_list", {})
    assert "tables" in t_res


@pytest.mark.asyncio
async def test_mqtt_connector_lifecycle_and_operations():
    connector = MQTTConnector()
    definition = build_mqtt_definition()

    assert definition.connector_key == "mqtt"
    assert "publish" in definition.operations
    assert "consume" in definition.operations

    # Test connect
    assert not await connector.connect({})
    assert await connector.connect({"broker_url": "broker.emqx.io"})

    # Test publish
    pub_res = await connector.op_execute("publish", {
        "topic": "sensors/ambient",
        "payload": {"temp": 24.5},
        "qos": 1,
    })
    assert pub_res["status"] == "published"
    assert pub_res["topic"] == "sensors/ambient"

    # Test consume
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
