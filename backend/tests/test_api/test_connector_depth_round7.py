"""Depth pass 7: ActiveCampaign, BigQuery, Bitbucket, Brevo, ClickUp, and Coda."""

from __future__ import annotations

import pytest

from app.connectors import ensure_builtin_connectors, get_registry


@pytest.fixture(autouse=True)
def _connectors():
    ensure_builtin_connectors()


@pytest.mark.asyncio
async def test_activecampaign_update_and_delete_contact(monkeypatch):
    from app.providers.activecampaign import ActiveCampaignProviderClient

    client = ActiveCampaignProviderClient()
    calls = []

    async def fake_request(creds, method, path, **kwargs):
        calls.append((method, path, kwargs))
        if method == "PUT":
            return {"contact": {"id": "c1", "firstName": "Ada"}}
        return {}

    monkeypatch.setattr(client, "request_activecampaign", fake_request)
    creds = {"account": "acme", "api_key": "token"}

    updated = await client.update_contact(creds, "c1", {"firstName": "Ada"})
    assert updated["contact"]["firstName"] == "Ada"
    assert calls[0][2]["json_body"]["contact"]["firstName"] == "Ada"

    deleted = await client.delete_contact(creds, "c1")
    assert deleted["deleted"] is True
    assert calls[-1][0] == "DELETE"


@pytest.mark.asyncio
async def test_bigquery_get_dataset_and_insert_rows(monkeypatch):
    from app.providers.bigquery import BigQueryProviderClient

    client = BigQueryProviderClient()
    calls = []

    async def fake_request(creds, method, path, **kwargs):
        calls.append((method, path, kwargs))
        if method == "GET":
            return {"datasetReference": {"datasetId": "analytics"}}
        return {"kind": "bigquery#tableDataInsertAllResponse"}

    monkeypatch.setattr(client, "request_bigquery", fake_request)
    creds = {"project_id": "proj", "access_token": "token"}

    dataset = await client.get_dataset(creds, "analytics")
    assert dataset["datasetReference"]["datasetId"] == "analytics"

    inserted = await client.insert_rows(creds, "analytics", "events", [{"id": 1}])
    assert inserted["kind"].startswith("bigquery")
    assert calls[-1][2]["json_body"]["rows"][0]["json"] == {"id": 1}


@pytest.mark.asyncio
async def test_bitbucket_branches_and_pull_request(monkeypatch):
    from app.providers.bitbucket import BitbucketProviderClient

    client = BitbucketProviderClient()
    calls = []

    async def fake_request(method, path, creds, **kwargs):
        calls.append((method, path, kwargs))
        if method == "GET":
            return {"values": [{"name": "main"}]}
        return {"id": 7, "title": "Add docs"}

    monkeypatch.setattr(client, "_request", fake_request)
    creds = {"access_token": "token"}

    branches = await client.list_branches(creds, "acme", "app")
    assert branches[0]["name"] == "main"

    pr = await client.create_pull_request(
        creds, "acme", "app", "Add docs", "feature", "main", description="Docs",
    )
    assert pr["id"] == 7
    assert calls[-1][2]["json_body"]["source"]["branch"]["name"] == "feature"


@pytest.mark.asyncio
async def test_brevo_list_lists_and_delete_contact(monkeypatch):
    from app.providers.brevo import BrevoProviderClient

    client = BrevoProviderClient()
    calls = []

    async def fake_request(creds, method, path, what, **kwargs):
        calls.append((method, path, kwargs))
        if method == "GET":
            return {"lists": [{"id": 1, "name": "Newsletter"}]}
        return {}

    monkeypatch.setattr(client, "_request", fake_request)
    creds = {"api_key": "token"}

    lists = await client.list_lists(creds)
    assert lists["lists"][0]["name"] == "Newsletter"

    deleted = await client.delete_contact(creds, "ada@example.com")
    assert deleted["deleted"] is True
    assert calls[-1][0] == "DELETE"


@pytest.mark.asyncio
async def test_clickup_list_lists_and_delete_task(monkeypatch):
    from app.providers.clickup import ClickUpProviderClient

    client = ClickUpProviderClient()
    calls = []

    async def fake_get(creds, path, what, params=None, timeout=30.0):
        calls.append(("GET", path))
        return {"lists": [{"id": "l1", "name": "Sprint"}]}

    async def fake_request(creds, method, path, what, **kwargs):
        calls.append((method, path))
        return {}

    monkeypatch.setattr(client, "_get", fake_get)
    monkeypatch.setattr(client, "_request", fake_request)
    creds = {"api_key": "token"}

    lists = await client.list_lists(creds, "space1")
    assert lists["lists"][0]["name"] == "Sprint"

    deleted = await client.delete_task(creds, "t1")
    assert deleted["deleted"] is True
    assert calls[-1][0] == "DELETE"


