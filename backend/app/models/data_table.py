"""Data Tables models: table metadata, column definitions, rows (JSONB)."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

if TYPE_CHECKING:
    from app.models import User, Workspace


class DataTable(Base):
    __tablename__ = "data_tables"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(64), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    workspace: Mapped["Workspace"] = relationship()
    user: Mapped["User"] = relationship()
    columns: Mapped[list["DataTableColumn"]] = relationship(back_populates="table", cascade="all, delete-orphan", order_by="DataTableColumn.position")
    rows: Mapped[list["DataTableRow"]] = relationship(back_populates="table", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("workspace_id", "name", name="uq_data_table_workspace_name"),
    )


class DataTableColumn(Base):
    __tablename__ = "data_table_columns"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    table_id: Mapped[str] = mapped_column(String(64), ForeignKey("data_tables.id", ondelete="CASCADE"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(String(32), nullable=False)  # string|number|boolean|date|datetime|json
    required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    default_value: Mapped[str | None] = mapped_column(Text, nullable=True)  # stored as JSON string or raw
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    table: Mapped["DataTable"] = relationship(back_populates="columns")

    __table_args__ = (
        UniqueConstraint("table_id", "name", name="uq_column_table_name"),
    )


class DataTableRow(Base):
    __tablename__ = "data_table_rows"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    table_id: Mapped[str] = mapped_column(String(64), ForeignKey("data_tables.id", ondelete="CASCADE"), index=True, nullable=False)
    data: Mapped[dict] = mapped_column(JSON, nullable=False)  # {col_name: value}
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    table: Mapped["DataTable"] = relationship(back_populates="rows")
