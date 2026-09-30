import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.connectors import get_registry, register_builtin_connectors
from app.nodes.registry import list_nodes
from app.api.nodes import _connector_catalog_entries
from app.credentials.registry import list_types

register_builtin_connectors()

builtins = [n["type"] for n in list_nodes()]
conns = [c["type"] for c in _connector_catalog_entries()]
conn_ids = [c.connector_id for c in get_registry().list_all()]
creds = [t["type"] for t in list_types()]

data = {
    "builtins": sorted(builtins),
    "connector_nodes": sorted(conns),
    "connectors": sorted(conn_ids),
    "credentials": sorted(creds),
}

out_file = ROOT / "frontend" / "src" / "all_catalog_items.json"
with open(out_file, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2)

print(f"Saved {out_file}")
print(f"Builtins: {len(builtins)}, Connector Nodes: {len(conns)}, Connectors: {len(conn_ids)}, Credentials: {len(creds)}")