@pytest.mark.asyncio
async def test_coda_update_and_delete_row(monkeypatch):
    from app.providers.coda import CodaProviderClient

    client = CodaProviderClient()
    calls = []

    async def fake_request(creds, method, path, **kwargs):
        calls.append((method, path, kwargs))
        if method == "PUT":
            return {"requestId": "r1", "id": "row1"}
        return {}

    monkeypatch.setattr(client, "request_coda", fake_request)
    creds = {"api_key": "token"}

    updated = await client.update_row(
        creds, "doc1", "table1", "row1", {"cells": [{"column": "Name", "value": "Ada"}]},
    )
    assert updated["id"] == "row1"
    assert calls[0][2]["json_body"]["row"]["cells"][0]["value"] == "Ada"

    deleted = await client.delete_row(creds, "doc1", "table1", "row1")
    assert deleted["deleted"] is True
    assert calls[-1][0] == "DELETE"


@pytest.mark.asyncio
async def test_depth_round7_connector_routes_map_new_operations(monkeypatch):
    from app.connectors.activecampaign_connector import ActiveCampaignConnector
    from app.connectors.bigquery_connector import BigQueryConnector
    from app.connectors.bitbucket_connector import BitbucketConnector
    from app.connectors.brevo_connector import BrevoConnector
    from app.connectors.clickup_connector import ClickUpConnector
    from app.connectors.coda_connector import CodaConnector

    activecampaign = ActiveCampaignConnector()

    async def fake_delete(creds, contact_id, **kwargs):
        assert contact_id == "c1"
        return {"contact_id": contact_id, "deleted": True}

    monkeypatch.setattr(activecampaign._provider, "delete_contact", fake_delete)
    deleted = await activecampaign.op_execute(
        "delete_contact", {"contact_id": "c1"},
        context={"credentials": {"activecampaign": {"account": "acme", "api_key": "x"}}},
    )
    assert deleted["deleted"] is True

    bigquery = BigQueryConnector()

    async def fake_insert(creds, dataset_id, table_id, rows, **kwargs):
        assert (dataset_id, table_id, rows) == ("d1", "t1", [{"id": 1}])
        return {"kind": "ok"}

    monkeypatch.setattr(bigquery._provider, "insert_rows", fake_insert)
    inserted = await bigquery.op_execute(
        "insert_rows", {"dataset_id": "d1", "table_id": "t1", "rows": [{"id": 1}]},
        context={"credentials": {"bigquery": {"project_id": "p", "access_token": "x"}}},
    )
    assert inserted["kind"] == "ok"

    bitbucket = BitbucketConnector()

    async def fake_pr(creds, workspace, repo, title, source_branch, destination_branch,
                      description="", **kwargs):
        assert (workspace, repo, title) == ("acme", "app", "Add docs")
        return {"id": 7}

    monkeypatch.setattr(bitbucket._provider, "create_pull_request", fake_pr)
    pr = await bitbucket.op_execute(
        "create_pull_request", {
            "workspace": "acme", "repo_slug": "app", "title": "Add docs",
            "source_branch": "feature", "destination_branch": "main",
        },
        context={"credentials": {"bitbucket": {"access_token": "x"}}},
    )
    assert pr["id"] == 7

    brevo = BrevoConnector()

    async def fake_lists(creds, limit, **kwargs):
        return {"lists": [{"id": 1}]}

    monkeypatch.setattr(brevo._provider, "list_lists", fake_lists)
    lists = await brevo.op_execute(
        "list_lists", {}, context={"credentials": {"brevo": {"api_key": "x"}}},
    )
    assert lists["lists"][0]["id"] == 1

    clickup = ClickUpConnector()

    async def fake_delete_task(creds, task_id, **kwargs):
        assert task_id == "t1"
        return {"task_id": task_id, "deleted": True}

    monkeypatch.setattr(clickup._provider, "delete_task", fake_delete_task)
    deleted = await clickup.op_execute(
        "delete_task", {"task_id": "t1"},
        context={"credentials": {"clickup": {"api_key": "x"}}},
    )
    assert deleted["deleted"] is True

    coda = CodaConnector()

    async def fake_update_row(creds, doc_id, table_id, row_id, row, **kwargs):
        assert (doc_id, table_id, row_id) == ("doc1", "table1", "row1")
        return {"id": row_id}

    monkeypatch.setattr(coda._provider, "update_row", fake_update_row)
    updated = await coda.op_execute(
        "update_row", {
            "doc_id": "doc1", "table_id": "table1", "row_id": "row1",
            "row": {"cells": [{"column": "Name", "value": "Ada"}]},
        },
        context={"credentials": {"coda": {"api_key": "x"}}},
    )
    assert updated["id"] == "row1"


def test_depth_round7_definitions_expose_new_operations():
    expected = {
        "activecampaign": {"update_contact", "delete_contact"},
        "bigquery": {"get_dataset", "insert_rows"},
        "bitbucket": {"list_branches", "create_pull_request"},
        "brevo": {"list_lists", "delete_contact"},
        "clickup": {"list_lists", "delete_task"},
        "coda": {"update_row", "delete_row"},
    }
    for key, operations in expected.items():
        definition = get_registry().get_definition(key)
        assert definition is not None
        assert operations <= set(definition.operations), (key, set(definition.operations))
