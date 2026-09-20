"""add_inbound_triage_items

Revision ID: a1b2c3d4e5f6
Revises: f5957d37d730
Create Date: 2026-09-20 11:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'f5957d37d730'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'inbound_triage_items',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('source', sa.String(length=50), nullable=False, server_default='GMAIL_WORKER'),
        sa.Column('sender', sa.String(length=255), nullable=False),
        sa.Column('recipient', sa.String(length=255), nullable=True),
        sa.Column('subject', sa.String(length=500), nullable=False),
        sa.Column('raw_body', sa.Text(), nullable=False),
        sa.Column('detected_company', sa.String(length=255), nullable=True),
        sa.Column('detected_role', sa.String(length=255), nullable=True),
        sa.Column('suggested_stage', sa.String(length=50), nullable=True),
        sa.Column('resolution_confidence', sa.String(length=20), nullable=False, server_default='AMBIGUOUS'),
        sa.Column('resolution_note', sa.Text(), nullable=True),
        sa.Column('candidate_application_ids', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='[]'),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='PENDING'),
        sa.Column('resolved_application_id', sa.UUID(), nullable=True),
        sa.Column('resolved_stage', sa.String(length=50), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['resolved_application_id'], ['applications.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_inbound_triage_status', 'inbound_triage_items', ['status'], unique=False)
    op.create_index('idx_inbound_triage_created', 'inbound_triage_items', [sa.literal_column('created_at DESC')], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('idx_inbound_triage_created', table_name='inbound_triage_items')
    op.drop_index('idx_inbound_triage_status', table_name='inbound_triage_items')
    op.drop_table('inbound_triage_items')
