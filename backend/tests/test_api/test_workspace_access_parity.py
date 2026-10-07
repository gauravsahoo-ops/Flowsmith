"""Parity tests for workspace access checks (audit step 3).

The same user+workspace pair must produce identical view/edit answers no
matter which module performs the check: access.py (source of truth),
files.py, workspaces._require_ws_member, and the RAG access resolver.
"""

from __future__ import annotations

import pytest

from app.api.access import workspace_can_edit, workspace_can_view
from app.api.files import _can_access_workspace
from app.api.workspaces import _require_ws_member
from app.db import get_session
from app.models import (
    Organization,
    OrganizationMember,
    User,
    Workspace,
    WorkspaceMember,
)
from app.rag import RagAccess, _resolve_access


@pytest.fixture()
def scenario():
    """Seed one org+workspace and users with distinct grants.

    - creator: workspace creator, deliberately NO member row
    - viewer:  workspace member, role=member/permission=view
    - editor:  workspace member, role=editor/permission=edit
    - org_member:  org role=member (no workspace row)
    - org_founder: org role=founder (no workspace row)
    - outsider: neither org nor workspace member
    """
    db = get_session()
    users = {
        key: User(email=f"parity_{key}@test.com", password_hash="x")
        for key in ("creator", "viewer", "editor", "org_member", "org_founder", "outsider")
    }
    db.add_all(users.values())
    db.flush()

    org = Organization(
        id="org_parity",
        name="Parity Org",
        founder_id=users["creator"].id,
        is_public=False,
    )
    db.add(org)
    db.flush()

    ws = Workspace(
        id="ws_parity",
        name="Parity WS",
        organization_id=org.id,
        creator_id=users["creator"].id,
    )
    db.add(ws)
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=users["viewer"].id, role="member", permission="view"))
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=users["editor"].id, role="editor", permission="edit"))
    db.add(OrganizationMember(organization_id=org.id, user_id=users["org_member"].id, role="member", permission="view"))
    db.add(OrganizationMember(organization_id=org.id, user_id=users["org_founder"].id, role="founder", permission="view"))
    db.commit()

    yield db, users, ws.id
    db.close()


CASES = [
    ("creator", "creator", True, True),
    ("ws-viewer", "viewer", True, False),
    ("ws-editor", "editor", True, True),
    ("org-member", "org_member", True, False),
    ("org-founder", "org_founder", True, True),
    ("outsider", "outsider", False, False),
]


@pytest.mark.parametrize("label,user_key,expect_view,expect_edit", CASES, ids=[c[0] for c in CASES])
def test_workspace_permission_parity(label, user_key, expect_view, expect_edit, scenario):
    db, users, ws_id = scenario
    user = users[user_key]

    # access.py: source of truth
    assert workspace_can_view(db, ws_id, user.id) is expect_view
    assert workspace_can_edit(db, ws_id, user.id) is expect_edit

    # files.py delegates to the same rules
    assert _can_access_workspace(db, user.id, ws_id) is expect_view
    assert _can_access_workspace(db, user.id, ws_id, need_edit=True) is expect_edit

    # workspaces.py view wrapper (workspace exists here => bool branch)
    assert _require_ws_member(db, ws_id, user) is expect_view

    # RAG resolver fills equivalent membership sets
    access = RagAccess(user_id=user.id)
    _resolve_access(db, access)
    assert (ws_id in access.readable_workspaces) is expect_view
    assert (ws_id in access.editable_workspaces) is expect_edit


def test_files_no_workspace_grants_nothing(scenario):
    """A missing workspace must never grant access (personal files are
    owner-scoped; callers check owner_user_id explicitly)."""
    db, users, _ws_id = scenario
    assert _can_access_workspace(db, users["creator"].id, None) is False
    assert _can_access_workspace(db, users["creator"].id, None, need_edit=True) is False
