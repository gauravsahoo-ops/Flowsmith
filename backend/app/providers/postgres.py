"""PostgreSQL provider client (Phase 11 business connectors).

SQLAlchemy Core over a credential DSN; scheme allowlist stops a Postgres
credential reaching other engines. All work runs off the event loop.
"""

from __future__ import annotations

from app.providers.sql_provider import PostgresProviderClient

__all__ = ["PostgresProviderClient"]
