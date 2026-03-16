"""Add conversation_sessions table.

Revision ID: 003
Create Date: 2026-03-16
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "003"
down_revision = None  # Update to previous migration if one exists
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversation_sessions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("session_id", sa.String(64), unique=True, nullable=False, index=True),
        sa.Column("context", JSONB, server_default=sa.text("'{}'::jsonb")),
        sa.Column("intent_history", JSONB, server_default=sa.text("'[]'::jsonb")),
        sa.Column("turn_count", sa.Integer, server_default=sa.text("0")),
        sa.Column("status", sa.String(20), server_default=sa.text("'active'")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("conversation_sessions")
