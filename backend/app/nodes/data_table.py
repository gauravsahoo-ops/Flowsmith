"""Data Table node — CRUD operations on workspace Data Tables."""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.engine.node_base import BaseNode, NodeContext, NodeResult
from app.engine.errors import NodeExecutionError
from app.nodes.registry import register


class DataTableParams(BaseModel):
    table_id: str = Field(description="Data Table ID (dt_...) or leave empty to use table_name + workspace")
    table_name: str | None = Field(default=None, description="Alternative lookup by name (requires workspace_id)")
    workspace_id: str | None = Field(default=None, description="Workspace ID for name lookup")
    operation: Literal["select", "insert", "update", "delete", "upsert", "bulk_insert", "bulk_update", "bulk_delete"] = "select"
    # For select
    filters: list[dict[str, Any]] = Field(default_factory=list, description="Filters: [{column, op, value}]")
    search: str | None = Field(default=None)
    sort_by: str | None = Field(default=None)
    sort_order: Literal["asc", "desc"] = "asc"
    limit: int | None = Field(default=None, ge=1, le=500)
    offset: int | None = Field(default=None, ge=0)
    # For insert/update/upsert/delete
    row_data: dict[str, Any] | None = Field(default=None, description="Row data for insert/update")
    row_id: str | None = Field(default=None, description="Row ID for update/delete")
    rows: list[dict[str, Any]] | None = Field(default=None, description="Bulk rows")
    upsert_key: str | None = Field(default=None, description="Column to match for upsert (default first unique string)")


