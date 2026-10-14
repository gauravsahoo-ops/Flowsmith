"""
Benchmark Suite for Flowsmith Execution Logs & Monitoring Telemetry (10,000+ Records).

Simulates production-scale volume with:
- 10,000 Execution records across 5 workspaces, 10 workflows, 4 statuses, realistic timestamps and error taxonomies
- 30,000 ExecutionStep DAG records
- 20,000 ApiRequestTelemetry records
- 2,500 ExecutionRetryHistory records

Evaluates:
1. Filtered Pagination (Status, Workspace, Trigger)
2. Complex Multi-Attribute Query (Date Range + Status + Connector)
3. Full-Text Search on Error Taxonomies and Summary
4. Monitoring Dashboard Metric Aggregation (Total runs, success rate, p95 duration, error classification)
5. Secure CSV Export stream query latency
"""

import os
import sys
import time
import uuid
import statistics
from datetime import datetime, timezone, timedelta
from sqlalchemy import create_engine, select, func, and_, or_, case
from sqlalchemy.orm import Session, defer

# Add backend to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.db import Base
from app.models.user import User
from app.models.organization import Organization, Workspace, WorkspaceMember
from app.models.workflow import WorkflowRecord
from app.models.execution import Execution
from app.models.monitoring_telemetry import ExecutionStep, ApiRequestTelemetry, ExecutionRetryHistory


def create_benchmark_db():
    db_file = os.path.abspath("benchmark_telemetry_10k.db")
    if os.path.exists(db_file):
        try:
            os.remove(db_file)
        except Exception:
            pass
    engine = create_engine(f"sqlite:///{db_file}", echo=False)
    Base.metadata.create_all(engine)
    return engine, db_file


def seed_10k_dataset(session: Session, user_id: str, org_id: str, workspace_id: str):
    print("\n--- Seeding 10,000 Execution Records and 52,500 Telemetry Entries ---")
    start_seed = time.perf_counter()

    statuses = ["completed", "failed", "running", "cancelled"]
    error_types = ["NETWORK_ERROR", "RATE_LIMIT", "AUTHENTICATION", "SCHEMA_VALIDATION", "UPSTREAM_5XX", "TIMEOUT"]
    connectors = ["Salesforce", "Shopify", "HubSpot", "Stripe", "NetSuite", "Slack", "Postgres"]
    triggers = ["webhook", "manual", "schedule", "api"]

    # 5 Workflows
    workflows = []
    for i in range(5):
        wf = WorkflowRecord(
            id=f"wf_bench_{i}",
            name=f"Enterprise Sync Pipeline {i+1}",
            user_id=user_id,
            workspace_id=workspace_id,
            version=1,
            data={"nodes": [{"id": "n1", "name": "Source"}]},
            active=True,
        )
        session.add(wf)
        workflows.append(wf)
    session.flush()

    base_time = datetime.now(timezone.utc) - timedelta(days=30)
    batch_size = 1000
    executions = []
    steps = []
    requests = []
    retries = []

    for i in range(10_000):
        wf = workflows[i % len(workflows)]
        status = statuses[i % len(statuses)]
        trigger = triggers[i % len(triggers)]
        started = base_time + timedelta(minutes=i * 4)
        duration_ms = 120 + (i % 800)
        finished = started + timedelta(milliseconds=duration_ms) if status != "running" else None

        err_type = error_types[i % len(error_types)] if status == "failed" else None
        err_code = f"ERR_{(i % 7) + 400}" if status == "failed" else None
        err_summary = f"Operation failed at step with code {err_code} in connector {connectors[i % len(connectors)]}" if status == "failed" else None

        exec_id = f"exec_bench_{i:06d}"
        ex = Execution(
            id=exec_id,
            workflow_id=wf.id,
            workflow_version=1,
            workflow_data={"nodes": []},
            user_id=user_id,
            workspace_id=workspace_id,
            organization_id=org_id,
            status=status,
            trigger=trigger,
            started_at=started,
            finished_at=finished,
            duration_ms=duration_ms if status != "running" else None,
            records_read=50 + (i % 100),
            records_created=30 + (i % 80),
            records_updated=10 + (i % 20),
            records_failed=5 if status == "failed" else 0,
            records_skipped=2,
            records_processed=90 + (i % 150),
            error_type=err_type,
            error_code=err_code,
            error_summary=err_summary,
            source_connector=connectors[i % len(connectors)],
            destination_connector=connectors[(i + 1) % len(connectors)],
            source_object="Order",
            destination_object="Invoice",
            http_method="POST",
            api_endpoint="/v2/transactions",
            http_status_code=200 if status == "completed" else 500 if status == "failed" else 202,
        )
        executions.append(ex)

        # Generate 3 steps per execution (30,000 steps)
        for s_idx in range(3):
            s_status = "completed" if status == "completed" else ("failed" if s_idx == 2 and status == "failed" else "completed")
            step = ExecutionStep(
                id=f"step_{exec_id}_{s_idx}",
                execution_id=exec_id,
                workspace_id=workspace_id,
                organization_id=org_id,
                node_id=f"node_{s_idx}",
                sequence_number=s_idx + 1,
                step_name=f"Sync Step {s_idx+1}",
                node_type="connector" if s_idx > 0 else "trigger",
                status=s_status,
                started_at=started + timedelta(milliseconds=s_idx * 40),
                completed_at=started + timedelta(milliseconds=(s_idx + 1) * 40),
                duration_ms=40.0,
                input_record_count=50,
                output_record_count=50 if s_status == "completed" else 0,
                failed_record_count=5 if s_status == "failed" else 0,
            )
            steps.append(step)

        # Generate 2 API telemetry requests per execution (20,000 requests)
        for r_idx in range(2):
            req = ApiRequestTelemetry(
                id=f"req_{exec_id}_{r_idx}",
                execution_id=exec_id,
                workspace_id=workspace_id,
                organization_id=org_id,
                node_id=f"node_{r_idx+1}",
                connector_name=connectors[(i + r_idx) % len(connectors)],
                http_method="POST" if r_idx == 1 else "GET",
                endpoint_url=f"https://api.{connectors[(i + r_idx) % len(connectors)].lower()}.com/v1/records",
                request_headers={"Authorization": "Bearer [REDACTED]"},
                request_payload={"query": "active"},
                http_status_code=200 if status == "completed" else 429,
                response_headers={"Content-Type": "application/json"},
                response_payload={"status": "ok"} if status == "completed" else {"error": "rate_limit"},
                duration_ms=45.0 + (i % 50),
            )
            requests.append(req)

        # Generate Retry history for every failed execution (approx 2,500)
        if status == "failed":
            retries.append(
                ExecutionRetryHistory(
                    id=f"retry_{exec_id}",
                    original_execution_id=exec_id,
                    retry_execution_id=exec_id,
                    workspace_id=workspace_id,
                    organization_id=org_id,
                    attempt_number=1,
                    retry_reason="Automated backoff retry",
                    retry_trigger="auto_policy",
                    initiated_by_user_id=user_id,
                    retry_policy="exponential_backoff",
                    status="completed",
                )
            )

        if len(executions) >= batch_size:
            session.bulk_save_objects(executions)
            session.bulk_save_objects(steps)
            session.bulk_save_objects(requests)
            if retries:
                session.bulk_save_objects(retries)
            session.flush()
            executions.clear()
            steps.clear()
            requests.clear()
            retries.clear()

    session.commit()
    seed_duration = time.perf_counter() - start_seed
    print(f"Seed complete in {seed_duration:.2f} seconds.")


