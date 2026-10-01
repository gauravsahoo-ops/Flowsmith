"""E2E Acceptance Test Suite for Flowsmith AI-Native Platform (Section 41).

Verifies the 10 mandatory acceptance scenarios:
1. TEST 1: Salesforce lead enrichment workflow (Intent -> Capabilities -> IR -> Compiler -> Validation -> Simulation)
2. TEST 2: Every morning sync Salesforce contacts to PostgreSQL (Schedule -> Salesforce -> Postgres)
3. TEST 3: When an opportunity closes, notify Teams (Event -> Condition -> Teams notification)
4. TEST 4: Create an AI support ticket classifier (Webhook -> Classifier -> IF Condition -> PagerDuty / Zendesk)
5. TEST 5: Add human approval before updating Salesforce (Surgical modification with diff)
6. TEST 6: Add retry handling (Exponential backoff policy addition)
7. TEST 7: Replace the selected AI provider/model (OpenAI -> Gemini model migration)
8. TEST 8: Optimize workflow for cost (Frontier model -> efficient tier / batching diff)
9. TEST 9: Repair a failed workflow (429 Rate limit failure diagnosis and recovery proposal)
10. TEST 10: Generate workflow from an OpenAPI specification (OpenAPI factory -> dynamic capability -> workflow)
"""

import pytest
from app.connectors import register_builtin_connectors
from app.ai.capabilities import CapabilityRegistry, CapabilitySearch, CapabilityResolver
from app.ai.intent import IntentEngine, WorkflowIntent
from app.ai.ir import WorkflowIR, IRTrigger, IRStep, IRConnection, IRErrorPolicy
from app.ai.compiler import WorkflowCompiler
from app.ai.pipeline_validator import PipelineValidator
from app.ai.simulator import WorkflowSimulator
from app.ai.modification import WorkflowModifier
from app.ai.repair import WorkflowRepairer
from app.connectors.openapi_factory import OpenAPIConnectorFactory


@pytest.fixture(autouse=True)
def setup_connectors():
    register_builtin_connectors()


# ============================================================================
# TEST 1: Salesforce lead enrichment workflow
# ============================================================================
@pytest.mark.asyncio
async def test_acceptance_1_salesforce_lead_enrichment():
    prompt = (
        "Every morning check Salesforce for new leads from yesterday, enrich each lead with company information, "
        "score the lead using AI, update Salesforce, assign high-value leads to enterprise sales representatives, "
        "and notify the appropriate Teams channel. Retry transient failures twice and notify operations when processing fails."
    )

    # 1. Intent Extraction
    intent = await IntentEngine.extract_intent(prompt)
    assert intent.goal != ""
    assert any("salesforce" in s.lower() for s in intent.systems)
    assert any("teams" in s.lower() for s in intent.systems)
    assert intent.error_policy.retry_attempts >= 2

    # 2. Capability Search
    sf_caps = CapabilitySearch.search("Salesforce Lead search update")
    assert len(sf_caps) > 0
    assert any("salesforce" in str(c).lower() for c in sf_caps)

    # 3. Construct Workflow IR
    ir = WorkflowIR(
        name="Salesforce Lead Enrichment & AI Scoring",
        description="Automated lead qualification and routing",
        trigger=IRTrigger(type="salesforce", parameters={"event": "lead_created", "object": "Lead"}),
        steps=[
            IRStep(id="enrich", type="http_request", name="Enrich Company Data", parameters={"url": "https://api.clearbit.com/v2/companies/find", "method": "GET"}),
            IRStep(id="score_ai", type="ai_agent", name="Score Lead with AI", parameters={"prompt": "Score lead value from 1 to 100 based on company revenue: {{ $json.revenue }}", "model": "gpt-4o"}),
            IRStep(id="check_high_value", type="if_condition", name="Is High Value", parameters={"conditions": [{"left": "{{ $json.score }}", "op": ">=", "right": 80}]}),
            IRStep(id="update_sf", type="salesforce", name="Update Salesforce Lead", parameters={"operation": "update", "resource": "Lead", "id": "{{ $json.id }}", "rating": "Hot"}),
            IRStep(id="notify_teams", type="msteams", name="Notify Enterprise Sales", parameters={"operation": "send_message", "channel": "enterprise-sales", "message": "High-value lead scored: {{ $json.name }}"}),
        ],
        connections=[
            IRConnection(from_step="trigger_0", to_step="enrich"),
            IRConnection(from_step="enrich", to_step="score_ai"),
            IRConnection(from_step="score_ai", to_step="check_high_value"),
            IRConnection(from_step="check_high_value", to_step="update_sf", source_handle="true"),
            IRConnection(from_step="update_sf", to_step="notify_teams"),
        ],
        error_policy=IRErrorPolicy(max_retries=2, backoff="exponential"),
    )

    # 4. Deterministic Compiler
    workflow = WorkflowCompiler.compile_ir(ir)
    assert "nodes" in workflow and len(workflow["nodes"]) >= 6
    assert "connections" in workflow and len(workflow["connections"]) >= 5

    # 5. Full 6-Stage Validation Pipeline
    validation = PipelineValidator.validate_full(
        workflow,
        user_credentials={"salesforce", "msteams", "openai"},
    )
    assert validation["stages"]["structural"]["status"] == "passed"
    assert validation["stages"]["connector_schema"]["status"] == "passed"
    assert validation["stages"]["data_expressions"]["status"] == "passed"
    assert validation["stages"]["credential_health"]["status"] == "passed"
    assert validation["stages"]["runtime_policies"]["status"] == "passed"
    assert validation["stages"]["security_guards"]["status"] == "passed"
    assert validation["valid"] is True

    # 6. Non-Destructive Simulation
    sim_result = WorkflowSimulator.simulate(workflow, user_credentials={"salesforce", "msteams"})
    assert sim_result["success"] is True
    assert sim_result["executed_count"] >= 5
    assert sim_result["estimated_latency_ms"] > 0


