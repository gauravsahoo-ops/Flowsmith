"""Authenticated in-app documentation endpoints.

Only user-facing manuals are served here. Source code, repository metadata,
administrator secrets, and deployment files remain outside the HTTP surface.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import PlainTextResponse

from app.api.auth import get_current_user
from app.models import User

router = APIRouter(prefix="/api/help", tags=["help"])

_MANUAL_CANDIDATES = (
    Path("/app/USER_MANUAL.md"),
    Path("/app/docs/USER_MANUAL.md"),
    Path(__file__).resolve().parents[3] / "USER_MANUAL.md",
    Path(__file__).resolve().parents[2] / "USER_MANUAL.md",
)


def _manual_path() -> Path | None:
    for candidate in _MANUAL_CANDIDATES:
        if candidate.is_file():
            return candidate
    return None


@router.get("/user-manual", response_class=PlainTextResponse)
def user_manual(user: User = Depends(get_current_user)) -> PlainTextResponse:
    """Return the current user manual as Markdown for authenticated users."""
    path = _manual_path()
    if path is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "The user manual is not installed in this deployment.",
        )
    return PlainTextResponse(
        path.read_text(encoding="utf-8"),
        media_type="text/markdown; charset=utf-8",
        headers={"Cache-Control": "private, no-store"},
    )
