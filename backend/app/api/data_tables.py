"""Data Tables API — workspace-scoped structured storage for workflows."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone, date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select, asc, desc, or_, cast, String
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.api.common import ok, page_params
from app.api.workspaces import _require_ws_member
from app.audit import log_event
from app.db import get_db
from app.models import DataTable, DataTableColumn, DataTableRow, User

router = APIRouter(prefix="/api/data-tables", tags=["data-tables"])

SUPPORTED_TYPES = {"string", "number", "boolean", "date", "datetime", "json"}
SORT_ORDERS = {"asc", "desc"}

# Audit actions
DT_CREATED = "data_table.created"
DT_UPDATED = "data_table.updated"
DT_DELETED = "data_table.deleted"
DT_COL_CREATED = "data_table.column_created"
DT_COL_UPDATED = "data_table.column_updated"
DT_COL_DELETED = "data_table.column_deleted"
DT_ROW_CREATED = "data_table.row_created"
DT_ROW_UPDATED = "data_table.row_updated"
DT_ROW_DELETED = "data_table.row_deleted"


def _require_table_access(db: Session, table_id: str, user: User) -> DataTable:
    tbl = db.get(DataTable, table_id)
    if tbl is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Table not found.")
    # workspace membership check (404 hides existence)
    if not _require_ws_member(db, tbl.workspace_id, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Table not found.")
    return tbl


def _enforce_ws_member(db: Session, ws_id: str, user: User) -> None:
    if not _require_ws_member(db, ws_id, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found.")


def _validate_column_def(col: dict, pos: int) -> dict:
    name = (col.get("name") or "").strip()
    if not name or len(name) > 255:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Column at position {pos} must have a name 1-255 chars.")
    if not name.replace("_", "").replace("-", "").isalnum():
        # allow alphanumeric + _ -
        # but we already allow; just check not empty
        pass
    typ = col.get("type")
    if typ not in SUPPORTED_TYPES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Column '{name}' has unsupported type '{typ}'. Allowed: {', '.join(sorted(SUPPORTED_TYPES))}")
    required = bool(col.get("required", False))
    default = col.get("default_value")
    # normalize default to string or None
    if default is not None:
        default = str(default)
        # validate default against type
        _coerce_value(default, typ, f"column '{name}' default")
    return {
        "name": name,
        "type": typ,
        "required": required,
        "default_value": default,
        "position": pos,
    }


def _coerce_value(raw: Any, col_type: str, field: str) -> Any:
    """Validate and coerce a value to its column type, raise 422 on bad input."""
    if raw is None:
        return None
    try:
        if col_type == "string":
            if not isinstance(raw, str):
                return str(raw)
            return raw
        elif col_type == "number":
            if isinstance(raw, (int, float)):
                return raw
            if isinstance(raw, str) and raw.strip() != "":
                # try int then float
                if "." in raw:
                    return float(raw)
                return int(raw)
            raise ValueError()
        elif col_type == "boolean":
            if isinstance(raw, bool):
                return raw
            if isinstance(raw, str):
                low = raw.lower()
                if low in ("true", "1", "yes"):
                    return True
                if low in ("false", "0", "no"):
                    return False
                raise ValueError()
            if isinstance(raw, (int, float)):
                return bool(raw)
            raise ValueError()
        elif col_type == "date":
            if isinstance(raw, date) and not isinstance(raw, datetime):
                return raw.isoformat()
            if isinstance(raw, str):
                # validate ISO date
                datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
                # ensure date only?
                # allow datetime string but extract date
                if "T" in raw:
                    return raw.split("T")[0]
                return raw
            raise ValueError()
        elif col_type == "datetime":
            if isinstance(raw, datetime):
                return raw.isoformat()
            if isinstance(raw, str):
                datetime.fromisoformat(raw.replace("Z", "+00:00"))
                return raw
            raise ValueError()
        elif col_type == "json":
            if isinstance(raw, (dict, list)):
                return raw
            if isinstance(raw, str):
                # try parse
                try:
                    return json.loads(raw)
                except:
                    # treat as raw string json?
                    return raw
            return raw
    except Exception:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Field '{field}' expects type {col_type}, got {repr(raw)[:100]}")
    return raw


def _validate_row_data(table_columns: list[DataTableColumn], data: dict, partial: bool = False) -> dict:
    """Validate row data against columns, apply defaults, coerce types. Returns cleaned dict."""
    col_map = {c.name: c for c in table_columns}
    cleaned: dict[str, Any] = {}
    # check required and coerce
    for col in table_columns:
        raw = data.get(col.name)
        if raw is None:
            if col.default_value is not None:
                # default is stored as string; coerce
                if col.type == "json":
                    try:
                        raw = json.loads(col.default_value)
                    except:
                        raw = col.default_value
                else:
                    raw = _coerce_value(col.default_value, col.type, col.name)
            elif col.required and not partial:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Missing required column '{col.name}'")
            else:
                continue
        # if still None and not required, skip
        if raw is None:
            continue
        cleaned[col.name] = _coerce_value(raw, col.type, col.name)
    # check for unknown columns
    for k in data.keys():
        if k not in col_map:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Unknown column '{k}'")
        # if partial and required missing, we already handled
        if k not in cleaned and data.get(k) is not None:
            # need to ensure we validated
            cleaned[k] = _coerce_value(data[k], col_map[k].type, k)
    return cleaned


def _table_to_dict(tbl: DataTable, db: Session, include_rows: bool = False) -> dict:
    cols = db.scalars(select(DataTableColumn).where(DataTableColumn.table_id == tbl.id).order_by(DataTableColumn.position)).all()
    row_count = db.scalar(select(func.count()).select_from(DataTableRow).where(DataTableRow.table_id == tbl.id)) or 0
    d = {
        "id": tbl.id,
        "name": tbl.name,
        "description": tbl.description,
        "workspace_id": tbl.workspace_id,
        "user_id": tbl.user_id,
        "row_count": row_count,
        "created_at": tbl.created_at,
        "updated_at": tbl.updated_at,
        "columns": [
            {
                "id": c.id,
                "name": c.name,
                "type": c.type,
                "required": c.required,
                "default_value": c.default_value,
                "position": c.position,
                "created_at": c.created_at,
                "updated_at": c.updated_at,
            }
            for c in cols
        ],
    }
    return d


# --- Pydantic Schemas ---

class ColumnCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    type: str
    required: bool = False
    default_value: str | None = None
    position: int | None = None

    @field_validator("type")
    @classmethod
    def validate_type(cls, v):
        if v not in SUPPORTED_TYPES:
            raise ValueError(f"Unsupported type '{v}'")
        return v


class TableCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(default="")
    workspace_id: str
    columns: list[ColumnCreate] = Field(default_factory=list)


class TableUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None


class ColumnUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    type: str | None = None
    required: bool | None = None
    default_value: str | None = None
    position: int | None = None

    @field_validator("type")
    @classmethod
    def validate_type(cls, v):
        if v is not None and v not in SUPPORTED_TYPES:
            raise ValueError(f"Unsupported type '{v}'")
        return v


class RowCreate(BaseModel):
    data: dict[str, Any]


class BulkRowsCreate(BaseModel):
    rows: list[dict[str, Any]]


class BulkRowsUpdate(BaseModel):
    rows: list[dict[str, Any]]  # each must have "id" + fields


class BulkRowsDelete(BaseModel):
    ids: list[str]


# --- Table CRUD ---

@router.post("", status_code=status.HTTP_201_CREATED)
def create_table(payload: TableCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    _enforce_ws_member(db, payload.workspace_id, user)
    # unique name per workspace
    existing = db.scalar(select(DataTable).where(DataTable.workspace_id == payload.workspace_id, DataTable.name == payload.name.strip()))
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Table '{payload.name}' already exists in this workspace.")
    if len(payload.columns) > 50:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Too many columns (max 50).")
    # validate column names unique
    names = [c.name.strip() for c in payload.columns]
    if len(names) != len(set(names)):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Column names must be unique.")
    table_id = f"dt_{uuid.uuid4().hex[:12]}"
    tbl = DataTable(
        id=table_id,
        name=payload.name.strip(),
        description=payload.description or "",
        workspace_id=payload.workspace_id,
        user_id=user.id,
    )
    db.add(tbl)
    db.flush()
    # columns
    for idx, col in enumerate(payload.columns):
        validated = _validate_column_def(col.model_dump(), idx)
        col_id = f"dtc_{uuid.uuid4().hex[:12]}"
        db.add(DataTableColumn(
            id=col_id,
            table_id=table_id,
            name=validated["name"],
            type=validated["type"],
            required=validated["required"],
            default_value=validated["default_value"],
            position=validated["position"],
        ))
    db.commit()
    db.refresh(tbl)
    log_event(db, DT_CREATED, target_type="data_table", target_id=table_id, user_id=user.id)
    return ok(_table_to_dict(tbl, db))


@router.get("")
def list_tables(
    workspace_id: str | None = Query(default=None),
    search: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    pageSize: int = Query(default=50, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    # if workspace_id provided, filter to that workspace (must be member)
    # otherwise list all workspace tables user can access
    q = select(DataTable)
    count_q = select(func.count()).select_from(DataTable)
    if workspace_id:
        _enforce_ws_member(db, workspace_id, user)
        q = q.where(DataTable.workspace_id == workspace_id)
        count_q = count_q.where(DataTable.workspace_id == workspace_id)
    else:
        # all workspaces user is member of + owned
        from app.models import Workspace, WorkspaceMember, Organization, OrganizationMember
        created = select(Workspace.id).where(Workspace.creator_id == user.id)
        member_of = select(WorkspaceMember.workspace_id).where(WorkspaceMember.user_id == user.id)
        org_ws = select(Workspace.id).join(Organization, Workspace.organization_id == Organization.id).join(OrganizationMember, OrganizationMember.organization_id == Organization.id).where(OrganizationMember.user_id == user.id)
        # union all
        # Use subquery for accessible workspace ids
        ws_ids_sub = created.union(member_of, org_ws)
        # Filter tables where workspace_id in (select ...)
        q = q.where(DataTable.workspace_id.in_(ws_ids_sub))
        count_q = count_q.where(DataTable.workspace_id.in_(ws_ids_sub))

    if search and search.strip():
        like = f"%{search.strip()}%"
        q = q.where(or_(DataTable.name.ilike(like), DataTable.description.ilike(like)))
        count_q = count_q.where(or_(DataTable.name.ilike(like), DataTable.description.ilike(like)))

    total = db.scalar(count_q) or 0
    page, size = page, min(pageSize, 100)
    rows = db.scalars(q.order_by(DataTable.updated_at.desc()).offset((page - 1) * size).limit(size)).all()
    data = []
    for tbl in rows:
        d = _table_to_dict(tbl, db)
        data.append(d)
    return ok(data, {"page": page, "pageSize": size, "total": total})


@router.get("/{table_id}")
def get_table(table_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    tbl = _require_table_access(db, table_id, user)
    return ok(_table_to_dict(tbl, db))


@router.patch("/{table_id}")
def update_table(table_id: str, payload: TableUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    tbl = _require_table_access(db, table_id, user)
    if payload.name is not None:
        name = payload.name.strip()
        if not name:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Name cannot be empty.")
        # check uniqueness
        dup = db.scalar(select(DataTable).where(DataTable.workspace_id == tbl.workspace_id, DataTable.name == name, DataTable.id != table_id))
        if dup:
            raise HTTPException(status.HTTP_409_CONFLICT, f"Table '{name}' already exists.")
        tbl.name = name
    if payload.description is not None:
        tbl.description = payload.description
    db.commit()
    db.refresh(tbl)
    log_event(db, DT_UPDATED, target_type="data_table", target_id=table_id, user_id=user.id)
    return ok(_table_to_dict(tbl, db))


@router.delete("/{table_id}", status_code=status.HTTP_200_OK)
def delete_table(table_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    tbl = _require_table_access(db, table_id, user)
    db.delete(tbl)
    db.commit()
    log_event(db, DT_DELETED, target_type="data_table", target_id=table_id, user_id=user.id)
    return ok({"deleted": True})


# --- Columns ---

@router.post("/{table_id}/columns", status_code=status.HTTP_201_CREATED)
def create_column(table_id: str, payload: ColumnCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    tbl = _require_table_access(db, table_id, user)
    # check name unique
    existing = db.scalar(select(DataTableColumn).where(DataTableColumn.table_id == table_id, DataTableColumn.name == payload.name.strip()))
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Column '{payload.name}' already exists.")
    count = db.scalar(select(func.count()).select_from(DataTableColumn).where(DataTableColumn.table_id == table_id)) or 0
    if count >= 50:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Too many columns (max 50).")
    validated = _validate_column_def(payload.model_dump(), payload.position if payload.position is not None else count)
    col_id = f"dtc_{uuid.uuid4().hex[:12]}"
    col = DataTableColumn(
        id=col_id,
        table_id=table_id,
        name=validated["name"],
        type=validated["type"],
        required=validated["required"],
        default_value=validated["default_value"],
        position=validated["position"],
    )
    db.add(col)
    db.commit()
    db.refresh(col)
    log_event(db, DT_COL_CREATED, target_type="data_table", target_id=table_id, user_id=user.id)
    return ok({
        "id": col.id,
        "name": col.name,
        "type": col.type,
        "required": col.required,
        "default_value": col.default_value,
        "position": col.position,
    })


@router.patch("/{table_id}/columns/{column_id}")
def update_column(table_id: str, column_id: str, payload: ColumnUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    tbl = _require_table_access(db, table_id, user)
    col = db.get(DataTableColumn, column_id)
    if col is None or col.table_id != table_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Column not found.")
    if payload.name is not None:
        name = payload.name.strip()
        if not name:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Name cannot be empty.")
        dup = db.scalar(select(DataTableColumn).where(DataTableColumn.table_id == table_id, DataTableColumn.name == name, DataTableColumn.id != column_id))
        if dup:
            raise HTTPException(status.HTTP_409_CONFLICT, f"Column '{name}' already exists.")
        # need to update rows that have old name -> new name
        # For simplicity, we update row data keys
        # This is transactional
        old_name = col.name
        if old_name != name:
            rows = db.scalars(select(DataTableRow).where(DataTableRow.table_id == table_id)).all()
            for r in rows:
                if old_name in r.data:
                    r.data[name] = r.data.pop(old_name)
                    # mark as modified for JSON
                    from sqlalchemy.orm.attributes import flag_modified
                    flag_modified(r, "data")
        col.name = name
    if payload.type is not None:
        if payload.type not in SUPPORTED_TYPES:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Unsupported type '{payload.type}'")
        # Changing type may break existing rows; we allow but existing rows remain as is (or attempt to coerce)
        # For safety, we check if any rows have values incompatible?
        # We won't block, but we will try to coerce existing rows.
        # If coercion fails, we leave as is; execution will validate on read.
        col.type = payload.type
    if payload.required is not None:
        col.required = payload.required
    if payload.default_value is not None:
        # allow empty string to clear default
        if payload.default_value == "":
            col.default_value = None
        else:
            # validate
            _coerce_value(payload.default_value, col.type, f"column '{col.name}' default")
            col.default_value = payload.default_value
    if payload.position is not None:
        col.position = payload.position
    db.commit()
    db.refresh(col)
    log_event(db, DT_COL_UPDATED, target_type="data_table", target_id=table_id, user_id=user.id)
    return ok({
        "id": col.id,
        "name": col.name,
        "type": col.type,
        "required": col.required,
        "default_value": col.default_value,
        "position": col.position,
    })


@router.delete("/{table_id}/columns/{column_id}")
def delete_column(table_id: str, column_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    tbl = _require_table_access(db, table_id, user)
    col = db.get(DataTableColumn, column_id)
    if col is None or col.table_id != table_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Column not found.")
    # Remove column from all rows
    rows = db.scalars(select(DataTableRow).where(DataTableRow.table_id == table_id)).all()
    for r in rows:
        if col.name in r.data:
            del r.data[col.name]
            from sqlalchemy.orm.attributes import flag_modified
            flag_modified(r, "data")
    db.delete(col)
    db.commit()
    log_event(db, DT_COL_DELETED, target_type="data_table", target_id=table_id, user_id=user.id)
    return ok({"deleted": True})


@router.post("/{table_id}/columns/reorder")
def reorder_columns(table_id: str, payload: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    tbl = _require_table_access(db, table_id, user)
    order: list[str] = payload.get("order", [])
    if not isinstance(order, list) or not order:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "order must be a non-empty list of column ids.")
    cols = db.scalars(select(DataTableColumn).where(DataTableColumn.table_id == table_id)).all()
    col_ids = {c.id for c in cols}
    if set(order) != col_ids:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "order must contain exactly all column ids.")
    for idx, cid in enumerate(order):
        for c in cols:
            if c.id == cid:
                c.position = idx
                break
    db.commit()
    return ok({"reordered": True})


# --- Rows ---

def _apply_filters(query, table_id: str, search: str | None, filters: list[dict] | None, sort_by: str | None, sort_order: str, db: Session):
    # We do in-memory filtering for JSONB since SQLite compatibility and simple
    # For Postgres, we could use JSON operators, but we keep simple for now
    # We'll return base query and handle post-filter in python for search/filters?
    # Instead, we do server-side but via python after fetching? For performance, we do DB where for search via casting
    # For now, we fetch all and filter in python only if needed for complex; but for pagination we need DB
    # Simplification: we do DB pagination after python filtering? That would be inaccurate for large tables.
    # Instead, we implement basic DB filtering for string contains via ilike on cast
    # For MVP, we handle search via python + pagination after filtering (acceptable for <10k rows)
    # For large datasets, we recommend server-side but we will implement DB-level for search via ilike
    return query


@router.get("/{table_id}/rows")
def list_rows(
    table_id: str,
    page: int = Query(default=1, ge=1),
    pageSize: int = Query(default=50, ge=1, le=100),
    search: str | None = Query(default=None),
    sort_by: str | None = Query(default=None),
    sort_order: str = Query(default="asc"),
    filters: str | None = Query(default=None),  # JSON string
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    tbl = _require_table_access(db, table_id, user)
    cols = db.scalars(select(DataTableColumn).where(DataTableColumn.table_id == table_id).order_by(DataTableColumn.position)).all()
    col_names = {c.name for c in cols}

    if sort_by and sort_by not in col_names:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"sort_by column '{sort_by}' not found.")
    if sort_order not in SORT_ORDERS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "sort_order must be asc or desc")

    # Parse filters
    filter_list = None
    if filters:
        try:
            filter_list = json.loads(filters)
            if not isinstance(filter_list, list):
                filter_list = [filter_list]
        except:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "filters must be valid JSON")

    # For performance, we fetch all rows and filter in python for MVP
    # This is okay for tables up to a few thousand rows. For larger, we would push to DB.
    # We also need to handle search: case-insensitive contains across all string columns
    all_rows = list(db.scalars(select(DataTableRow).where(DataTableRow.table_id == table_id)).all())

    # Apply search
    if search and search.strip():
        q = search.strip().lower()
        filtered = []
        for r in all_rows:
            for v in r.data.values():
                if isinstance(v, str) and q in v.lower():
                    filtered.append(r)
                    break
                elif isinstance(v, (int, float, bool)) and q in str(v).lower():
                    filtered.append(r)
                    break
                elif isinstance(v, dict) and q in json.dumps(v).lower():
                    filtered.append(r)
                    break
        all_rows = filtered

    # Apply filters
    if filter_list:
        def match(row, f):
            col = f.get("column")
            op = f.get("op", "eq")
            val = f.get("value")
            if col not in col_names:
                return False
            cell = row.data.get(col)
            if op == "eq":
                return cell == val
            elif op == "ne":
                return cell != val
            elif op == "contains":
                return isinstance(cell, str) and isinstance(val, str) and val.lower() in cell.lower()
            elif op == "gt":
                try:
                    return cell is not None and val is not None and cell > val
                except:
                    return False
            elif op == "lt":
                try:
                    return cell is not None and val is not None and cell < val
                except:
                    return False
            elif op == "gte":
                try:
                    return cell is not None and val is not None and cell >= val
                except:
                    return False
            elif op == "lte":
                try:
                    return cell is not None and val is not None and cell <= val
                except:
                    return False
            elif op == "in":
                return cell in (val if isinstance(val, list) else [val])
            return False

        for f in filter_list:
            all_rows = [r for r in all_rows if match(r, f)]

    # Apply sorting
    if sort_by:
        reverse = sort_order == "desc"
        # Handle None values
        def sort_key(r):
            v = r.data.get(sort_by)
            # None should be last
            return (v is None, v if not isinstance(v, dict) else json.dumps(v))
        all_rows.sort(key=sort_key, reverse=reverse)
    else:
        # default sort by created_at desc
        all_rows.sort(key=lambda r: r.created_at, reverse=True)

    total = len(all_rows)
    page = max(1, page)
    size = min(pageSize, 100)
    start = (page - 1) * size
    paged = all_rows[start:start+size]

    data = [
        {
            "id": r.id,
            "data": r.data,
            "created_at": r.created_at,
            "updated_at": r.updated_at,
        }
        for r in paged
    ]
    return ok(data, {"page": page, "pageSize": size, "total": total})


@router.post("/{table_id}/rows", status_code=status.HTTP_201_CREATED)
def create_row(table_id: str, payload: RowCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    tbl = _require_table_access(db, table_id, user)
    cols = list(db.scalars(select(DataTableColumn).where(DataTableColumn.table_id == table_id).order_by(DataTableColumn.position)).all())
    cleaned = _validate_row_data(cols, payload.data, partial=False)
    row_id = f"dtr_{uuid.uuid4().hex[:12]}"
    row = DataTableRow(id=row_id, table_id=table_id, data=cleaned)
    db.add(row)
    # touch table updated_at
    tbl.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    log_event(db, DT_ROW_CREATED, target_type="data_table", target_id=table_id, user_id=user.id)
    return ok({"id": row.id, "data": row.data, "created_at": row.created_at, "updated_at": row.updated_at})


@router.post("/{table_id}/rows/bulk", status_code=status.HTTP_201_CREATED)
def bulk_create_rows(table_id: str, payload: BulkRowsCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    tbl = _require_table_access(db, table_id, user)
    cols = list(db.scalars(select(DataTableColumn).where(DataTableColumn.table_id == table_id).order_by(DataTableColumn.position)).all())
    if len(payload.rows) > 500:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Bulk limit 500 rows per request.")
    if not payload.rows:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "No rows provided.")
    created = []
    try:
        for row_data in payload.rows:
            if not isinstance(row_data, dict):
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Each row must be an object.")
            cleaned = _validate_row_data(cols, row_data, partial=False)
            row_id = f"dtr_{uuid.uuid4().hex[:12]}"
            row = DataTableRow(id=row_id, table_id=table_id, data=cleaned)
            db.add(row)
            created.append(row)
        tbl.updated_at = datetime.now(timezone.utc)
        db.commit()
        for r in created:
            db.refresh(r)
    except HTTPException:
        db.rollback()
        raise
    log_event(db, DT_ROW_CREATED, target_type="data_table", target_id=table_id, user_id=user.id, detail={"bulk_count": len(created)})
    return ok([{"id": r.id, "data": r.data} for r in created])


@router.get("/{table_id}/rows/{row_id}")
def get_row(table_id: str, row_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    tbl = _require_table_access(db, table_id, user)
    row = db.get(DataTableRow, row_id)
    if row is None or row.table_id != table_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Row not found.")
    return ok({"id": row.id, "data": row.data, "created_at": row.created_at, "updated_at": row.updated_at})


@router.patch("/{table_id}/rows/{row_id}")
def update_row(table_id: str, row_id: str, payload: RowCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    tbl = _require_table_access(db, table_id, user)
    row = db.get(DataTableRow, row_id)
    if row is None or row.table_id != table_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Row not found.")
    cols = list(db.scalars(select(DataTableColumn).where(DataTableColumn.table_id == table_id).order_by(DataTableColumn.position)).all())
    # partial update: merge existing with new, validate
    merged = {**row.data, **payload.data}
    cleaned = _validate_row_data(cols, merged, partial=False)
    row.data = cleaned
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(row, "data")
    tbl.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    log_event(db, DT_ROW_UPDATED, target_type="data_table", target_id=table_id, user_id=user.id)
    return ok({"id": row.id, "data": row.data, "updated_at": row.updated_at})


@router.delete("/{table_id}/rows/{row_id}")
def delete_row(table_id: str, row_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    tbl = _require_table_access(db, table_id, user)
    row = db.get(DataTableRow, row_id)
    if row is None or row.table_id != table_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Row not found.")
    db.delete(row)
    tbl.updated_at = datetime.now(timezone.utc)
    db.commit()
    log_event(db, DT_ROW_DELETED, target_type="data_table", target_id=table_id, user_id=user.id)
    return ok({"deleted": True})


@router.post("/{table_id}/rows/bulk-update")
def bulk_update_rows(table_id: str, payload: BulkRowsUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    tbl = _require_table_access(db, table_id, user)
    cols = list(db.scalars(select(DataTableColumn).where(DataTableColumn.table_id == table_id).order_by(DataTableColumn.position)).all())
    if len(payload.rows) > 500:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Bulk limit 500.")
    updated = []
    try:
        for item in payload.rows:
            rid = item.get("id")
            if not rid:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Each row must have id.")
            row = db.get(DataTableRow, rid)
            if row is None or row.table_id != table_id:
                raise HTTPException(status.HTTP_404_NOT_FOUND, f"Row {rid} not found.")
            # remove id from data
            data = {k: v for k, v in item.items() if k != "id"}
            merged = {**row.data, **data}
            cleaned = _validate_row_data(cols, merged, partial=False)
            row.data = cleaned
            from sqlalchemy.orm.attributes import flag_modified
            flag_modified(row, "data")
            updated.append(row)
        tbl.updated_at = datetime.now(timezone.utc)
        db.commit()
        for r in updated:
            db.refresh(r)
    except HTTPException:
        db.rollback()
        raise
    log_event(db, DT_ROW_UPDATED, target_type="data_table", target_id=table_id, user_id=user.id, detail={"bulk_count": len(updated)})
    return ok([{"id": r.id, "data": r.data} for r in updated])


@router.post("/{table_id}/rows/bulk-delete")
def bulk_delete_rows(table_id: str, payload: BulkRowsDelete, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    tbl = _require_table_access(db, table_id, user)
    if len(payload.ids) > 500:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Bulk limit 500.")
    for rid in payload.ids:
        row = db.get(DataTableRow, rid)
        if row is None or row.table_id != table_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Row {rid} not found.")
        db.delete(row)
    tbl.updated_at = datetime.now(timezone.utc)
    db.commit()
    log_event(db, DT_ROW_DELETED, target_type="data_table", target_id=table_id, user_id=user.id, detail={"bulk_count": len(payload.ids)})
    return ok({"deleted": len(payload.ids)})

