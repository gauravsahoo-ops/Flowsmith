"""workflow_tests (Phase 14: first-class workflow testing)

Revision ID: b51d7c8a90f2
Revises: c28f54193584
Create Date: 2026-08-25 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b51d7c8a90f2'
down_revision: Union[str, Sequence[str], None] = 'c28f54193584'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('workflow_tests',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('workflow_id', sa.String(length=64), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=160), nullable=False),
    sa.Column('test_data', sa.JSON(), nullable=True),
    sa.Column('mocks', sa.JSON(), nullable=True),
    sa.Column('assertions', sa.JSON(), nullable=True),
    sa.Column('expected_outputs', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['workflow_id'], ['workflows.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_workflow_tests_workflow_id'), 'workflow_tests', ['workflow_id'], unique=False)
    op.create_index(op.f('ix_workflow_tests_user_id'), 'workflow_tests', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_workflow_tests_user_id'), table_name='workflow_tests')
    op.drop_index(op.f('ix_workflow_tests_workflow_id'), table_name='workflow_tests')
    op.drop_table('workflow_tests')
