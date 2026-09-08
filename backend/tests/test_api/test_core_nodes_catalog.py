"""Catalog inclusion for Phase 43 nodes."""
import pytest

from tests.test_api.conftest import auth_headers, register


def test_new_nodes_in_catalog_metadata(client):
    headers = auth_headers(register(client)["token"])
    body = client.get("/api/nodes", headers=headers).json()["data"]
    types = {n["type"] for n in body}
    assert {"switch", "filter", "wait", "graphql"} <= types
