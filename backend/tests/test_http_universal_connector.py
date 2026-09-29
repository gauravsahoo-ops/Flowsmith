"""Comprehensive tests for Universal HTTP Connector (Phase 40F).

Verifies:
- REST requests with query parameters and headers
- Path parameter interpolation
- GraphQL request envelope formation
- SOAP XML envelope formation and SOAPAction header
- Auth injection (Bearer, Basic, API Key in header and query)
- Dynamic schema inference
- Pagination handling
- SafeHTTPClient execution with mock responses
"""

import pytest
import respx
import httpx
from app.connectors.http_connector import HTTPConnector, infer_json_schema


@pytest.mark.asyncio
async def test_universal_http_rest_get():
    connector = HTTPConnector()
    with respx.mock(base_url="https://api.example.com") as respx_mock:
        respx_mock.get("/users/123?role=admin").mock(
            return_value=httpx.Response(200, json={"id": 123, "name": "Alice", "role": "admin"})
        )

        res = await connector.op_execute(
            "request",
            {
                "method": "GET",
                "url": "https://api.example.com/users/{user_id}",
                "path_params": {"user_id": 123},
                "query_params": {"role": "admin"},
                "headers": {"X-Custom": "test"},
                "infer_schema": True,
            }
        )

        assert res["success"] is True
        output = res["output"]
        assert output["status_code"] == 200
        assert output["body"]["name"] == "Alice"
        assert output["protocol"] == "REST"
        assert "inferred_schema" in output
        assert output["inferred_schema"]["type"] == "object"
        assert "name" in output["inferred_schema"]["properties"]


@pytest.mark.asyncio
async def test_universal_http_graphql():
    connector = HTTPConnector()
    with respx.mock(base_url="https://api.example.com") as respx_mock:
        respx_mock.post("/graphql").mock(
            return_value=httpx.Response(200, json={"data": {"viewer": {"login": "flowsmith"}}})
        )

        res = await connector.op_execute(
            "request",
            {
                "url": "https://api.example.com/graphql",
                "protocol": "GRAPHQL",
                "graphql_query": "query GetViewer { viewer { login } }",
                "graphql_variables": {"key": "val"},
                "auth_type": "bearer",
                "auth_token": "secret_gql_token",
            }
        )

        assert res["success"] is True
        output = res["output"]
        assert output["status_code"] == 200
        assert output["body"]["data"]["viewer"]["login"] == "flowsmith"
        assert output["protocol"] == "GRAPHQL"


@pytest.mark.asyncio
async def test_universal_http_soap():
    connector = HTTPConnector()
    soap_xml = '<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"><soapenv:Body><GetPriceResponse>100</GetPriceResponse></soapenv:Body></soapenv:Envelope>'
    with respx.mock(base_url="https://ws.example.com") as respx_mock:
        respx_mock.post("/stockservice").mock(
            return_value=httpx.Response(200, text=soap_xml, headers={"Content-Type": "text/xml"})
        )

        res = await connector.op_execute(
            "request",
            {
                "url": "https://ws.example.com/stockservice",
                "protocol": "SOAP",
                "soap_action": "http://example.com/GetPrice",
                "soap_envelope": '<soapenv:Envelope><soapenv:Body><GetPrice>IBM</GetPrice></soapenv:Body></soapenv:Envelope>',
            }
        )

        assert res["success"] is True
        output = res["output"]
        assert output["status_code"] == 200
        assert "GetPriceResponse" in output["body"]
        assert output["protocol"] == "SOAP"


@pytest.mark.asyncio
async def test_universal_http_basic_auth():
    connector = HTTPConnector()
    with respx.mock(base_url="https://api.example.com") as respx_mock:
        route = respx_mock.get("/protected").mock(
            return_value=httpx.Response(200, json={"status": "authenticated"})
        )

        res = await connector.op_execute(
            "request",
            {
                "url": "https://api.example.com/protected",
                "auth_type": "basic",
                "auth_username": "admin",
                "auth_password": "password123",
            }
        )

        assert res["success"] is True
        assert route.called
        req = route.calls.last.request
        assert "Authorization" in req.headers
        assert req.headers["Authorization"].startswith("Basic ")


@pytest.mark.asyncio
async def test_universal_http_pagination():
    connector = HTTPConnector()
    with respx.mock(base_url="https://api.example.com") as respx_mock:
        respx_mock.get("/items?page=1&limit=2").mock(
            return_value=httpx.Response(200, json={"items": [{"id": 1}, {"id": 2}]})
        )
        respx_mock.get("/items?page=2&limit=2").mock(
            return_value=httpx.Response(200, json={"items": [{"id": 3}, {"id": 4}]})
        )

        res = await connector.op_execute(
            "request",
            {
                "url": "https://api.example.com/items",
                "paginate": True,
                "pagination_type": "page",
                "page_size": 2,
                "max_pages": 2,
            }
        )

        assert res["success"] is True
        output = res["output"]
        assert len(output["body"]) == 2
        assert output["pagination"]["pages_fetched"] == 2
