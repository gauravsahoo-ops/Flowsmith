"""Install/update the certified Salesforce -> HubSpot workflows on a server.

This is the structural companion to
``fix_server_hubspot_static_credential.py``. It imports the current parent and
child workflow JSON, binds the server's Salesforce and HubSpot credentials by
ID, activates both workflows, and snapshots a new version for each.

Run it INSIDE the server's app container, where DATABASE_URL and the
credential encryption key are available.

Example (after copying the script and examples into the container):

    docker cp scripts/install_server_salesforce_hubspot_workflows.py mat-app:/tmp/install.py
    docker cp docs/examples/salesforce_to_hubspot_contact_sync.json mat-app:/tmp/parent.json
    docker cp docs/examples/salesforce_hubspot_contact_upsert.json mat-app:/tmp/child.json
    docker exec mat-app python /tmp/install.py \
        --parent /tmp/parent.json \
        --child /tmp/child.json \
        --apply

Optional flags:

    --user-id ID                     owner (defaults to the existing workflow owner)
    --salesforce-credential-id ID    explicit Salesforce credential
    --hubspot-credential-id ID       explicit HubSpot credential
    --activate / --no-activate       activate both workflows (default: activate)

The script never prints secret values and is safe to run more than once.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve()
for candidate in (_HERE.parents[1], _HERE.parents[1] / "backend", Path("/app"), Path("/app/backend")):
    if (candidate / "app").is_dir() and str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from app.db import get_session
from app.models import (
    Credential,
    User,
    WorkflowRecord,
    WorkflowVersionRecord,
)
from app.schemas.workflow import Workflow
from app.security.crypto import decrypt_text
from sqlalchemy import select

PARENT_DEFAULT = Path("docs/examples/salesforce_to_hubspot_contact_sync.json")
CHILD_DEFAULT = Path("docs/examples/salesforce_hubspot_contact_upsert.json")

SALESFORCE_PLACEHOLDER = "REPLACE_WITH_SALESFORCE_CREDENTIAL_ID"
HUBSPOT_PLACEHOLDER = "REPLACE_WITH_HUBSPOT_CREDENTIAL_ID"


def _load_workflow(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not data.get("id"):
        raise SystemExit(f"{path} is not a workflow JSON object with an id")
    return data


def _replace_credentials(data: dict[str, Any], salesforce_id: str, hubspot_id: str) -> int:
    replacements = {
        SALESFORCE_PLACEHOLDER: salesforce_id,
        HUBSPOT_PLACEHOLDER: hubspot_id,
    }
    count = 0
    for node in data.get("nodes") or []:
        credentials = node.get("credentials")
        if not isinstance(credentials, dict):
            continue
        for key, value in list(credentials.items()):
            if isinstance(value, str) and value in replacements:
                credentials[key] = replacements[value]
                count += 1
    return count


def _credential_owner(db, workflow_ids: list[str]) -> int | None:
    for workflow_id in workflow_ids:
        rec = db.get(WorkflowRecord, workflow_id)
        if rec is not None:
            return rec.user_id
    return None


def _resolve_workflow_id(db, data: dict[str, Any], user_id: int) -> str:
    """Return the record id this definition will update/create."""
    rec = db.get(WorkflowRecord, str(data["id"]))
    if rec is not None:
        return rec.id
    rec = db.scalars(
        select(WorkflowRecord).where(
            WorkflowRecord.user_id == user_id,
            WorkflowRecord.name == str(data.get("name") or ""),
            WorkflowRecord.deleted_at.is_(None),
        )
    ).first()
    return rec.id if rec is not None else str(data["id"])


def _patch_subworkflow_target(data: dict[str, Any], child_id: str) -> int:
    """Point the parent's Execute Sub-workflow node at the real child id."""
    patched = 0
    for node in data.get("nodes") or []:
        if node.get("type") != "sub_workflow":
            continue
        params = node.setdefault("parameters", {})
        current = str(params.get("workflow_id") or "").strip()
        if not current or current.startswith("wf_salesforce_hubspot_contact"):
            params["workflow_id"] = child_id
            params["workflow_selector"] = "id"
            patched += 1
    return patched


def _pick_credential(db, user_id: int, credential_type: str) -> Credential | None:
    rows = list(
        db.scalars(
            select(Credential)
            .where(Credential.user_id == user_id, Credential.type == credential_type)
            .order_by(Credential.created_at.desc())
        ).all()
    )
    if not rows:
        return None
    if credential_type != "hubspot":
        return rows[0]
    # Prefer a credential that actually carries a private token, then fall
    # back to the newest HubSpot credential.
    for row in rows:
        try:
            payload = json.loads(decrypt_text(row.data))
        except Exception:  # noqa: BLE001, S112 - skip malformed rows
            continue
        if str(payload.get("private_token") or "").strip():
            return row
    return rows[0]


def _describe_credential(cred: Credential) -> str:
    return f"{cred.id} ({cred.name})"


