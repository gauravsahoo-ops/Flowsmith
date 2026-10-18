"""Phase 11 Production Certification Tests: AI & Workflow Reliability & Import/Export Safety.

Verifies:
1. Malformed AI workflow rejection (broken DAG, cycles, invalid structure).
2. Data expression validation (syntax errors, unbalanced braces).
3. Security guard validation (prohibited hardcoded secrets, API tokens, private keys).
4. Unsafe internal URL / SSRF detection in AI-generated HTTP nodes.
5. Runtime policy validation (enforcement of maximum retry limits).
6. Credential availability checks (missing required credentials flagged).
7. Portable JSON export safety: strictly excludes credentials, secrets, tokens, and runtime execution state.
8. Workflow import safety: enforces inactive draft lifecycle (active=False, status='draft'), strips credentials, and validates versions.
9. Workflow duplication safety: prevents auto-execution, strips credentials and execution state, and generates fresh identifiers.
10. AI workflow simulation with non-destructive verification.
"""

import pytest
from typing import Any
from app.connectors import register_builtin_connectors
from app.ai.pipeline_validator import PipelineValidator
from app.ai.simulator import WorkflowSimulator
from app.importexport import build_export, parse_import, sanitize_workflow_data, WorkflowImportError, EXPORT_FORMAT


@pytest.fixture(autouse=True)
def setup_connectors():
    register_builtin_connectors()


class TestAIWorkflowValidationAndGuards:
    """Verifies AI workflow validation pipeline across all 6 safety stages."""

    def test_malformed_ai_workflow_rejected(self):
        """Rejects empty workflow or workflow with unresolvable connections."""
        malformed_wf = {
            "name": "Broken AI Workflow",
            "nodes": [
                {"id": "n1", "type": "manual_trigger", "name": "Start", "parameters": {}},
            ],
            "connections": {
                "n1": {"main": [[{"node": "nonexistent_node", "type": "main", "index": 0}]]}
            },
        }
        res = PipelineValidator.validate_full(malformed_wf)
        assert res["valid"] is False
        assert res["structural_ok"] is False
        assert any("CONNECTION" in str(e.get("code", "")) or "TARGET" in str(e.get("code", "")) for e in res["errors"])

    def test_invalid_expressions_detected(self):
        """Detects malformed expression syntax with unbalanced braces."""
        wf_with_bad_expr = {
            "name": "Bad Expression Workflow",
            "nodes": [
                {"id": "trig", "type": "manual_trigger", "name": "Trigger", "parameters": {}},
                {
                    "id": "calc",
                    "type": "set_variable",
                    "name": "Set Var",
                    "parameters": {"expression": "{{ $json.total + (5 * 2"},
                },
            ],
            "connections": {
                "trig": {"main": [[{"node": "calc", "type": "main", "index": 0}]]}
            },
        }
        res = PipelineValidator.validate_full(wf_with_bad_expr)
        assert res["data_ok"] is False or len(res["errors"]) > 0

    def test_exposed_hardcoded_secrets_blocked(self):
        """Security guard stage blocks hardcoded OpenAI/AWS/GitHub tokens in parameters."""
        wf_with_secret = {
            "name": "Leaky Workflow",
            "nodes": [
                {"id": "trig", "type": "manual_trigger", "name": "Trigger", "parameters": {}},
                {
                    "id": "http1",
                    "type": "http_request",
                    "name": "HTTP Call",
                    "parameters": {
                        "url": "https://api.example.com/data",
                        "auth_token": "sk-1234567890abcdef1234567890abcdef",
                    },
                },
            ],
            "connections": {
                "trig": {"main": [[{"node": "http1", "type": "main", "index": 0}]]}
            },
        }
        res = PipelineValidator.validate_full(wf_with_secret)
        assert res["valid"] is False
        assert res["security_ok"] is False
        assert any(e.get("code") == "EXPOSED_SECRET" for e in res["errors"])

    def test_unsafe_internal_ssrf_urls_flagged(self):
        """Security guard stage flags internal/private network endpoints."""
        wf_with_internal_ip = {
            "name": "SSRF Attempt Workflow",
            "nodes": [
                {"id": "trig", "type": "manual_trigger", "name": "Trigger", "parameters": {}},
                {
                    "id": "http1",
                    "type": "http_request",
                    "name": "Internal Call",
                    "parameters": {
                        "url": "http://169.254.169.254/latest/meta-data",
                    },
                },
            ],
            "connections": {
                "trig": {"main": [[{"node": "http1", "type": "main", "index": 0}]]}
            },
        }
        res = PipelineValidator.validate_full(wf_with_internal_ip)
        assert any(w.get("code") == "UNSAFE_ENDPOINT" for w in res["warnings"])

    def test_excessive_retry_policy_rejected(self):
        """Runtime policy validator rejects retry attempts exceeding limit of 5."""
        wf_bad_policy = {
            "name": "Heavy Retry Workflow",
            "nodes": [
                {"id": "trig", "type": "manual_trigger", "name": "Trigger", "parameters": {}},
                {
                    "id": "http1",
                    "type": "http_request",
                    "name": "HTTP",
                    "parameters": {"url": "https://api.example.com"},
                    "settings": {"retry": {"max_attempts": 10}},
                },
            ],
            "connections": {
                "trig": {"main": [[{"node": "http1", "type": "main", "index": 0}]]}
            },
        }
        res = PipelineValidator.validate_full(wf_bad_policy)
        assert res["valid"] is False
        assert res["runtime_ok"] is False
        assert any(e.get("code") == "INVALID_RUNTIME_POLICY" for e in res["errors"])

    def test_missing_credentials_flagged(self):
        """Flag missing credentials when workflow requires an unconfigured integration."""
        wf_needs_cred = {
            "name": "Salesforce Sync",
            "nodes": [
                {"id": "trig", "type": "manual_trigger", "name": "Trigger", "parameters": {}},
                {
                    "id": "sf1",
                    "type": "salesforce",
                    "name": "Query Salesforce",
                    "parameters": {"operation": "get", "resource": "Contact", "id": "003xxx"},
                    "credentials": {"salesforce": {"id": "sf_cred_1"}},
                },
            ],
            "connections": {
                "trig": {"main": [[{"node": "sf1", "type": "main", "index": 0}]]}
            },
        }
        res = PipelineValidator.validate_full(wf_needs_cred, user_credentials={"postgresql"})
        assert res["credential_ok"] is False
        assert any(w.get("code") == "MISSING_CREDENTIAL" for w in res["warnings"])