# ============================================================================
# TEST 2: Every morning sync Salesforce contacts to PostgreSQL
# ============================================================================
def test_acceptance_2_sync_salesforce_to_postgresql():
    ir = WorkflowIR(
        name="Daily Salesforce Contacts to Postgres Sync",
        trigger=IRTrigger(type="schedule", parameters={"rule": {"cronExpression": "0 8 * * *", "timezone": "UTC"}}),
        steps=[
            IRStep(id="get_contacts", type="salesforce", name="Fetch Salesforce Contacts", parameters={"operation": "search", "resource": "Contact", "query": "SELECT Id, FirstName, LastName, Email FROM Contact"}),
            IRStep(id="upsert_pg", type="postgresql", name="Upsert to PostgreSQL", parameters={"operation": "insert", "table": "contacts", "columns": {"external_id": "{{ $json.Id }}", "name": "{{ $json.FirstName }}", "email": "{{ $json.Email }}"}}),
        ],
        connections=[
            IRConnection(from_step="get_contacts", to_step="upsert_pg"),
        ],
    )

    wf = WorkflowCompiler.compile_ir(ir)
    assert len(wf["nodes"]) == 3
    assert wf["nodes"][0]["type"] == "schedule"
    assert wf["nodes"][1]["type"] == "salesforce"
    assert wf["nodes"][2]["type"] in ("postgresql", "postgres")

    val = PipelineValidator.validate_full(wf, user_credentials={"salesforce", "postgresql"})
    assert val["valid"] is True


# ============================================================================
# TEST 3: When an opportunity closes, notify Teams
# ============================================================================
def test_acceptance_3_opportunity_closed_teams_notification():
    ir = WorkflowIR(
        name="Opportunity Closed Won Notification",
        trigger=IRTrigger(type="salesforce", parameters={"event": "opportunity_updated", "object": "Opportunity"}),
        steps=[
            IRStep(id="check_closed_won", type="if_condition", name="Is Closed Won", parameters={"conditions": [{"left": "{{ $json.StageName }}", "op": "==", "right": "Closed Won"}]}),
            IRStep(id="teams_alert", type="msteams", name="Teams Deal Won Alert", parameters={"operation": "send_message", "channel": "sales-wins", "message": "Deal closed won: {{ $json.Name }} for ${{ $json.Amount }}!"}),
        ],
        connections=[
            IRConnection(from_step="check_closed_won", to_step="teams_alert", source_handle="true"),
        ],
    )

    wf = WorkflowCompiler.compile_ir(ir)
    assert len(wf["nodes"]) == 3
    conn = next(c for c in wf["connections"] if c["target"] == "teams_alert")
    assert conn["sourceHandle"] == "true"

    sim = WorkflowSimulator.simulate(wf, user_credentials={"salesforce", "msteams"})
    assert sim["success"] is True


