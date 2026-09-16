"""Drop redundant files.object_key unique constraint.

Revision ID: d2e6f8a0b1c3
Revises: c9d4e5f6a7b8
Create Date: 2026-09-16 00:00:00.000000

Migration 7c2d9e4b1af3 declared inline unique=True on object_key AND an
explicit unique ix_files_object_key, leaving two unique enforcements
(backing indexes files_object_key_key + ix_files_object_key). The model
renders a single unique ix_files_object_key. Drop the redundant
constraint; uniqueness stays enforced by ix_files_object_key.
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'd2e6f8a0b1c3'
down_revision: Union[str, Sequence[str], None] = 'c9d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint('files_object_key_key', 'files', type_='unique')


def downgrade() -> None:
    op.create_unique_constraint('files_object_key_key', 'files', ['object_key'])
