"""Checkpoint seed planner: directive precedence, output replay, and run_job wiring.

The planner is pure, so most coverage is direct. The final test characterizes
the four resume/retry modes through ``run_job`` with ``execute_workflow``
monkeypatched: it pins exactly which persisted outputs the engine would receive.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.engine.executor import ExecutionResult
from app.models import Execution, User, WorkflowRecord
from app.db import get_session
from app.orchestration.checkpoint import (
    RunSeed,
    ancestor_ids,
    plan_seed,
    seed_from_approval,
    seed_from_node_retry,
    seed_from_run_node,
    seed_from_run_to_node,
    seed_mode,
)
from app.queue import QueueJob

# ---------------------------------------------------------------------------
# directive precedence
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (None, "fresh"),
        ({}, "fresh"),
        ({"_approval_data": None}, "fresh"),
        ({"_approval_data": {}}, "approval"),
        ({"_approval_data": {"node_id": "paused"}}, "approval"),
        (
            {
                "_approval_data": {"node_id": "paused"},
                "_retry_from_node": "failed",
                "_run_node": "single",
                "_run_to_node": "target",
            },
            "approval",
        ),
        ({"_retry_from_node": "failed"}, "node_retry"),
        (
            {"_retry_from_node": "failed", "_run_node": "single", "_run_to_node": "target"},
            "node_retry",
        ),
        ({"_retry_from_node": "", "_run_node": "single"}, "run_node"),
        ({"_run_node": "single", "_run_to_node": "target"}, "run_node"),
        ({"_retry_from_node": "", "_run_node": "", "_run_to_node": "target"}, "run_to_node"),
        ({"_run_to_node": "target"}, "run_to_node"),
    ],
)
def test_seed_mode_precedence(payload: dict[str, Any] | None, expected: str) -> None:
    assert seed_mode(payload) == expected


# ---------------------------------------------------------------------------
# ancestry
# ---------------------------------------------------------------------------


def test_ancestor_ids_is_transitive_and_cycle_safe() -> None:
    connections = [
        {"source": "a", "target": "b"},
        {"source": "b", "target": "c"},
        {"source": "c", "target": "a"},
    ]
    # A cycle makes the target its own ancestor; traversal must still terminate.
    assert ancestor_ids(connections, "a") == {"a", "b", "c"}
    assert ancestor_ids(connections, "b") == {"a", "b", "c"}


def test_ancestor_ids_missing_target_and_dangling_edges() -> None:
    connections = [
        {"source": "a", "target": "b"},
        {"source": "ghost", "target": "nowhere"},
    ]
    assert ancestor_ids(connections, "b") == {"a"}
    assert ancestor_ids(connections, "nowhere") == {"ghost"}
    assert ancestor_ids(connections, "missing") == set()
    assert ancestor_ids([], "a") == set()


# ---------------------------------------------------------------------------
# approval resume
# ---------------------------------------------------------------------------


def _results(*node_ids: str) -> dict[str, dict[str, list[dict[str, Any]]]]:
    return {nid: {"main": [{"node": nid}]} for nid in node_ids}


def test_approval_seed_replays_everything_except_paused_node() -> None:
    decision = {"node_id": "paused", "approved": True, "approved_by": 7}
    outputs = _results("start", "paused", "after")

    seed = seed_from_approval(outputs, decision)

    assert seed.mode == "approval"
    assert seed.initial_results == _results("start", "after")
    assert "paused" not in seed.initial_results
    assert seed.storage_seed == {"_approval_data": decision}
    assert seed.storage_seed is not None
    assert seed.storage_seed["_approval_data"] is decision
    assert seed.decision is decision
    assert seed.upstream == set()
    assert seed.doomed == set()
    assert seed.retry_source_id is None
    assert seed.run_source_id is None


def test_approval_seed_preserves_empty_mapping_but_none_stays_none() -> None:
    decision = {"node_id": "paused", "approved": False}
    assert seed_from_approval({}, decision).initial_results == {}
    assert seed_from_approval(None, decision).initial_results is None


@pytest.mark.parametrize("outputs", [None, [], "not-a-mapping", 7])
def test_approval_seed_non_mapping_outputs_yield_none(outputs: Any) -> None:
    decision = {"node_id": "paused", "approved": True}
    seed = seed_from_approval(outputs, decision)
    assert seed.initial_results is None
    assert seed.storage_seed == {"_approval_data": decision}
    assert seed.decision is decision


# ---------------------------------------------------------------------------
# safe node retry
# ---------------------------------------------------------------------------


def test_node_retry_excludes_failed_node_and_descendants_keeps_upstream() -> None:
    connections = [
        {"source": "start", "target": "up"},
        {"source": "up", "target": "failed"},
        {"source": "failed", "target": "down1"},
        {"source": "down1", "target": "down2"},
    ]
    source_outputs = _results("start", "up", "failed", "down1", "down2", "unrelated")

    seed = seed_from_node_retry(connections, "failed", source_outputs)

    assert seed.mode == "node_retry"
    assert seed.doomed == {"failed", "down1", "down2"}
    assert seed.initial_results == _results("start", "up", "unrelated")
    assert seed.upstream == set()
    assert seed.storage_seed is None
    assert seed.decision is None


def test_node_retry_without_source_outputs_is_none_but_doomed_is_kept() -> None:
    connections = [{"source": "failed", "target": "down"}]
    for source_outputs in (None, [], "not-a-mapping"):
        seed = seed_from_node_retry(connections, "failed", source_outputs)
        assert seed.initial_results is None
        assert seed.doomed == {"failed", "down"}

    empty = seed_from_node_retry(connections, "failed", {})
    assert empty.initial_results == {}


# ---------------------------------------------------------------------------
# run-node
# ---------------------------------------------------------------------------


def test_run_node_seed_normalizes_outputs_and_seeds_skipped_nodes() -> None:
    workflow_data = {
        "nodes": [
            {"id": "start"},
            {"id": "up_dict"},
            {"id": "up_list"},
            {"id": "up_missing"},
            {"id": "target"},
            {"id": "down_scalar"},
            {"id": "down_empty"},
            {"id": "island"},
        ],
        "connections": [
            {"source": "start", "target": "up_dict"},
            {"source": "start", "target": "up_list"},
            {"source": "start", "target": "up_missing"},
            {"source": "up_dict", "target": "target"},
            {"source": "up_list", "target": "target"},
            {"source": "up_missing", "target": "target"},
            {"source": "target", "target": "down_scalar"},
            {"source": "target", "target": "down_empty"},
        ],
    }
    dict_output = {"main": [{"node": "start"}]}
    source_outputs = {
        "start": dict_output,
        "up_dict": {"main": [{"node": "up_dict"}]},
        "up_list": [{"node": "up_list"}],
        "down_scalar": "scalar",
    }

    seed = seed_from_run_node(
        workflow_data,
        workflow_data["connections"],
        "target",
        source_outputs,
    )

    assert seed.mode == "run_node"
    assert seed.upstream == {"start", "up_dict", "up_list", "up_missing"}
    assert seed.doomed == set()
    assert seed.storage_seed is None
    assert "target" not in seed.initial_results
    assert seed.initial_results == {
        "start": {"main": [{"node": "start"}]},
        "up_dict": {"main": [{"node": "up_dict"}]},
        "up_list": {"main": [{"node": "up_list"}]},
        "up_missing": {"main": [{}]},
        "down_scalar": {"main": ["scalar"]},
        "down_empty": {"main": []},
        "island": {"main": []},
    }
    # Cached dict outputs are replayed as-is, not copied or reshaped.
    assert seed.initial_results["start"] is dict_output


def test_run_node_without_source_outputs_uses_fallbacks() -> None:
    workflow_data = {
        "nodes": [{"id": "up"}, {"id": "target"}, {"id": "down"}],
        "connections": [
            {"source": "up", "target": "target"},
            {"source": "target", "target": "down"},
        ],
    }
    seed = seed_from_run_node(workflow_data, workflow_data["connections"], "target", None)
    assert seed.initial_results == {
        "up": {"main": [{}]},
        "down": {"main": []},
    }


# ---------------------------------------------------------------------------
# run-to-node
# ---------------------------------------------------------------------------


def test_run_to_node_seed_skips_only_downstream_nodes() -> None:
    connections = [
        {"source": "a", "target": "b"},
        {"source": "b", "target": "c"},
        {"source": "c", "target": "d"},
    ]

    seed = seed_from_run_to_node(connections, "b")

    assert seed.mode == "run_to_node"
    assert seed.initial_results == {"c": {"main": []}, "d": {"main": []}}
    assert "b" not in seed.initial_results
    assert seed.upstream == set()
    assert seed.doomed == set()
    assert seed.storage_seed is None


def test_run_to_node_excludes_target_even_in_a_cycle() -> None:
    connections = [
        {"source": "a", "target": "b"},
        {"source": "b", "target": "a"},
    ]
    seed = seed_from_run_to_node(connections, "b")
    assert seed.initial_results == {"a": {"main": []}}

    empty = seed_from_run_to_node([], "b")
    assert empty.initial_results == {}


# ---------------------------------------------------------------------------
# dispatcher
# ---------------------------------------------------------------------------


def test_plan_seed_fresh_ignores_stray_source_ids() -> None:
    seed = plan_seed(
        {"_retry_source": "exec_a", "_source_execution": "exec_b"},
        workflow_data={"nodes": [], "connections": []},
    )
    assert seed == RunSeed(mode="fresh")
    assert seed.initial_results is None
    assert seed.storage_seed is None
    assert seed.retry_source_id is None
    assert seed.run_source_id is None


def test_plan_seed_approval_wins_and_ignores_lower_precedence_directives() -> None:
    decision = {"node_id": "paused", "approved": True}
    outputs = _results("start", "paused")
    workflow_data = {
        "nodes": [{"id": "start"}, {"id": "paused"}],
        "connections": [{"source": "start", "target": "paused"}],
    }

    seed = plan_seed(
        {
            "_approval_data": decision,
            "_retry_from_node": "paused",
            "_run_node": "start",
            "_run_to_node": "start",
            "_retry_source": "exec_retry",
            "_source_execution": "exec_run",
        },
        workflow_data=workflow_data,
        outputs=outputs,
        retry_outputs=_results("start", "paused"),
        run_outputs=_results("start"),
    )

    assert seed.mode == "approval"
    assert seed.initial_results == _results("start")
    assert seed.storage_seed == {"_approval_data": decision}
    assert seed.decision is decision
    assert seed.retry_source_id is None
    assert seed.run_source_id is None


def test_plan_seed_node_retry_carries_source_id() -> None:
    workflow_data = {
        "nodes": [{"id": "start"}, {"id": "failed"}, {"id": "down"}],
        "connections": [
            {"source": "start", "target": "failed"},
            {"source": "failed", "target": "down"},
        ],
    }
    output = _results("start", "failed", "down")

    seed = plan_seed(
        {"_retry_from_node": "failed", "_retry_source": "exec_source"},
        workflow_data=workflow_data,
        retry_outputs=output,
    )

    assert seed.mode == "node_retry"
    assert seed.doomed == {"failed", "down"}
    assert seed.initial_results == _results("start")
    assert seed.retry_source_id == "exec_source"
    assert seed.run_source_id is None

    no_source = plan_seed(
        {"_retry_from_node": "failed"},
        workflow_data=workflow_data,
        retry_outputs=output,
    )
    assert no_source.retry_source_id is None


def test_plan_seed_run_node_carries_source_id() -> None:
    workflow_data = {
        "nodes": [{"id": "start"}, {"id": "target"}, {"id": "down"}],
        "connections": [
            {"source": "start", "target": "target"},
            {"source": "target", "target": "down"},
        ],
    }

    seed = plan_seed(
        {"_run_node": "target", "_source_execution": "exec_source"},
        workflow_data=workflow_data,
        run_outputs={"start": {"main": [{"node": "start"}]}},
    )

    assert seed.mode == "run_node"
    assert seed.run_source_id == "exec_source"
    assert seed.retry_source_id is None
    assert seed.initial_results == {
        "start": {"main": [{"node": "start"}]},
        "down": {"main": []},
    }

    no_source = plan_seed(
        {"_run_node": "target"},
        workflow_data=workflow_data,
        run_outputs={},
    )
    assert no_source.run_source_id is None


def test_plan_seed_run_to_node() -> None:
    workflow_data = {
        "nodes": [{"id": "a"}, {"id": "b"}, {"id": "c"}],
        "connections": [
            {"source": "a", "target": "b"},
            {"source": "b", "target": "c"},
        ],
    }
    seed = plan_seed(
        {"_run_to_node": "b"},
        workflow_data=workflow_data,
    )
    assert seed.mode == "run_to_node"
    assert seed.initial_results == {"c": {"main": []}}
    assert seed.retry_source_id is None
    assert seed.run_source_id is None


# ---------------------------------------------------------------------------
# characterization: run_job -> execute_workflow seeds
# ---------------------------------------------------------------------------

WF_SEED = {
    "id": "wf_seed",
    "name": "seed",
    "nodes": [
        {"id": "start", "type": "manual_trigger", "parameters": {}},
        {"id": "up", "type": "set_data", "parameters": {"fields": {"v": 1}}},
        {"id": "peer", "type": "set_data", "parameters": {"fields": {"v": 2}}},
        {"id": "target", "type": "set_data", "parameters": {"fields": {"v": 3}}},
        {"id": "down", "type": "set_data", "parameters": {"fields": {"v": 4}}},
    ],
    "connections": [
        {"source": "start", "target": "up"},
        {"source": "up", "target": "target"},
        {"source": "peer", "target": "target"},
        {"source": "target", "target": "down"},
    ],
    "settings": {},
}

PRIOR_OUTPUTS = {
    "start": {"main": [{"node": "start"}]},
    "up": {"main": [{"node": "up"}]},
    "peer": {"main": [{"node": "peer"}]},
    "target": {"main": [{"node": "target"}]},
    "down": {"main": [{"node": "down"}]},
}

APPROVAL_DECISION = {"node_id": "target", "approved": True, "approved_by": 1}

CHARACTERIZATION_CASES: dict[str, dict[str, Any]] = {
    "fresh": {
        "directives": {},
        "current_results": None,
        "source_results": None,
        "expected_initial": None,
        "expected_storage": None,
    },
    "approval": {
        "directives": {"_approval_data": APPROVAL_DECISION},
        "current_results": {
            "outputs": {
                "start": PRIOR_OUTPUTS["start"],
                "target": PRIOR_OUTPUTS["target"],
                "peer": PRIOR_OUTPUTS["peer"],
            }
        },
        "source_results": None,
        "expected_initial": {
            "start": PRIOR_OUTPUTS["start"],
            "peer": PRIOR_OUTPUTS["peer"],
        },
        "expected_storage": {"_approval_data": APPROVAL_DECISION},
    },
    "node_retry": {
        "directives": {
            "_retry_from_node": "target",
            "_retry_source": "exec_source",
        },
        "current_results": None,
        "source_results": {"outputs": PRIOR_OUTPUTS},
        "expected_initial": {
            "start": PRIOR_OUTPUTS["start"],
            "up": PRIOR_OUTPUTS["up"],
            "peer": PRIOR_OUTPUTS["peer"],
        },
        "expected_storage": None,
    },
    "run_node": {
        "directives": {
            "_run_node": "target",
            "_source_execution": "exec_source",
        },
        "current_results": None,
        "source_results": {
            "outputs": {
                "start": PRIOR_OUTPUTS["start"],
                "up": [{"node": "up"}],
                "peer": "peer-scalar",
            }
        },
        "expected_initial": {
            "start": PRIOR_OUTPUTS["start"],
            "up": {"main": [{"node": "up"}]},
            "peer": {"main": ["peer-scalar"]},
            "down": {"main": []},
        },
        "expected_storage": None,
    },
    "run_to_node": {
        "directives": {"_run_to_node": "target"},
        "current_results": None,
        "source_results": None,
        "expected_initial": {"down": {"main": []}},
        "expected_storage": None,
    },
}


@pytest.mark.parametrize("case_name", list(CHARACTERIZATION_CASES))
def test_run_job_passes_planner_seeds_to_execute_workflow(
    case_name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = CHARACTERIZATION_CASES[case_name]
    user_id = 1
    execution_id = "exec_current"
    source_id = "exec_source"

    db = get_session()
    try:
        db.add(User(id=user_id, email="seed@example.com", password_hash="x"))
        db.add(
            WorkflowRecord(
                id=WF_SEED["id"],
                user_id=user_id,
                name=WF_SEED["name"],
                version=1,
                active=True,
                data=WF_SEED,
            )
        )
        db.flush()
        db.add(
            Execution(
                id=execution_id,
                workflow_id=WF_SEED["id"],
                user_id=user_id,
                workflow_version=1,
                workflow_data=WF_SEED,
                trigger="manual",
                trigger_data=[{}],
                status="queued",
                results=case["current_results"],
            )
        )
        if case["source_results"] is not None:
            db.add(
                Execution(
                    id=source_id,
                    workflow_id=WF_SEED["id"],
                    user_id=user_id,
                    workflow_version=1,
                    workflow_data=WF_SEED,
                    trigger="manual",
                    trigger_data=[{}],
                    status="success",
                    results=case["source_results"],
                )
            )
        db.commit()
    finally:
        db.close()

    captured: dict[str, Any] = {}

    async def fake_execute_workflow(workflow: Any, trigger_items: Any, **kwargs: Any) -> ExecutionResult:
        captured.update(kwargs)
        return ExecutionResult(status="success", results={})

    monkeypatch.setattr("app.execution_runtime.execute_workflow", fake_execute_workflow)

    from app.execution_runtime import run_job

    job = QueueJob(
        id="job_seed",
        execution_id=execution_id,
        payload={
            "workflow_data": WF_SEED,
            "trigger_items": [{}],
            "trigger": "manual",
            "user_id": user_id,
            "workflow_id": WF_SEED["id"],
            "version": 1,
            "workspace_id": None,
            **case["directives"],
        },
    )

    status = asyncio.run(run_job(job, lambda event: None))

    assert status == "success"
    assert captured["initial_results"] == case["expected_initial"]
    assert captured["storage_seed"] == case["expected_storage"]