@register
class DataTableNode(BaseNode[DataTableParams]):
    node_type = "data_table"
    display_name = "Data Table"
    version = 1
    description = "Store and query structured data in workspace tables."
    category = "Database"
    icon = "🗃️"
    parameters_schema = DataTableParams
    idempotency = "conditionally_idempotent"

    async def run(self, ctx: NodeContext, params: DataTableParams, input_items: list[dict[str, Any]]) -> NodeResult:
        # Resolve workspace/table
        from sqlalchemy import select
        from app.db import get_session
        from app.models.data_table import DataTable, DataTableColumn, DataTableRow
        from app.models.organization import Workspace
        from sqlalchemy.orm.attributes import flag_modified

        # Need to run DB operations synchronously (SQLAlchemy sync)
        # Use get_session (not async)
        db = get_session()
        try:
            # Resolve table
            table = None
            if params.table_id:
                table = db.get(DataTable, params.table_id)
            elif params.table_name and params.workspace_id:
                table = db.scalar(select(DataTable).where(DataTable.workspace_id == params.workspace_id, DataTable.name == params.table_name))
            elif params.table_name and ctx.workspace_id:
                table = db.scalar(select(DataTable).where(DataTable.workspace_id == ctx.workspace_id, DataTable.name == params.table_name))
            if table is None:
                raise NodeExecutionError(f"Data Table not found (id={params.table_id or params.table_name})", code="TABLE_NOT_FOUND")

            # Workspace access check: user must be member of table's workspace
            # Use the same logic as API: check workspace membership via _require_ws_member
            # For execution, we use ctx.user_id and ctx.workspace_id? But table's workspace may differ from workflow's workspace
            # We check if user is member of table's workspace (or owner)
            if ctx.user_id is not None:
                from app.api.workspaces import _require_ws_member
                from app.models import User
                user = db.get(User, ctx.user_id)
                if user is not None:
                    allowed = _require_ws_member(db, table.workspace_id, user)
                    if not allowed:
                        raise NodeExecutionError(f"Access denied to table '{table.name}'", code="FORBIDDEN")

            cols = db.scalars(select(DataTableColumn).where(DataTableColumn.table_id == table.id).order_by(DataTableColumn.position)).all()
            col_map = {c.name: c for c in cols}

            # Helper to validate row data
            def validate_row(data: dict, partial: bool = False) -> dict:
                # reuse same logic as API but simplified
                cleaned = {}
                for col in cols:
                    raw = data.get(col.name)
                    if raw is None:
                        if col.default_value is not None:
                            # default may be JSON string
                            if col.type == "json":
                                try:
                                    raw = json.loads(col.default_value)
                                except:
                                    raw = col.default_value
                            elif col.type == "number":
                                try:
                                    raw = float(col.default_value) if "." in col.default_value else int(col.default_value)
                                except:
                                    raw = col.default_value
                            elif col.type == "boolean":
                                raw = col.default_value.lower() in ("true", "1", "yes")
                            else:
                                raw = col.default_value
                        elif col.required and not partial:
                            raise NodeExecutionError(f"Missing required column '{col.name}'", code="VALIDATION_ERROR")
                        else:
                            continue
                    if raw is None:
                        continue
                    # coerce
                    if col.type == "string":
                        cleaned[col.name] = str(raw)
                    elif col.type == "number":
                        if isinstance(raw, (int, float)):
                            cleaned[col.name] = raw
                        elif isinstance(raw, str):
                            try:
                                cleaned[col.name] = float(raw) if "." in raw else int(raw)
                            except:
                                raise NodeExecutionError(f"Column '{col.name}' expects number, got {raw!r}", code="VALIDATION_ERROR")
                        else:
                            raise NodeExecutionError(f"Column '{col.name}' expects number", code="VALIDATION_ERROR")
                    elif col.type == "boolean":
                        if isinstance(raw, bool):
                            cleaned[col.name] = raw
                        elif isinstance(raw, str):
                            low = raw.lower()
                            if low in ("true", "1", "yes"):
                                cleaned[col.name] = True
                            elif low in ("false", "0", "no"):
                                cleaned[col.name] = False
                            else:
                                raise NodeExecutionError(f"Column '{col.name}' expects boolean", code="VALIDATION_ERROR")
                        else:
                            cleaned[col.name] = bool(raw)
                    elif col.type in ("date", "datetime"):
                        # keep as string ISO
                        cleaned[col.name] = str(raw)
                    elif col.type == "json":
                        cleaned[col.name] = raw if isinstance(raw, (dict, list)) else raw
                    else:
                        cleaned[col.name] = raw
                # check unknown columns
                for k in data.keys():
                    if k not in col_map:
                        raise NodeExecutionError(f"Unknown column '{k}'", code="VALIDATION_ERROR")
                    if k not in cleaned and data[k] is not None:
                        # already validated above? ensure
                        pass
                return cleaned

            op = params.operation

            # For operations that can use input_items: if row_data is empty and input_items has data, use first input item
            def resolve_data(src: dict | None) -> dict:
                if src and any(v is not None for v in src.values()):
                    return src
                if input_items and isinstance(input_items[0], dict):
                    # if input is wrapped as {"json": {...}} from previous node? Use first item's fields that match columns
                    candidate = input_items[0]
                    # If candidate has 'json' key (from expressions), unwrap
                    if "json" in candidate and isinstance(candidate["json"], dict):
                        candidate = candidate["json"]
                    # filter to known columns
                    filtered = {k: v for k, v in candidate.items() if k in col_map}
                    if filtered:
                        return filtered
                return src or {}

            if op == "select":
                # Build query with filters/search/sort/limit
                # For simplicity, fetch all and filter in python (same as API)
                rows = list(db.scalars(select(DataTableRow).where(DataTableRow.table_id == table.id)).all())
                # apply filters
                if params.filters:
                    def match(row, f):
                        col = f.get("column")
                        oper = f.get("op", "eq")
                        val = f.get("value")
                        if col not in col_map:
                            return False
                        cell = row.data.get(col)
                        if oper == "eq":
                            return cell == val
                        elif oper == "ne":
                            return cell != val
                        elif oper == "contains":
                            return isinstance(cell, str) and isinstance(val, str) and val.lower() in cell.lower()
                        elif oper == "gt":
                            try:
                                return cell is not None and val is not None and cell > val
                            except:
                                return False
                        elif oper == "lt":
                            try:
                                return cell is not None and val is not None and cell < val
                            except:
                                return False
                        elif oper == "gte":
                            try:
                                return cell is not None and val is not None and cell >= val
                            except:
                                return False
                        elif oper == "lte":
                            try:
                                return cell is not None and val is not None and cell <= val
                            except:
                                return False
                        elif oper == "in":
                            return cell in (val if isinstance(val, list) else [val])
                        return False
                    for f in params.filters:
                        rows = [r for r in rows if match(r, f)]
                if params.search and params.search.strip():
                    q = params.search.strip().lower()
                    rows = [r for r in rows if any(q in str(v).lower() for v in r.data.values())]
                if params.sort_by:
                    if params.sort_by not in col_map:
                        raise NodeExecutionError(f"sort_by column '{params.sort_by}' not found", code="VALIDATION_ERROR")
                    reverse = params.sort_order == "desc"
                    rows.sort(key=lambda r: (r.data.get(params.sort_by) is None, r.data.get(params.sort_by)), reverse=reverse)
                else:
                    rows.sort(key=lambda r: r.created_at, reverse=True)
                if params.offset:
                    rows = rows[params.offset:]
                if params.limit:
                    rows = rows[: params.limit]
                items = [{"id": r.id, **r.data, "_id": r.id, "_created_at": r.created_at.isoformat() if r.created_at else None} for r in rows]
                # Also return via output handle main
                db.close()
                return NodeResult(output_items=items)

            elif op == "insert":
                data = resolve_data(params.row_data)
                # also try to resolve expressions already resolved by executor? row_data already resolved
                cleaned = validate_row(data, partial=False)
                import uuid
                row_id = f"dtr_{uuid.uuid4().hex[:12]}"
                row = DataTableRow(id=row_id, table_id=table.id, data=cleaned)
                db.add(row)
                table.updated_at = _now()
                db.commit()
                db.refresh(row)
                db.close()
                return NodeResult(output_items=[{"id": row.id, **row.data}])

            elif op == "update":
                if not params.row_id:
                    # try to get from input
                    if input_items and input_items[0].get("id"):
                        params.row_id = input_items[0]["id"]
                    elif input_items and input_items[0].get("_id"):
                        params.row_id = input_items[0]["_id"]
                    else:
                        raise NodeExecutionError("row_id is required for update", code="VALIDATION_ERROR")
                row = db.get(DataTableRow, params.row_id)
                if row is None or row.table_id != table.id:
                    raise NodeExecutionError(f"Row {params.row_id} not found", code="NOT_FOUND")
                data = resolve_data(params.row_data)
                # merge
                merged = {**row.data, **data}
                cleaned = validate_row(merged, partial=False)
                row.data = cleaned
                flag_modified(row, "data")
                table.updated_at = _now()
                db.commit()
                db.refresh(row)
                db.close()
                return NodeResult(output_items=[{"id": row.id, **row.data}])

            elif op == "delete":
                rid = params.row_id
                if not rid and input_items and input_items[0].get("id"):
                    rid = input_items[0]["id"]
                if not rid and input_items and input_items[0].get("_id"):
                    rid = input_items[0]["_id"]
                if not rid:
                    raise NodeExecutionError("row_id is required for delete", code="VALIDATION_ERROR")
                row = db.get(DataTableRow, rid)
                if row is None or row.table_id != table.id:
                    raise NodeExecutionError(f"Row {rid} not found", code="NOT_FOUND")
                db.delete(row)
                table.updated_at = _now()
                db.commit()
                db.close()
                return NodeResult(output_items=[{"deleted": rid}])

            elif op == "upsert":
                # upsert based on key column
                key = params.upsert_key
                if not key:
                    # pick first unique string column or first column
                    key = cols[0].name if cols else None
                if not key or key not in col_map:
                    raise NodeExecutionError(f"upsert_key '{key}' not found", code="VALIDATION_ERROR")
                data = resolve_data(params.row_data)
                if key not in data:
                    raise NodeExecutionError(f"upsert_key '{key}' missing in row_data", code="VALIDATION_ERROR")
                existing = None
                # find existing row where data[key] == value
                rows = list(db.scalars(select(DataTableRow).where(DataTableRow.table_id == table.id)).all())
                for r in rows:
                    if r.data.get(key) == data[key]:
                        existing = r
                        break
                if existing:
                    # update
                    merged = {**existing.data, **data}
                    cleaned = validate_row(merged, partial=False)
                    existing.data = cleaned
                    flag_modified(existing, "data")
                    table.updated_at = _now()
                    db.commit()
                    db.refresh(existing)
                    db.close()
                    return NodeResult(output_items=[{"id": existing.id, **existing.data, "_upsert": "updated"}])
                else:
                    cleaned = validate_row(data, partial=False)
                    import uuid
                    row_id = f"dtr_{uuid.uuid4().hex[:12]}"
                    row = DataTableRow(id=row_id, table_id=table.id, data=cleaned)
                    db.add(row)
                    table.updated_at = _now()
                    db.commit()
                    db.refresh(row)
                    db.close()
                    return NodeResult(output_items=[{"id": row.id, **row.data, "_upsert": "inserted"}])

            elif op == "bulk_insert":
                rows_data = params.rows or []
                # also support input_items as rows
                if not rows_data and input_items:
                    rows_data = [item.get("json", item) if isinstance(item, dict) and "json" in item else item for item in input_items]
                    rows_data = [r for r in rows_data if isinstance(r, dict)]
                if not rows_data:
                    raise NodeExecutionError("No rows provided for bulk_insert", code="VALIDATION_ERROR")
                if len(rows_data) > 500:
                    raise NodeExecutionError("Bulk limit 500", code="VALIDATION_ERROR")
                created = []
                import uuid
                for rd in rows_data:
                    cleaned = validate_row(rd, partial=False)
                    row_id = f"dtr_{uuid.uuid4().hex[:12]}"
                    row = DataTableRow(id=row_id, table_id=table.id, data=cleaned)
                    db.add(row)
                    created.append(row)
                table.updated_at = _now()
                db.commit()
                for r in created:
                    db.refresh(r)
                db.close()
                return NodeResult(output_items=[{"id": r.id, **r.data} for r in created])

            elif op == "bulk_update":
                rows_data = params.rows or []
                if not rows_data and input_items:
                    rows_data = input_items
                if not rows_data:
                    raise NodeExecutionError("No rows provided for bulk_update", code="VALIDATION_ERROR")
                if len(rows_data) > 500:
                    raise NodeExecutionError("Bulk limit 500", code="VALIDATION_ERROR")
                updated = []
                for item in rows_data:
                    rid = item.get("id") or item.get("_id")
                    if not rid:
                        raise NodeExecutionError("Each bulk_update row must have id", code="VALIDATION_ERROR")
                    row = db.get(DataTableRow, rid)
                    if row is None or row.table_id != table.id:
                        raise NodeExecutionError(f"Row {rid} not found", code="NOT_FOUND")
                    data = {k: v for k, v in item.items() if k not in ("id", "_id")}
                    merged = {**row.data, **data}
                    cleaned = validate_row(merged, partial=False)
                    row.data = cleaned
                    flag_modified(row, "data")
                    updated.append(row)
                table.updated_at = _now()
                db.commit()
                for r in updated:
                    db.refresh(r)
                db.close()
                return NodeResult(output_items=[{"id": r.id, **r.data} for r in updated])

            elif op == "bulk_delete":
                ids = []
                if params.rows:
                    ids = [r.get("id") or r.get("_id") for r in params.rows if isinstance(r, dict)]
                elif params.row_data and isinstance(params.row_data.get("ids"), list):
                    ids = params.row_data["ids"]
                elif input_items:
                    ids = [item.get("id") or item.get("_id") for item in input_items if isinstance(item, dict)]
                # fallback to row_id?
                if not ids and params.row_id:
                    ids = [params.row_id]
                if not ids:
                    raise NodeExecutionError("No ids provided for bulk_delete", code="VALIDATION_ERROR")
                if len(ids) > 500:
                    raise NodeExecutionError("Bulk limit 500", code="VALIDATION_ERROR")
                count = 0
                for rid in ids:
                    row = db.get(DataTableRow, rid)
                    if row and row.table_id == table.id:
                        db.delete(row)
                        count += 1
                table.updated_at = _now()
                db.commit()
                db.close()
                return NodeResult(output_items=[{"deleted": count}])

            else:
                raise NodeExecutionError(f"Unsupported operation '{op}'", code="VALIDATION_ERROR")
        except NodeExecutionError:
            try:
                db.rollback()
            except:
                pass
            db.close()
            raise
        except Exception as exc:
            try:
                db.rollback()
            except:
                pass
            db.close()
            raise NodeExecutionError(str(exc), code="NODE_ERROR") from exc
        finally:
            try:
                db.close()
            except:
                pass


def _now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)
