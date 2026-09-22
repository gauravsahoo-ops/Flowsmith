"""Admin maintenance endpoints (M9 hardening): manual retention prune.

The maintenance daemon prunes automatically on its interval; this
endpoint lets admins run a prune now (optionally with a custom window)
or preview what a prune would remove without deleting anything.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.audit import ADMIN_PRUNE, log_event
from app.config import get_settings
from app.db import get_db
from app.maintenance import prune
from app.api.common import ok
from app.api.users import get_current_admin
from app.models import User

router = APIRouter(prefix="/api/admin", tags=["admin"])


class PruneRequest(BaseModel):
    days: int | None = Field(default=None, ge=1, le=3650, description="Override the retention window.")
    dry_run: bool = Field(default=True, description="Preview only; deletes nothing when true.")


@router.post("/maintenance/prune")
def prune_endpoint(
    body: PruneRequest,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> dict:
    days = body.days or get_settings().execution_retention_days
    before = datetime.now(UTC) - timedelta(days=days)
    counts = prune(db, before, dry_run=body.dry_run)
    if not body.dry_run:
        log_event(db, ADMIN_PRUNE, target_type="system", target_id="executions",
                  user_id=admin.id, detail={"days": days, **counts})
    return ok({
        "retention_days": days,
        "before": before.isoformat(),
        "dry_run": body.dry_run,
        **counts,
    })
