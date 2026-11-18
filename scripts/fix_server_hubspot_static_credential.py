"""Switch a deployed workflow's HubSpot credential to a static private token.

Run this INSIDE the server's app container, where DATABASE_URL and the
credential encryption key are available. By default it converts the HubSpot
credentials already referenced by the workflow in place, so every HubSpot node
keeps working without editing or re-versioning the workflow.

The token is never printed. The script is safe to run more than once.

Examples (on the server host):

    docker cp scripts/fix_server_hubspot_static_credential.py mat-app:/tmp/fix_hubspot.py
    docker exec -e HUBSPOT_STATIC_TOKEN='pat-...' mat-app python /tmp/fix_hubspot.py --apply

Optional environment variables:

    USER_ID              owner id (defaults to the owner of the target workflow)
    WORKFLOW_ID          only touch this workflow (default: all of the owner's
                         workflows that contain HubSpot nodes)
    CREDENTIAL_NAME      credential used by --rebind
    HUBSPOT_STATIC_TOKEN required unless --token-file is used

Modes:

    (default)  convert the credentials the workflow already uses to the static
               token; no workflow version change
    --rebind   create/update CREDENTIAL_NAME and point every HubSpot node at it
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path

_HERE = Path(__file__).resolve()
for candidate in (_HERE.parents[1] / "backend", _HERE.parents[1], Path("/app"), Path("/app/backend")):
    if (candidate / "app").is_dir() and str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from app.credentials.service import create_for_user, update_for_user
from app.db import get_session
from app.models import Credential, WorkflowRecord, WorkflowVersionRecord
from app.schemas.workflow import Workflow
from sqlalchemy import select

DEFAULT_NAME = "HubSpot Production Sync (static app)"


def _token_from_args(args: argparse.Namespace) -> str:
    if args.token_file:
        return Path(args.token_file).read_text(encoding="utf-8").strip()
    return (os.environ.get("HUBSPOT_STATIC_TOKEN") or "").strip()


def _hubspot_credential_ids(data: dict) -> set[str]:
    ids: set[str] = set()
    for node in data.get("nodes") or []:
        if node.get("type") != "hubspot":
            continue
        credential_id = str((node.get("credentials") or {}).get("hubspot") or "").strip()
        if credential_id:
            ids.add(credential_id)
    return ids


def _rewrite_workflow(data: dict, credential_id: str) -> tuple[dict, int]:
    updated = json.loads(json.dumps(data))
    count = 0
    for node in updated.get("nodes") or []:
        if node.get("type") != "hubspot":
            continue
        credentials = dict(node.get("credentials") or {})
        credentials["hubspot"] = credential_id
        node["credentials"] = credentials
        count += 1
    return updated, count


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="persist the changes")
    parser.add_argument("--token-file", default="", help="read the static token from this path")
    parser.add_argument("--rebind", action="store_true", help="point every HubSpot node at CREDENTIAL_NAME")
    args = parser.parse_args()

    token = _token_from_args(args)
    if not token:
        print("HUBSPOT_STATIC_TOKEN (or --token-file) is required.", file=sys.stderr)
        return 2

    db = get_session()
    try:
        target_workflow_id = (os.environ.get("WORKFLOW_ID") or "").strip()
        user_id = int(os.environ.get("USER_ID") or 0) or None

        if target_workflow_id and not user_id:
            target = db.get(WorkflowRecord, target_workflow_id)
            if target is None:
                print(f"workflow not found: {target_workflow_id}", file=sys.stderr)
                return 1
            user_id = target.user_id

        workflows = list(
            db.scalars(
                select(WorkflowRecord).where(
                    WorkflowRecord.deleted_at.is_(None),
                    *([WorkflowRecord.id == target_workflow_id] if target_workflow_id else []),
                    *([WorkflowRecord.user_id == user_id] if user_id else []),
                )
            ).all()
        )
        workflows = [
            w for w in workflows
            if any(n.get("type") == "hubspot" for n in (w.data or {}).get("nodes", []))
        ]
        if not workflows:
            print("No workflows with HubSpot nodes found.", file=sys.stderr)
            return 1
        if not user_id:
            user_id = workflows[0].user_id

        referenced = sorted({cid for w in workflows for cid in _hubspot_credential_ids(w.data or {})})
        if not referenced:
            print("HubSpot nodes have no credential id.", file=sys.stderr)
            return 1

        print(f"owner={user_id} workflows={len(workflows)} credentials={len(referenced)}")

        if not args.rebind:
            credentials = list(
                db.scalars(
                    select(Credential).where(
                        Credential.user_id == user_id,
                        Credential.id.in_(referenced),
                    )
                ).all()
            )
            found = {c.id for c in credentials}
            missing = [cid for cid in referenced if cid not in found]
            if missing:
                print(f"credentials not found for owner: {', '.join(missing)}", file=sys.stderr)
                return 1
            for credential in credentials:
                if credential.type != "hubspot":
                    print(f"{credential.id} is type {credential.type!r}, refusing to convert", file=sys.stderr)
                    return 1
                print(f"  convert {credential.id} ({credential.name}) to a private token")
            if not args.apply:
                print("dry run only; pass --apply to persist")
                return 0
            for credential in credentials:
                update_for_user(
                    db,
                    user_id,
                    credential.id,
                    data={"private_token": token, "oauth": False},
                )
            print("done; workflows were not modified")
            return 0

        name = (os.environ.get("CREDENTIAL_NAME") or DEFAULT_NAME).strip()
        existing = db.scalar(
            select(Credential).where(
                Credential.user_id == user_id,
                Credential.type == "hubspot",
                Credential.name == name,
            )
        )
        if not args.apply:
            print(f"dry run only; would create/update {name!r} and rebind")
            for w in workflows:
                count = sum(1 for n in (w.data or {}).get("nodes", []) if n.get("type") == "hubspot")
                print(f"  would update {w.id} ({w.name}) v{w.version}: {count} HubSpot nodes")
            return 0

        if existing is None:
            meta = create_for_user(db, user_id, name, "hubspot", {"private_token": token})
        else:
            meta = update_for_user(
                db, user_id, existing.id, data={"private_token": token, "oauth": False}
            )
        credential_id = meta["id"]
        print(f"credential id={credential_id}")

        for w in workflows:
            new_data, count = _rewrite_workflow(w.data or {}, credential_id)
            if not count:
                continue
            wf = Workflow.model_validate(new_data)
            w.name = wf.name
            w.data = wf.model_dump(mode="json")
            w.version = int(w.version or 1) + 1
            db.query(WorkflowVersionRecord).filter(
                WorkflowVersionRecord.workflow_id == w.id,
                WorkflowVersionRecord.version != w.version,
            ).update({"is_active": False})
            db.add(WorkflowVersionRecord(
                id=f"ver_{uuid.uuid4().hex[:12]}",
                workflow_id=w.id,
                workspace_id=w.workspace_id,
                version=w.version,
                data=w.data,
                user_id=w.user_id,
                is_active=True,
            ))
            print(f"  updated {w.id} -> v{w.version}: {count} HubSpot nodes")

        db.commit()
        print("done")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
