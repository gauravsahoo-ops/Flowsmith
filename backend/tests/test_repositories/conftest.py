"""Repository tests: plain SQLAlchemy sessions, no FastAPI/TestClient."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy.orm import Session


@pytest.fixture
def db() -> Iterator[Session]:
    """Session for a repository test (the suite truncates tables per test)."""
    from app.db import get_session

    session = get_session()
    try:
        yield session
    finally:
        session.close()