def _upsert_workflow(
    db,
    *,
    data: dict[str, Any],
    user_id: int,
    activate: bool,
    dry_run: bool,
) -> tuple[str, int, str]:
    workflow_id = str(data["id"])
    rec = db.get(WorkflowRecord, workflow_id)
    if rec is None:
        # Fall back to a name match so a renamed server workflow is updated
        # instead of duplicated.
        rec = db.scalars(
            select(WorkflowRecord).where(
                WorkflowRecord.user_id == user_id,
                WorkflowRecord.name == str(data.get("name") or ""),
                WorkflowRecord.deleted_at.is_(None),
            )
        ).first()

    validated = Workflow.model_validate(data)
    normalized = validated.model_dump(mode="json")
    action = "update" if rec is not None else "create"
    version = (int(rec.version or 1) + 1) if rec is not None else 1

    if dry_run:
        target = rec.id if rec is not None else workflow_id
        return target, version, action

    if rec is None:
        rec = WorkflowRecord(
            id=workflow_id,
            user_id=user_id,
            workspace_id=None,
            name=normalized.get("name") or workflow_id,
            data=normalized,
            version=1,
            active=activate,
        )
        db.add(rec)
        db.flush()
    else:
        rec.name = normalized.get("name") or rec.name
        rec.data = normalized
        rec.version = version
        rec.active = activate
        db.query(WorkflowVersionRecord).filter(
            WorkflowVersionRecord.workflow_id == rec.id,
            WorkflowVersionRecord.version != version,
        ).update({"is_active": False})

    db.add(
        WorkflowVersionRecord(
            id=f"ver_{uuid.uuid4().hex[:12]}",
            workflow_id=rec.id,
            workspace_id=rec.workspace_id,
            version=version,
            data=normalized,
            user_id=user_id,
            is_active=True,
        )
    )
    return rec.id, version, action


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parent", default=str(PARENT_DEFAULT))
    parser.add_argument("--child", default=str(CHILD_DEFAULT))
    parser.add_argument("--user-id", type=int, default=0)
    parser.add_argument("--salesforce-credential-id", default="")
    parser.add_argument("--hubspot-credential-id", default="")
    parser.add_argument("--apply", action="store_true", help="persist the changes")
    parser.add_argument("--no-activate", action="store_true")
    args = parser.parse_args()

    parent = _load_workflow(Path(args.parent))
    child = _load_workflow(Path(args.child))

    db = get_session()
    try:
        user_id = args.user_id or _credential_owner(db, [parent["id"], child["id"]])
        if not user_id:
            first = db.scalars(select(User).order_by(User.id).limit(1)).first()
            user_id = first.id if first is not None else None
        if not user_id:
            print("No user found. Pass --user-id.", file=sys.stderr)
            return 1

        if args.salesforce_credential_id:
            salesforce = db.get(Credential, args.salesforce_credential_id)
        else:
            salesforce = _pick_credential(db, user_id, "salesforce")
        if salesforce is None or salesforce.user_id != user_id or salesforce.type != "salesforce":
            print("No Salesforce credential found for this owner.", file=sys.stderr)
            return 1

        if args.hubspot_credential_id:
            hubspot = db.get(Credential, args.hubspot_credential_id)
        else:
            hubspot = _pick_credential(db, user_id, "hubspot")
        if hubspot is None or hubspot.user_id != user_id or hubspot.type != "hubspot":
            print("No HubSpot credential found for this owner.", file=sys.stderr)
            return 1

        print(f"owner={user_id}")
        print(f"salesforce={_describe_credential(salesforce)}")
        print(f"hubspot={_describe_credential(hubspot)}")

        parent_replacements = _replace_credentials(parent, salesforce.id, hubspot.id)
        child_replacements = _replace_credentials(child, salesforce.id, hubspot.id)
        print(
            f"credential bindings: parent={parent_replacements} child={child_replacements} "
            "(placeholder occurrences replaced)"
        )

        child_target_id = _resolve_workflow_id(db, child, user_id)
        patched = _patch_subworkflow_target(parent, child_target_id)
        print(f"sub_workflow target: {child_target_id} ({patched} node(s) patched)")

        activate = not args.no_activate
        # Child first so the parent always points at the actual child record.
        plans = [("child", child), ("parent", parent)]
        for label, data in plans:
            try:
                wf_id, version, action = _upsert_workflow(
                    db,
                    data=data,
                    user_id=user_id,
                    activate=activate,
                    dry_run=not args.apply,
                )
            except Exception as exc:  # noqa: BLE001 - report the failing workflow
                db.rollback()
                print(f"{label}: FAILED: {exc}", file=sys.stderr)
                return 1
            print(f"{label}: would {action} {wf_id} as v{version}" if not args.apply else f"{label}: {action} {wf_id} -> v{version}")

        if not args.apply:
            print("dry run only; pass --apply to persist")
            return 0

        db.commit()
        print("done")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
