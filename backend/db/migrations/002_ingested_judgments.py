"""SC Judgments audit table — Neethi AI

Creates the ingested_judgments table that serves as both the deduplication
registry and the audit trail for the Vanga S3 SC judgment ingestion pipeline.

Every judgment processed by sc_judgment_ingester.py has exactly one row here
(enforced by UNIQUE(diary_no)). The row tracks:
  - Vanga metadata (case_no, case_name, year, decision_date, disposal_nature)
  - Qdrant point IDs for all chunks of this judgment
  - Indian Kanoon URL enrichment status (ik_url, ik_resolved_at)
  - Ingestion quality flags (pdf_hash, ocr_required)

Revision ID: 002_ingested_judgments
Depends on:  001_initial_legal_schema
Create Date: 2026-02-22
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers used by Alembic
revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ingested_judgments",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        # Primary deduplication key — eCourts internal filing number
        sa.Column("diary_no", sa.String(50), nullable=False),
        # Formal case number (e.g. "C.A. No.-004292-004292 - 2002")
        # NOT an AIR/SCC citation — those fields are absent from Vanga data
        sa.Column("case_no", sa.String(200)),
        # "Petitioner v. Respondent" display name
        sa.Column("case_name", sa.Text()),
        # Year partition key from Vanga S3 (reliable, unlike judgment_dates field)
        sa.Column("year", sa.Integer(), nullable=False),
        # Decision date after century-bug correction (+100 years where year < 1950 and partition_year > 1993)
        sa.Column("decision_date", sa.Date()),
        # From Vanga Parquet disposal_nature field
        # e.g. "Dismissed", "Allowed", "Bail Granted", "Conviction Upheld"
        sa.Column("disposal_nature", sa.String(100)),
        # Inferred from case_no prefix: C.A.→civil, Crl.A.→criminal, W.P.→constitutional
        sa.Column("legal_domain", sa.String(50)),
        # JSONB array of all Qdrant chunk point UUIDs for this judgment
        # uuid5(NAMESPACE_URL, f"{diary_no}__chunk{idx}") for each chunk
        sa.Column("qdrant_point_ids", postgresql.JSONB()),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        # Indian Kanoon URL — stored as empty string until enrichment pass
        # Back-filled without re-embedding: SET ik_url = '...', ik_resolved_at = NOW()
        sa.Column("ik_url", sa.Text(), nullable=False, server_default="''"),
        # Indian Kanoon internal doc ID — no mathematical relationship to diary_no
        sa.Column("ik_tid", sa.Integer()),
        # NULL = not yet enriched. Partial index makes enrichment queries O(log n).
        sa.Column("ik_resolved_at", sa.TIMESTAMP(timezone=True)),
        sa.Column(
            "ingested_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
        ),
        # SHA-256 of source PDF — enables change detection on re-ingestion
        sa.Column("pdf_hash", sa.String(64)),
        # True if PyMuPDF text extraction returned < 200 chars on multi-page PDF
        sa.Column("ocr_required", sa.Boolean(), nullable=False, server_default="false"),
        # Primary deduplication constraint
        sa.UniqueConstraint("diary_no", name="uq_ingested_judgments_diary_no"),
    )

    # Standard indexes for common filter patterns
    op.create_index("idx_ingested_year", "ingested_judgments", ["year"])
    op.create_index("idx_ingested_disposal", "ingested_judgments", ["disposal_nature"])

    # Partial index: efficiently finds records not yet enriched with IK URL
    # Query: SELECT * FROM ingested_judgments WHERE ik_resolved_at IS NULL
    op.create_index(
        "idx_ingested_ik_unresolved",
        "ingested_judgments",
        ["ik_resolved_at"],
        postgresql_where=sa.text("ik_resolved_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_table("ingested_judgments")