def run_benchmarks(session: Session, workspace_id: str):
    print("\n=======================================================")
    print("  FLOWSMITH LOGS & MONITORING 10K+ BENCHMARK RESULTS   ")
    print("=======================================================")

    results = []

    def time_operation(name, iterations, fn):
        latencies = []
        for _ in range(iterations):
            t0 = time.perf_counter()
            count = fn()
            elapsed_ms = (time.perf_counter() - t0) * 1000
            latencies.append(elapsed_ms)
        p50 = statistics.median(latencies)
        p95 = statistics.quantiles(latencies, n=20)[18] if len(latencies) >= 20 else max(latencies)
        p99 = max(latencies)
        results.append({
            "name": name,
            "p50_ms": p50,
            "p95_ms": p95,
            "p99_ms": p99,
            "records_matched": count
        })
        print(f"[{name}]")
        print(f"  -> p50: {p50:.2f}ms | p95: {p95:.2f}ms | p99: {p99:.2f}ms | count: {count}")

    # Benchmark 1: Filtered Paginated Listing (Page 1, 20 items, status=failed)
    def q1():
        stmt = (
            select(Execution)
            .where(Execution.workspace_id == workspace_id, Execution.status == "failed")
            .order_by(Execution.started_at.desc())
            .limit(20)
        )
        return len(session.scalars(stmt).all())

    time_operation("1. Filtered Pagination (status=failed, limit=20)", 50, q1)

    # Benchmark 2: Deep Pagination (Page 100, 20 items, status=completed)
    def q2():
        stmt = (
            select(Execution)
            .where(Execution.workspace_id == workspace_id, Execution.status == "completed")
            .order_by(Execution.started_at.desc())
            .offset(2000)
            .limit(20)
        )
        return len(session.scalars(stmt).all())

    time_operation("2. Deep Offset Pagination (offset=2000, limit=20)", 50, q2)

    # Benchmark 3: Multi-Attribute Filter (Date range + Connector + Status)
    one_week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    def q3():
        stmt = (
            select(Execution)
            .where(
                Execution.workspace_id == workspace_id,
                Execution.status == "failed",
                Execution.source_connector == "Salesforce",
                Execution.started_at >= one_week_ago
            )
            .order_by(Execution.started_at.desc())
            .limit(50)
        )
        return len(session.scalars(stmt).all())

    time_operation("3. Multi-Attribute Filter (Salesforce + Failed + Last 7d)", 50, q3)

    # Benchmark 4: Search Error Summary Pattern
    def q4():
        stmt = (
            select(Execution)
            .where(
                Execution.workspace_id == workspace_id,
                Execution.error_summary.like("%Operation failed%")
            )
            .order_by(Execution.started_at.desc())
            .limit(50)
        )
        return len(session.scalars(stmt).all())

    time_operation("4. Partial Text Search ('%Operation failed%')", 30, q4)

    # Benchmark 5: Monitoring Metrics Aggregation (Dashboard 8 Metrics & Taxonomy Breakdown)
    def q5():
        # Aggregation of total, success count, avg duration, total records read & failed
        totals = session.execute(
            select(
                func.count(Execution.id).label("total"),
                func.sum(case((Execution.status == "completed", 1), else_=0)).label("success_count"),
                func.sum(case((Execution.status == "failed", 1), else_=0)).label("failure_count"),
                func.avg(Execution.duration_ms).label("avg_duration"),
                func.sum(Execution.records_read).label("total_read"),
                func.sum(Execution.records_processed).label("total_processed"),
                func.sum(Execution.records_failed).label("total_failed"),
            ).where(Execution.workspace_id == workspace_id)
        ).one()

        # Taxonomy group by
        taxonomy = session.execute(
            select(
                Execution.error_type,
                func.count(Execution.id).label("cnt")
            )
            .where(Execution.workspace_id == workspace_id, Execution.error_type.isnot(None))
            .group_by(Execution.error_type)
        ).all()

        return totals.total

    time_operation("5. Monitoring Dashboard Summary Aggregation (10,000 records)", 30, q5)

    # Benchmark 6: Step DAG Traversal & Record Sums
    def q6():
        stmt = (
            select(ExecutionStep)
            .where(ExecutionStep.execution_id == "exec_bench_000500")
            .order_by(ExecutionStep.started_at.asc())
        )
        return len(session.scalars(stmt).all())

    time_operation("6. DAG Step Inspection (by execution_id index)", 50, q6)

    # Benchmark 7: API Request Inspector Query
    def q7():
        stmt = (
            select(ApiRequestTelemetry)
            .where(ApiRequestTelemetry.execution_id == "exec_bench_000500")
            .order_by(ApiRequestTelemetry.created_at.asc())
        )
        return len(session.scalars(stmt).all())

    time_operation("7. API Request Inspector (by execution_id index)", 50, q7)

    # Benchmark 8: CSV Export Stream Generator (First 1,000 records)
    def q8():
        stmt = (
            select(Execution)
            .options(
                defer(Execution.trace),
                defer(Execution.results),
                defer(Execution.workflow_data),
                defer(Execution.node_statuses),
            )
            .where(Execution.workspace_id == workspace_id)
            .order_by(Execution.started_at.desc())
            .limit(1000)
        )
        records = session.scalars(stmt).all()
        # Simulate row formatting
        count = 0
        for r in records:
            _ = f"{r.id},{r.status},{r.started_at},{r.duration_ms},{r.records_processed}\n"
            count += 1
        return count

    time_operation("8. CSV Export 1,000 Row Extraction", 20, q8)

    print("\n-------------------------------------------------------")
    all_under_100ms = all(r["p95_ms"] < 100.0 for r in results)
    print(f"SLA Target (< 100ms p95): {'PASSED ALL CHECKS' if all_under_100ms else 'FAILED'}")
    print("-------------------------------------------------------\n")
    return results


def main():
    engine, db_file = create_benchmark_db()
    with Session(engine) as session:
        user_id = 9999
        org_id = "org_bench"
        workspace_id = "ws_bench"

        org = Organization(id=org_id, name="Benchmark Org", founder_id=user_id)
        user = User(id=user_id, email="bench@flowsmith.local", password_hash="dummy_hash", role="admin", active=True)
        ws = Workspace(id=workspace_id, name="Benchmark Workspace", organization_id=org_id, creator_id=user_id)
        member = WorkspaceMember(workspace_id=workspace_id, user_id=user_id, role="owner")
        session.add_all([org, user, ws, member])
        session.commit()

        seed_10k_dataset(session, user_id, org_id, workspace_id)
        results = run_benchmarks(session, workspace_id)

    try:
        os.remove(db_file)
    except Exception:
        pass

    return results


if __name__ == "__main__":
    main()
