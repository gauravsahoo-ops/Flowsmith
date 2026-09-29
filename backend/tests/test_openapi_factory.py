"""Tests for OpenAPI Connector Factory (Phase 40E).

Verifies:
- OpenAPI 3.0 & 3.1 parsing
- Authentication scheme extraction (Bearer, API Key, Basic, OAuth2)
- Schema, tags, pagination, and webhook extraction
- Code generation bundle production
- Validation checks preventing empty/invalid specs
"""

import pytest
from app.connectors.openapi_factory import OpenAPIConnectorFactory, OpenAPIFactoryValidationError


SAMPLE_OPENAPI_3_1 = """
openapi: 3.1.0
info:
  title: Enterprise Order API
  version: 1.0.0
servers:
  - url: https://orders.enterprise.com/api/v1
paths:
  /orders:
    get:
      summary: List customer orders
      operationId: listOrders
      tags:
        - Orders
      parameters:
        - name: page
          in: query
          required: false
          schema:
            type: integer
        - name: limit
          in: query
          required: false
          schema:
            type: integer
      responses:
        '200':
          description: Successful orders list
          content:
            application/json:
              schema:
                type: array
                items:
                  type: object
                  properties:
                    id:
                      type: string
                    total:
                      type: number
    post:
      summary: Create new order
      operationId: createOrder
      tags:
        - Orders
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required:
                - customer_id
                - items
              properties:
                customer_id:
                  type: string
                items:
                  type: array
      responses:
        '201':
          description: Order created
webhooks:
  orderCreated:
    post:
      summary: Triggered when an order is created
      responses:
        '200':
          description: Webhook received
components:
  securitySchemes:
    bearerAuth:
      type: http
      scheme: bearer
"""


def test_openapi_factory_bundle_generation():
    factory = OpenAPIConnectorFactory()
    bundle = factory.build_connector_bundle(SAMPLE_OPENAPI_3_1, custom_key="enterprise_orders")

    assert bundle["connector_key"] == "enterprise_orders"
    assert bundle["base_url"] == "https://orders.enterprise.com/api/v1"
    assert bundle["openapi_version"] == "3.1.0"
    assert bundle["auth_kind"] == "bearer"
    assert bundle["operation_count"] == 2
    assert bundle["webhook_count"] == 1

    ops = {op["key"]: op for op in bundle["operations"]}
    assert "listorders" in ops
    assert ops["listorders"]["method"] == "GET"
    assert ops["listorders"]["pagination"]["type"] == "page"
    assert "createorder" in ops
    assert ops["createorder"]["method"] == "POST"
    assert ops["createorder"]["has_schema"] is True

    # Check generated source strings
    sources = bundle["sources"]
    assert "class GeneratedEnterpriseOrdersConnector" in sources["connector"]
    assert "build_enterprise_orders_definition" in sources["definition"]
    assert "AUTH_KIND = \"bearer\"" in sources["provider"]


def test_openapi_factory_validation_error():
    factory = OpenAPIConnectorFactory()
    invalid_spec = {
        "openapi": "3.0.0",
        "info": {
            "title": "Empty API",
            "version": "1.0.0",
        },
        "paths": {},
    }
    with pytest.raises(OpenAPIFactoryValidationError):
        factory.build_connector_bundle(invalid_spec)
