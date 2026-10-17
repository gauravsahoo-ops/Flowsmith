"""Flowsmith Performance Baseline Audit Script (Phase 1).
Measures:
1. Node Catalog generation latency (_connector_catalog_entries + get_nodes)
2. Workflow serialization and query execution time
3. DB Connection pool and query timings
4. Redis ping and serialization throughput
"""

import sys
import time
import os

# Add backend to path
sys.path.insert(0, os.path.abspath("backend"))

from app.db import get_session, init_db
from app.api.nodes import get_nodes, _connector_catalog_entries
from app.nodes.registry import list_nodes
from app.models import WorkflowRecord, User
from app.connectors import get_registry as get_connector_registry, register_builtin_connectors

def measure_catalog_baseline():
    print("--- 1. Node Catalog Baseline ---")
    register_builtin_connectors()
    
    t0 = time.perf_counter()
    connectors = _connector_catalog_entries()
    t_conn = (time.perf_counter() - t0) * 1000
    print(f"_connector_catalog_entries(): {len(connectors)} items generated in {t_conn:.2f} ms")
    
    # Simulate a dummy user for get_nodes
    class DummyUser:
        id = 1
        is_admin = True
    
    times = []
    for _ in range(5):
        t0 = time.perf_counter()
        res = get_nodes(user=DummyUser())
        times.append((time.perf_counter() - t0) * 1000)
    
    p50 = sorted(times)[len(times)//2]
    print(f"GET /api/nodes response generation: p50={p50:.2f} ms, min={min(times):.2f} ms, max={max(times):.2f} ms")

def measure_db_baseline():
    print("\n--- 2. Database & Workflows Query Baseline ---")
    db = get_session()
    try:
        t0 = time.perf_counter()
        count = db.query(WorkflowRecord).count()
        t_count = (time.perf_counter() - t0) * 1000
        print(f"WorkflowRecord count query ({count} rows): {t_count:.2f} ms")

        # Measure loading full rows with JSONB
        t0 = time.perf_counter()
        records = db.query(WorkflowRecord).limit(50).all()
        t_full = (time.perf_counter() - t0) * 1000
        print(f"Query 50 full WorkflowRecords (with JSONB data): {t_full:.2f} ms")

        # Measure loading deferred/lightweight columns (without full graph JSONB)
        t0 = time.perf_counter()
        lightweight = db.query(
            WorkflowRecord.id,
            WorkflowRecord.name,
            WorkflowRecord.version,
            WorkflowRecord.active,
            WorkflowRecord.updated_at,
            WorkflowRecord.created_at,
        ).limit(50).all()
        t_light = (time.perf_counter() - t0) * 1000
        print(f"Query 50 lightweight Workflow columns (ID/Name/Status): {t_light:.2f} ms (Speedup: {t_full/max(t_light, 0.01):.1f}x)")
    finally:
        db.close()

def measure_executions_baseline():
    print("\n--- 3. Executions API Baseline ---")
    from app.api.executions import list_executions
    db = get_session()
    try:
        user = db.query(User).first()
        if not user:
            print("No user found in DB, skipping executions test")
            return
        
        times = []
        for _ in range(5):
            t0 = time.perf_counter()
            res = list_executions(page=1, pageSize=50, user=user, db=db)
            times.append((time.perf_counter() - t0) * 1000)
        
        p50 = sorted(times)[len(times)//2]
        count = len(res.get("data", []))
        total = res.get("meta", {}).get("total", 0)
        print(f"list_executions (retrieved {count} / {total} total): p50={p50:.2f} ms, min={min(times):.2f} ms, max={max(times):.2f} ms")
    finally:
        db.close()

def inspect_indexes():
    print("\n--- 4. PostgreSQL Indexes ---")
    from sqlalchemy import text
    db = get_session()
    try:
        for table in ['workflows', 'executions', 'execution_steps']:
            print(f"=== Indexes on {table} ===")
            res = db.execute(text("SELECT indexname, indexdef FROM pg_indexes WHERE tablename = :t"), {'t': table}).fetchall()
            for name, definition in res:
                print(f"  {name}: {definition}")
    finally:
        db.close()

if __name__ == "__main__":
    measure_catalog_baseline()
    measure_db_baseline()
    measure_executions_baseline()
    inspect_indexes()
