"""workflow auth state (auth fetch/store lifecycle)

Revision ID: b7e2a4f6c8d1
Revises: a1b2c3d4e5f6
Create Date: 2026-09-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7e2a4f6c8d1'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('workflow_auth_state',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('workflow_id', sa.String(length=64), nullable=False),
    sa.Column('provider', sa.String(length=64), nullable=False),
    sa.Column('data', sa.LargeBinary(), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_validated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('last_error', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['workflow_id'], ['workflows.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('workflow_id', 'provider', name='uq_workflow_auth_state_wf_provider')
    )
    op.create_index(op.f('ix_workflow_auth_state_workflow_id'), 'workflow_auth_state', ['workflow_id'], unique=False)
    op.create_index(op.f('ix_workflow_auth_state_provider'), 'workflow_auth_state', ['provider'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_workflow_auth_state_provider'), table_name='workflow_auth_state')
    op.drop_index(op.f('ix_workflow_auth_state_workflow_id'), table_name='workflow_auth_state')
    op.drop_table('workflow_auth_state')
