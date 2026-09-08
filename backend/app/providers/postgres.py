"""PostgreSQL provider client (Phase 11 business connectors).

SQLAlchemy Core over a credential DSN; scheme allowlist stops a Postgres
credential reaching other engines. All work runs off the event loop.
"""

from __future__ import annotations

from app.providers.sql_provider import SQLProviderClient


class PostgresProviderClient(SQLProviderClient):
    credential_type = "postgres"
    product_name = "PostgreSQL"
    allowed_dsn_prefixes = ("postgresql://", "postgresql+psycopg2://", "postgresql+psycopg://", "postgres://")