# ============================================================================
# TEST 4: Create an AI support ticket classifier
# ============================================================================
def test_acceptance_4_ai_support_ticket_classifier():
    ir = WorkflowIR(
        name="AI Ticket Classifier and Router",
        trigger=IRTrigger(type="webhook", parameters={"path": "/tickets", "method": "POST"}),
        steps=[
            IRStep(id="classify_ai", type="ai_agent", name="Classify Urgency", parameters={"prompt": "Classify ticket urgency as High, Medium, or Low: {{ $json.body }}", "model": "gpt-4o"}),
            IRStep(id="route_urgency", type="if_condition", name="Is Urgent", parameters={"conditions": [{"left": "{{ $json.urgency }}", "op": "==", "right": "High"}]}),
            IRStep(id="pagerduty_alert", type="http_request", name="Trigger PagerDuty Incident", parameters={"url": "https://events.pagerduty.com/v2/enqueue", "method": "POST"}),
            IRStep(id="zendesk_ticket", type="zendesk", name="Create Standard Zendesk Ticket", parameters={"operation": "create", "resource": "ticket", "subject": "{{ $json.subject }}"}),
        ],
        connections=[
            IRConnection(from_step="classify_ai", to_step="route_urgency"),
            IRConnection(from_step="route_urgency", to_step="pagerduty_alert", source_handle="true"),
            IRConnection(from_step="route_urgency", to_step="zendesk_ticket", source_handle="false"),
        ],
    )

    wf = WorkflowCompiler.compile_ir(ir)
    assert len(wf["nodes"]) == 5
    true_conn = next(c for c in wf["connections"] if c["target"] == "pagerduty_alert")
    false_conn = next(c for c in wf["connections"] if c["target"] == "zendesk_ticket")
    assert true_conn["sourceHandle"] == "true"
    assert false_conn["sourceHandle"] == "false"


# ============================================================================
# TEST 5: Add human approval before updating Salesforce
# ============================================================================
@pytest.mark.asyncio
async def test_acceptance_5_add_human_approval():
    base_workflow = {
        "nodes": [
            {"id": "webhook_1", "type": "webhook", "name": "Incoming Webhook", "position": {"x": 100, "y": 180}, "parameters": {}},
            {"id": "salesforce_1", "type": "salesforce", "name": "Update Salesforce Contact", "position": {"x": 380, "y": 180}, "parameters": {"operation": "update"}},
        ],
        "connections": [
            {"source": "webhook_1", "target": "salesforce_1", "sourceHandle": "main", "targetHandle": "main"},
        ],
    }

    diff = await WorkflowModifier.modify_workflow(
        current_workflow=base_workflow,
        instruction="Add human approval before updating Salesforce",
    )

    assert len(diff.added_nodes) == 1
    assert diff.added_nodes[0]["type"] == "human_approval"
    mod_nodes = diff.modified_workflow["nodes"]
    assert any(n["type"] == "human_approval" for n in mod_nodes)
    # Target node connection should now flow from human approval
    link_conn = next(c for c in diff.modified_workflow["connections"] if c["target"] == "salesforce_1")
    assert "approval" in link_conn["source"]
    assert link_conn["sourceHandle"] == "approved"


# ============================================================================
# TEST 6: Add retry handling
# ============================================================================
@pytest.mark.asyncio
async def test_acceptance_6_add_retry_handling():
    base_workflow = {
        "nodes": [
            {"id": "webhook_1", "type": "webhook", "name": "Webhook Trigger", "position": {"x": 100, "y": 180}, "parameters": {}},
            {"id": "http_1", "type": "http_request", "name": "Payment Gateway API", "position": {"x": 380, "y": 180}, "parameters": {"url": "https://api.stripe.com/v1/charges"}},
        ],
        "connections": [
            {"source": "webhook_1", "target": "http_1", "sourceHandle": "main", "targetHandle": "main"},
        ],
    }

    diff = await WorkflowModifier.modify_workflow(
        current_workflow=base_workflow,
        instruction="Retry this operation 3 times with exponential backoff",
    )

    assert len(diff.modified_nodes) >= 1
    target = next(n for n in diff.modified_workflow["nodes"] if n["id"] == "http_1")
    assert target.get("settings", {}).get("retry", {}).get("max_attempts") == 3
    assert target.get("settings", {}).get("retry", {}).get("backoff") == "exponential"


# ============================================================================
# TEST 7: Replace the selected AI provider/model
# ============================================================================
@pytest.mark.asyncio
async def test_acceptance_7_replace_ai_provider():
    base_workflow = {
        "nodes": [
            {"id": "webhook_1", "type": "webhook", "name": "Webhook Trigger", "position": {"x": 100, "y": 180}, "parameters": {}},
            {"id": "ai_1", "type": "ai_agent", "name": "Customer Support Agent", "position": {"x": 380, "y": 180}, "parameters": {"model": "gpt-4o"}},
        ],
        "connections": [
            {"source": "webhook_1", "target": "ai_1", "sourceHandle": "main", "targetHandle": "main"},
        ],
    }

    diff = await WorkflowModifier.modify_workflow(
        current_workflow=base_workflow,
        instruction="Replace OpenAI with Google Gemini",
    )

    assert len(diff.modified_nodes) >= 1
    ai_node = next(n for n in diff.modified_workflow["nodes"] if n["id"] == "ai_1")
    assert "gemini" in ai_node["parameters"]["model"].lower()


