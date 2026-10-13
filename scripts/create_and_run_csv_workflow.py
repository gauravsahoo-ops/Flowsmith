import uuid
import json
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
from datetime import datetime, timezone

from app.db import get_session
from app.models import WorkflowRecord, User, Execution
from app.schemas.workflow import Workflow
from app.engine.executor import execute_workflow
from app.api.executions import start_execution

def setup_and_run_workflow():
    user_id = 1341
    wf_id = "wf_csv_salesforce_10k_ingest"

    wf_data = {
        "id": wf_id,
        "name": "CSV Connector - 10k Salesforce Contact Ingestion",
        "status": "active",
        "version": 1,
        "settings": {},
        "nodes": [
            {
                "id": "manual_trigger_1",
                "name": "Start Ingest",
                "type": "manual_trigger",
                "version": 1,
                "position": {"x": 200, "y": 250},
                "parameters": {}
            },
            {
                "id": "csv_parser_1",
                "name": "CSV Parser & Schema Validator",
                "type": "csv_parser",
                "version": 1,
                "position": {"x": 550, "y": 250},
                "parameters": {
                    "file_path": "flowsmith_salesforce_contact_10000.csv",
                    "delimiter": ",",
                    "has_header": True,
                    "batch_size": 1000,
                    "target_object": "Contact",
                    "duplicate_policy": "skip",
                    "dedup_key": "Email",
                    "persist_to_db": True,
                    "field_mapping": {
                        "FirstName": "FirstName",
                        "LastName": "LastName",
                        "Email": "Email",
                        "Phone": "Phone",
                        "Department": "Department",
                        "Title": "Title",
                        "MailingStreet": "MailingStreet",
                        "MailingCity": "MailingCity",
                        "MailingState": "MailingState",
                        "MailingPostalCode": "MailingPostalCode",
                        "MailingCountry": "MailingCountry",
                        "Description": "Description"
                    }
                }
            },
            {
                "id": "code_summary_1",
                "name": "Ingest Audit & Metrics",
                "type": "code",
                "version": 1,
                "position": {"x": 900, "y": 250},
                "parameters": {
                    "language": "javascript",
                    "code": """const items = $input.all();
const raw = items[0] ? (items[0].json || items[0]) : {};
const summary = raw.summary || {};
return [{
    status: "SUCCESS",
    total_csv_records: summary.total_parsed || 0,
    valid_unique_contacts: summary.unique_count || 0,
    duplicates_filtered: summary.duplicate_count || 0,
    invalid_records: summary.invalid_count || 0,
    persisted_to_staged_db: summary.persisted_count || 0,
    target_object: summary.target_object || "Contact",
    dedup_policy: summary.duplicate_policy || "skip",
    execution_correlation_id: summary.execution_id || "",
    summary_message: "Successfully ingested " + (summary.total_parsed || 0) + " Contact rows. " + (summary.persisted_count || 0) + " contacts staged in PostgreSQL staged_contacts, " + (summary.duplicate_count || 0) + " duplicates isolated."
}];"""
                }
            }
        ],
        "connections": [
            {
                "source": "manual_trigger_1",
                "target": "csv_parser_1",
                "sourceHandle": "main",
                "targetHandle": "main"
            },
            {
                "source": "csv_parser_1",
                "target": "code_summary_1",
                "sourceHandle": "main",
                "targetHandle": "main"
            }
        ]
    }

    with get_session() as db:
        wf_rec = db.get(WorkflowRecord, wf_id)
        if not wf_rec:
            wf_rec = WorkflowRecord(
                id=wf_id,
                user_id=user_id,
                name=wf_data["name"],
                active=True,
                version=1,
                data=wf_data
            )
            db.add(wf_rec)
        else:
            wf_rec.name = wf_data["name"]
            wf_rec.data = wf_data
            wf_rec.active = True
        db.commit()
        print(f"Workflow saved: ID={wf_rec.id}, Name={wf_rec.name}")

        # Now execute the workflow to generate a real run & logs
        parsed_wf = Workflow(**wf_data)
        execution_id = f"exec_{uuid.uuid4().hex[:12]}"

        # Create execution record
        exec_row = Execution(
            id=execution_id,
            workflow_id=wf_id,
            user_id=user_id,
            workflow_version=1,
            workflow_data=wf_data,
            trigger="manual",
            trigger_data=[{}],
            status="running",
            started_at=datetime.now(timezone.utc)
        )
        db.add(exec_row)
        db.commit()
        print(f"Execution started: ID={execution_id}")

    # Run execution directly using engine
    result = asyncio.run(execute_workflow(parsed_wf, trigger_items=[{}], execution_id=execution_id))

    with get_session() as db:
        exec_row = db.get(Execution, execution_id)
        if exec_row:
            exec_row.status = result.status
            exec_row.finished_at = datetime.now(timezone.utc)
            exec_row.results = result.results
            exec_row.trace = result.trace
            if result.error:
                exec_row.error = {"message": str(result.error)}
            db.commit()
            print(f"Execution finished: Status={exec_row.status}")
            print(f"Trace events recorded: {len(exec_row.trace or [])}")
            for item in (exec_row.trace or []):
                print(f" - Node {item.get('node_id')} ({item.get('node_type')}): status={item.get('status')}")

    print("\n--- WORKFLOW READY ---")
    print(f"Workflow URL: http://localhost:5173/workflows/{wf_id}")
    print(f"Execution URL: http://localhost:5173/executions/{execution_id}")
    print(f"Execution ID: {execution_id}")

if __name__ == "__main__":
    setup_and_run_workflow()
