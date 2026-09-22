"""CSV / JSON transform node (spec 7).

Transforms data between CSV and JSON formats. Can convert a list of items
to CSV, parse CSV into a list of dicts, or convert JSON to/from CSV.

Modes:
- "json-to-csv": Convert JSON array to CSV
- "csv-to-json": Parse CSV string into JSON array
- "json-pretty": Pretty-print JSON
- "csv-to-json-rows": Parse CSV into list of dicts (same as csv-to-json)
"""

from __future__ import annotations

import csv
import io
import json
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.engine.node_base import BaseNode, NodeContext, NodeResult
from app.nodes.registry import register


class CsvJsonTransformParams(BaseModel):
    mode: Literal["json-to-csv", "csv-to-json", "json-pretty"] = Field(
        default="json-to-csv", description="Transformation mode."
    )
    json_input: Any = Field(
        default=None, description="JSON input (array of objects for csv-to-json)."
    )
    csv_input: str = Field(
        default="", description="CSV string input (for csv-to-json modes)."
    )
    include_header: bool = Field(
        default=True, description="Include CSV header row (json-to-csv mode)."
    )


@register
class CsvJsonTransformNode(BaseNode[CsvJsonTransformParams]):
    node_type = "csv_json_transform"
    display_name = "CSV / JSON Transform"
    version = 1
    description = "Transform data between CSV and JSON formats."
    category = "Transform"
    icon = "🔄"
    parameters_schema = CsvJsonTransformParams
    credential_types = []

    async def run(
        self,
        ctx: NodeContext,
        params: CsvJsonTransformParams,
        input_items: list[dict[str, Any]],
    ) -> NodeResult:
        mode = params.mode

        if mode == "json-to-csv":
            # Convert input items (or json_input) to CSV
            items = input_items if input_items else (params.json_input or [])
            if not items:
                return NodeResult(output_items=[])

            # Collect all possible keys
            key_set: set[str] = set()
            for item in items:
                if isinstance(item, dict):
                    key_set.update(item.keys())
            all_keys = sorted(key_set)

            output = io.StringIO()
            writer = csv.DictWriter(output, fieldnames=all_keys, extrasaction="ignore")
            if params.include_header:
                writer.writeheader()
            for item in items:
                if isinstance(item, dict):
                    writer.writerow(item)

            csv_string = output.getvalue()
            return NodeResult(output_items=[{"success": True, "csv": csv_string, "format": "csv"}])

        elif mode == "csv-to-json":
            csv_string = params.csv_input or ""
            if not csv_string.strip():
                return NodeResult(output_items=[])

            reader = csv.DictReader(io.StringIO(csv_string))
            rows = [row for row in reader]
            return NodeResult(output_items=[{"success": True, "json": rows, "format": "json"}])

        elif mode == "json-pretty":
            json_input = params.json_input or {}
            if isinstance(json_input, str):
                data = json.loads(json_input)
            else:
                data = json_input
            pretty = json.dumps(data, indent=2, ensure_ascii=False)
            return NodeResult(output_items=[{"success": True, "json": pretty, "format": "json-pretty"}])

        return NodeResult(output_items=[])