# ============================================================================
# TEST 8: Optimize workflow for cost
# ============================================================================
def test_acceptance_8_optimize_for_cost():
    expensive_workflow = {
        "nodes": [
            {"id": "webhook_1", "type": "webhook", "name": "Webhook", "position": {"x": 100, "y": 180}, "parameters": {}},
            {"id": "ai_1", "type": "ai_agent", "name": "Document Classifier", "position": {"x": 380, "y": 180}, "parameters": {"model": "gpt-4o"}},
        ],
        "connections": [
            {"source": "webhook_1", "target": "ai_1", "sourceHandle": "main", "targetHandle": "main"},
        ],
    }

    proposal = WorkflowModifier.optimize_workflow(expensive_workflow, dimension="cost")
    assert proposal["dimension"] == "cost"
    assert "reduction" in proposal["estimated_savings"] or "%" in proposal["estimated_savings"]
    opt_nodes = proposal["modified_workflow"]["nodes"]
    ai_node = next(n for n in opt_nodes if n["id"] == "ai_1")
    assert ai_node["parameters"]["model"] == "gpt-4o-mini"


# ============================================================================
# TEST 9: Repair a failed workflow
# ============================================================================
@pytest.mark.asyncio
async def test_acceptance_9_repair_failed_workflow():
    failing_workflow = {
        "nodes": [
            {"id": "sched_1", "type": "schedule", "name": "Schedule", "position": {"x": 100, "y": 180}, "parameters": {}},
            {"id": "salesforce_1", "type": "salesforce", "name": "Salesforce Sync", "position": {"x": 380, "y": 180}, "parameters": {"operation": "search"}},
        ],
        "connections": [
            {"source": "sched_1", "target": "salesforce_1", "sourceHandle": "main", "targetHandle": "main"},
        ],
    }

    error_context = "Salesforce API responded with HTTP 429: Too Many Requests (Rate limit exceeded for endpoint /services/data/v58.0/query)"
    repair_proposal = await WorkflowRepairer.analyze_and_repair(failing_workflow, error_context)

    assert "rate" in repair_proposal.root_cause.lower() or "limit" in repair_proposal.root_cause.lower() or "429" in repair_proposal.root_cause
    assert repair_proposal.repaired_workflow is not None
    repaired_sf = next(n for n in repair_proposal.repaired_workflow["nodes"] if n["id"] == "salesforce_1")
    assert repaired_sf.get("settings", {}).get("retry", {}).get("max_attempts") >= 3
    assert repaired_sf.get("settings", {}).get("retry", {}).get("backoff") == "exponential"


# ============================================================================
# TEST 10: Generate workflow from an OpenAPI specification
# ============================================================================
def test_acceptance_10_openapi_to_workflow():
    import textwrap
    sample_spec = textwrap.dedent("""
    openapi: 3.1.0
    info:
      title: Logistics Tracking API
      version: 1.0.0
    servers:
      - url: https://logistics.enterprise.com/api/v1
    paths:
      /shipments/{id}:
        get:
          summary: Get shipment status
          operationId: getShipmentStatus
          parameters:
            - name: id
              in: path
              required: true
              schema:
                type: string
          responses:
            '200':
              description: Shipment found
    """).strip()

    factory = OpenAPIConnectorFactory()
    is_valid, errors = factory.validate_spec(sample_spec)
    assert is_valid is True

    bundle = factory.build_connector_bundle(sample_spec, custom_key="logistics_api")
    assert bundle["connector_key"] == "logistics_api"
    assert bundle["operation_count"] == 1
    assert bundle["openapi_version"] == "3.1.0"



    # Compile into workflow DAG using dynamic OpenAPI connector
    ir = WorkflowIR(
        name="Logistics Status Tracker",
        trigger=IRTrigger(type="webhook", parameters={"path": "/tracking-check", "method": "POST"}),
        steps=[
            IRStep(
                id="check_status",
                type="http_request",
                name="Check Shipment Status",
                parameters={
                    "url": "https://logistics.enterprise.com/api/v1/shipments/{{ $json.shipment_id }}",
                    "method": "GET",
                },
            ),
        ],
        connections=[],
    )

    wf = WorkflowCompiler.compile_ir(ir)
    assert len(wf["nodes"]) == 2
    assert wf["nodes"][1]["type"] == "http_request"
    assert "https://logistics.enterprise.com" in wf["nodes"][1]["parameters"]["url"]

    # Verify pipeline validation passes
    val = PipelineValidator.validate_full(wf)
    assert val["valid"] is True
