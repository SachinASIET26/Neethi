"""Add staged pipeline columns to conversation_sessions.

Revision ID: 004
Create Date: 2026-03-21

Adds columns for the conversational staged pipeline:
- stage: current pipeline stage (intake/clarifying/confirming/retrieving/responding/follow_up)
- formulated_query: LLM-reformulated legal query
- classified_domain: legal domain classification
- retrieved_sections_cache: cached retrieved sections (JSONB)
- clarification_round: number of clarification rounds completed
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "conversation_sessions",
        sa.Column("stage", sa.String(20), server_default=sa.text("'intake'"))
    )
    op.add_column(
        "conversation_sessions",
        sa.Column("formulated_query", sa.Text, nullable=True)
    )
    op.add_column(
        "conversation_sessions",
        sa.Column("classified_domain", sa.String(50), nullable=True)
    )
    op.add_column(
        "conversation_sessions",
        sa.Column("retrieved_sections_cache", JSONB, nullable=True)
    )
    op.add_column(
        "conversation_sessions",
        sa.Column("clarification_round", sa.Integer, server_default=sa.text("0"))
    )


def downgrade() -> None:
    op.drop_column("conversation_sessions", "clarification_round")
    op.drop_column("conversation_sessions", "retrieved_sections_cache")
    op.drop_column("conversation_sessions", "classified_domain")
    op.drop_column("conversation_sessions", "formulated_query")
    op.drop_column("conversation_sessions", "stage")