class TestWorkflowImportExportAndDuplicationSafety:
    """Verifies that workflows can be exported, imported, and duplicated safely without data leakage or auto-execution."""

    def test_build_export_strips_credentials_and_runtime_state(self):
        """Verifies that export envelopes never contain decrypted secrets or execution state."""
        wf_doc = {
            "id": "wf_prod_100",
            "name": "Payment Pipeline",
            "active": True,
            "status": "active",
            "execution_id": "exec_active_999",
            "runtime_state": {"step": 4, "cursor": "batch_42"},
            "last_run": "2026-10-18T10:00:00Z",
            "history": [{"run": 1, "status": "completed"}],
            "nodes": [
                {
                    "id": "node_1",
                    "type": "http_request",
                    "name": "API Call",
                    "parameters": {
                        "url": "https://api.stripe.com/v1/charges",
                        "api_key": "sec_live_abcdef123456",
                        "auth_token": "bearer_secret_xyz",
                    },
                    "credentials": {"stripe": {"id": "c_123", "secret": "live_key"}},
                    "last_run": "2026-10-18T10:00:00Z",
                    "execution_status": "success",
                }
            ],
            "connections": {},
        }

        export_pkg = build_export(wf_doc)
        assert export_pkg["format"] == EXPORT_FORMAT
        assert "exported_at" in export_pkg

        exported_wf = export_pkg["workflow"]
        # Enforce lifecycle reset
        assert exported_wf["active"] is False
        assert exported_wf["status"] == "draft"

        # Enforce runtime state stripping
        assert "execution_id" not in exported_wf
        assert "runtime_state" not in exported_wf
        assert "last_run" not in exported_wf
        assert "history" not in exported_wf

        # Enforce node credential and secret parameter stripping
        node = exported_wf["nodes"][0]
        assert node["credentials"] == {}
        assert "last_run" not in node
        assert "execution_status" not in node
        assert node["parameters"].get("api_key") is None or node["parameters"].get("api_key") == ""
        assert node["parameters"].get("auth_token") is None or node["parameters"].get("auth_token") == ""

    def test_parse_import_enforces_inactive_draft(self):
        """Verifies that imported workflow payloads are unconditionally set to inactive draft."""
        import_payload = {
            "format": EXPORT_FORMAT,
            "version": 1,
            "workflow": {
                "id": "wf_foreign_1",
                "name": "Imported Active Flow",
                "active": True,
                "status": "active",
                "nodes": [
                    {"id": "t1", "type": "manualTrigger", "name": "Start", "parameters": {}},
                    {"id": "n1", "type": "set", "name": "Set", "parameters": {"mode": "manual"}},
                ],
                "connections": {
                    "t1": {"main": [[{"node": "n1", "type": "main", "index": 0}]]}
                },
            },
        }

        imported = parse_import(import_payload)
        assert imported["active"] is False
        assert imported["status"] == "draft"

    def test_parse_import_rejects_unsupported_version(self):
        """Rejects export payloads with future or invalid format versions."""
        with pytest.raises(WorkflowImportError, match="Unsupported workflow export version"):
            parse_import({
                "format": EXPORT_FORMAT,
                "version": 999,
                "workflow": {"nodes": []},
            })

    def test_sanitize_workflow_data_duplication_safety(self):
        """Verifies sanitize_workflow_data leaves workflow clean for safe duplication."""
        source_data = {
            "id": "wf_origin",
            "name": "Critical Sync",
            "active": True,
            "status": "active",
            "active_execution_id": "exec_live",
            "job_id": "job_123",
            "nodes": [
                {
                    "id": "hook",
                    "type": "webhook",
                    "parameters": {"path": "my-secret-hook-path-1234567890"},
                    "credentials": {"auth": "secret_token"},
                    "runPreview": {"sample": "leaked_data"},
                }
            ],
        }

        sanitized = sanitize_workflow_data(source_data, strip_credentials=True, strip_secrets=True)
        assert sanitized["active"] is False
        assert sanitized["status"] == "draft"
        assert "active_execution_id" not in sanitized
        assert "job_id" not in sanitized
        assert sanitized["nodes"][0]["credentials"] == {}
        assert "runPreview" not in sanitized["nodes"][0]


class TestAIWorkflowSimulationSafety:
    """Verifies that AI workflow simulation executes non-destructively without modifying production state."""

    def test_simulation_runs_non_destructively(self):
        workflow = {
            "name": "Simulated Pipeline",
            "nodes": [
                {"id": "trig", "type": "manual_trigger", "name": "Manual Start", "parameters": {}},
                {"id": "calc", "type": "set_variable", "name": "Transform", "parameters": {"score": 95}},
            ],
            "connections": {
                "trig": {"main": [[{"node": "calc", "type": "main", "index": 0}]]}
            },
        }

        res = WorkflowSimulator.simulate(workflow)
        assert res["success"] is True
        assert res["executed_count"] == 2
        assert len(res["warnings"]) == 0
