"""Code validation endpoint for Code node."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.auth import get_current_user
from app.api.common import ok
from app.models import User

router = APIRouter(prefix="/api/nodes/code", tags=["code"])

class ValidateRequest(BaseModel):
    code: str
    language: str = "javascript"

class ValidateResponse(BaseModel):
    valid: bool
    message: str | None = None
    line: int | None = None
    column: int | None = None

@router.post("/validate")
def validate_code(body: ValidateRequest, user: User = Depends(get_current_user)) -> dict:
    from app.nodes.code import _validate_syntax
    is_valid, msg, line, col = _validate_syntax(body.code, body.language)
    if is_valid:
        return ok({"valid": True, "message": "Code is valid", "line": None, "column": None})
    else:
        return ok({"valid": False, "message": msg, "line": line, "column": col})
