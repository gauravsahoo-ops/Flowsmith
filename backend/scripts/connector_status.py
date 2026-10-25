#!/usr/bin/env python3
"""Report the real composition of the connector registry.

Run from the backend directory:

    python scripts/connector_status.py

The registry has three distinct populations:

* native      - hand-written vendor-specific connector classes
* generated   - connectors generated from an OpenAPI description
* catalog_only- generic reference-inventory entries that require an explicit
                endpoint_url and have no vendor-specific execution code

Catalog-only connectors must never be presented as equivalent to native
integrations.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

# Allow `python scripts/connector_status.py` from the backend directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.connectors import get_registry, register_builtin_connectors
from app.connectors.parity_connectors import ParityConnector
from app.nodes.registry import NODE_REGISTRY


def classify(connector: object) -> str:
    if isinstance(connector, ParityConnector):
        return "catalog_only"
    module = type(connector).__module__
    if module.startswith("app.connectors.generated."):
        return "generated"
    return "native"


def main() -> int:
    register_builtin_connectors()
    registry = get_registry()

    rows: list[dict[str, str | int | bool]] = []
    kinds: Counter[str] = Counter()
    scopes: Counter[str] = Counter()
    total_operations = 0

    for info in registry.list_all():
        connector = registry.get(info.connector_id)
        definition = registry.get_definition(info.connector_id)
        kind = classify(connector)
        kinds[kind] += 1
        if definition and isinstance(connector, ParityConnector):
            if definition.connector_key in NODE_REGISTRY:
                scopes["node_shadow"] += 1
            elif definition.triggers or definition.connector_key.endswith("_trigger"):
                scopes["trigger_alias"] += 1
            else:
                scopes["vendor"] += 1
        operations = len(definition.operations) if definition else 0
        total_operations += operations
        rows.append(
            {
                "connector_id": info.connector_id,
                "kind": kind,
                "operations": operations,
                "requires_endpoint": bool(
                    definition and definition.metadata.get("requires_endpoint")
                ),
            }
        )

    total = len(rows)
    native = kinds["native"]
    generated = kinds["generated"]
    catalog_only = kinds["catalog_only"]

    print(f"Total registered names: {total}")
    print(f"  native:       {native}")
    print(f"  generated:    {generated}")
    print(f"  catalog_only: {catalog_only}")
    print(f"Total declared operations: {total_operations}")
    if scopes:
        print(f"  catalog scopes: {dict(scopes)}")
    print()
    print("Catalog-only connectors require an explicit endpoint_url.")
    print("They are not vendor-specific integrations.")
    print("Only catalog_scope='vendor' entries are native-conversion candidates.")
    print()
    print(json.dumps({"summary": dict(kinds), "total": total}, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
