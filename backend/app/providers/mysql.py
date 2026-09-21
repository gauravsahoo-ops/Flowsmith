"""MySQL provider client (Phase 11 business connectors).

SQLAlchemy Core over a credential DSN (pymysql driver); scheme allowlist
keeps MySQL credentials on MySQL servers. All work runs off the event
loop via asyncio.to_thread.
"""

from __future__ import annotations

from app.providers.sql_provider import MySQLProviderClient

__all__ = ["MySQLProviderClient"]
