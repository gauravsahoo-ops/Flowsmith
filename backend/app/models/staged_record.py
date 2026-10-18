"""Staged contact record model for CSV and Salesforce batch/bulk processing."""

from __future__ import annotations

from datetime import datetime
from sqlalchemy import JSON, BigInteger, DateTime, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class StagedContactRecord(Base):
    __tablename__ = "staged_contacts"
    __table_args__ = (
        Index("ix_staged_contacts_exec_status", "execution_id", "status"),
        Index("ix_staged_contacts_exec_row", "execution_id", "row_number"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    execution_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    row_number: Mapped[int] = mapped_column(BigInteger, nullable=False)
    first_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    phone: Mapped[str | None] = mapped_column(String(100), nullable=True)
    department: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mailing_street: Mapped[str | None] = mapped_column(Text, nullable=True)
    mailing_city: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mailing_state: Mapped[str | None] = mapped_column(String(100), nullable=True)
    mailing_postal_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    mailing_country: Mapped[str | None] = mapped_column(String(100), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="staged", index=True, nullable=False)
    salesforce_id: Mapped[str | None] = mapped_column(String(50), index=True, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
