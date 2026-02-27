"""Initial legal schema — Neethi AI

Creates the complete PostgreSQL schema for Indian legal domain data.

Revision ID: 001_initial_legal_schema
Create Date: 2026-02-19

Tables created:
    acts, chapters, sections, sub_sections,
    law_transition_mappings, cross_references,
    extraction_audit, human_review_queue
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers used by Alembic
revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # acts
    # ------------------------------------------------------------------
    op.create_table(
        "acts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("act_code", sa.String(20), nullable=False),
        sa.Column("act_name", sa.String(200), nullable=False),
        sa.Column("act_name_hindi", sa.String(200)),
        sa.Column("short_name", sa.String(50)),
        sa.Column("act_number", sa.Integer()),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("effective_date", sa.Date()),
        sa.Column("repealed_date", sa.Date()),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("era", sa.String(30), nullable=False),
        sa.Column("replaces_act_code", sa.String(20)),
        sa.Column("domain", sa.String(50)),
        sa.Column("total_sections", sa.Integer()),
        sa.Column("total_chapters", sa.Integer()),
        sa.Column("gazette_reference", sa.String(200)),
        sa.Column("source_url", sa.Text()),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
        ),
        sa.UniqueConstraint("act_code", name="uq_acts_code"),
        sa.ForeignKeyConstraint(["replaces_act_code"], ["acts.act_code"]),
        sa.CheckConstraint(
            "status IN ('active', 'repealed', 'amended', 'notified')",
            name="ck_acts_status",
        ),
        sa.CheckConstraint(
            "era IN ('colonial_codes', 'naveen_sanhitas', 'constitutional', 'other')",
            name="ck_acts_era",
        ),
        sa.CheckConstraint(
            "domain IN ('criminal_substantive', 'criminal_procedure', 'evidence', 'civil', 'constitutional') OR domain IS NULL",
            name="ck_acts_domain",
        ),
    )

    # ------------------------------------------------------------------
    # chapters
    # ------------------------------------------------------------------
    op.create_table(
        "chapters",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "act_code",
            sa.String(20),
            sa.ForeignKey("acts.act_code", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chapter_number", sa.String(10), nullable=False),
        sa.Column("chapter_number_int", sa.Integer(), nullable=False),
        sa.Column("chapter_title", sa.String(300), nullable=False),
        sa.Column("sections_range", sa.String(30)),
        sa.Column("domain", sa.String(100)),
        sa.Column("section_count", sa.Integer()),
        sa.UniqueConstraint("act_code", "chapter_number", name="uq_chapters_act_number"),
    )
    op.create_index("idx_chapters_act_code", "chapters", ["act_code"])
    op.create_index("idx_chapters_int_order", "chapters", ["act_code", "chapter_number_int"])

    # ------------------------------------------------------------------
    # sections  (central table)
    # ------------------------------------------------------------------
    op.create_table(
        "sections",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "act_code",
            sa.String(20),
            sa.ForeignKey("acts.act_code", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chapter_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("chapters.id")),
        # CRITICAL: VARCHAR not INT — section numbers include letters ('53A', '124A')
        sa.Column("section_number", sa.String(20), nullable=False),
        sa.Column("section_number_int", sa.Integer()),
        sa.Column("section_number_suffix", sa.String(5)),
        sa.Column("section_title", sa.String(500)),
        sa.Column("section_title_hindi", sa.String(500)),
        # The single most important field — zero noise, pure law text
        sa.Column("legal_text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("applicable_from", sa.Date()),
        sa.Column("applicable_until", sa.Date()),
        sa.Column("era", sa.String(30), nullable=False),
        # Offence classification
        sa.Column("is_offence", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_cognizable", sa.Boolean()),
        sa.Column("is_bailable", sa.Boolean()),
        sa.Column("triable_by", sa.String(50)),
        sa.Column("punishment_type", sa.String(100)),
        sa.Column("punishment_min_years", sa.Numeric(5, 2)),
        # 99999 = life imprisonment
        sa.Column("punishment_max_years", sa.Numeric(5, 2)),
        sa.Column("punishment_fine_max", sa.BigInteger()),
        # Source quality
        sa.Column("has_subsections", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("has_illustrations", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("has_explanations", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("has_provisos", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("extraction_confidence", sa.Float(), nullable=False, server_default="1.0"),
        # Cross-references (structured JSON, not raw text)
        sa.Column("internal_refs", postgresql.JSONB()),
        sa.Column("external_refs", postgresql.JSONB()),
        # Qdrant indexing status
        sa.Column("qdrant_indexed", sa.Boolean(), nullable=False, server_default="false"),
        # Composite unique constraint — critical for upsert safety
        sa.UniqueConstraint("act_code", "section_number", name="uq_sections_act_num"),
        sa.CheckConstraint(
            "status IN ('active', 'repealed', 'omitted', 'substituted', 'amended')",
            name="ck_sections_status",
        ),
        sa.CheckConstraint(
            "era IN ('colonial_codes', 'naveen_sanhitas', 'constitutional', 'other')",
            name="ck_sections_era",
        ),
    )
    op.create_index("idx_sections_act_code", "sections", ["act_code"])
    op.create_index("idx_sections_status", "sections", ["status"])
    op.create_index("idx_sections_era", "sections", ["era"])
    op.create_index(
        "idx_sections_is_offence", "sections", ["is_offence"],
        postgresql_where=sa.text("is_offence = TRUE"),
    )
    op.create_index(
        "idx_sections_cognizable", "sections", ["is_cognizable"],
        postgresql_where=sa.text("is_cognizable IS NOT NULL"),
    )
    op.create_index("idx_sections_qdrant_indexed", "sections", ["qdrant_indexed"])
    op.create_index(
        "idx_sections_act_num_unique", "sections", ["act_code", "section_number"], unique=True
    )

    # ------------------------------------------------------------------
    # sub_sections
    # ------------------------------------------------------------------
    op.create_table(
        "sub_sections",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "section_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("act_code", sa.String(20), nullable=False),
        sa.Column("parent_section_number", sa.String(20), nullable=False),
        sa.Column("sub_section_label", sa.String(20), nullable=False),
        sa.Column("sub_section_type", sa.String(30), nullable=False),
        sa.Column("legal_text", sa.Text(), nullable=False),
        sa.Column("position_order", sa.Integer(), nullable=False),
        sa.UniqueConstraint(
            "section_id", "sub_section_label", name="uq_sub_sections_section_label"
        ),
        sa.CheckConstraint(
            "sub_section_type IN ('numbered', 'lettered', 'explanation', 'proviso', 'illustration', 'exception')",
            name="ck_sub_sections_type",
        ),
    )
    op.create_index("idx_sub_sections_section_id", "sub_sections", ["section_id"])
    op.create_index("idx_sub_sections_act_code", "sub_sections", ["act_code"])

    # ------------------------------------------------------------------
    # law_transition_mappings  (the safety table)
    # ------------------------------------------------------------------
    op.create_table(
        "law_transition_mappings",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("old_act", sa.String(20), nullable=False),
        sa.Column("old_section", sa.String(20), nullable=False),
        sa.Column("old_section_title", sa.String(500)),
        sa.Column("new_act", sa.String(20)),
        sa.Column("new_section", sa.String(20)),
        sa.Column("new_section_title", sa.String(500)),
        sa.Column("transition_type", sa.String(20), nullable=False),
        sa.Column("transition_note", sa.Text()),
        sa.Column("scope_change", sa.String(30)),
        sa.Column("semantic_similarity", sa.Float()),
        sa.Column("gazette_reference", sa.String(300)),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("approved_by", sa.String(100)),
        sa.Column("approved_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("user_correct_votes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("user_wrong_votes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("auto_demoted", sa.Boolean(), nullable=False, server_default="false"),
        # ONLY rows with is_active=TRUE are used by StatuteNormalizationTool
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
        ),
        sa.CheckConstraint(
            "transition_type IN ('equivalent', 'modified', 'split_into', 'merged_from', 'deleted', 'new')",
            name="ck_transition_type",
        ),
        sa.CheckConstraint(
            "scope_change IN ('none', 'narrowed', 'expanded', 'restructured', 'unknown') OR scope_change IS NULL",
            name="ck_scope_change",
        ),
    )
    op.create_index("idx_transition_old", "law_transition_mappings", ["old_act", "old_section"])
    op.create_index("idx_transition_new", "law_transition_mappings", ["new_act", "new_section"])
    op.create_index(
        "idx_transition_active", "law_transition_mappings", ["is_active"],
        postgresql_where=sa.text("is_active = TRUE"),
    )

    # ------------------------------------------------------------------
    # cross_references
    # ------------------------------------------------------------------
    op.create_table(
        "cross_references",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("source_act", sa.String(20), nullable=False),
        sa.Column("source_section", sa.String(20), nullable=False),
        sa.Column("target_act", sa.String(20), nullable=False),
        sa.Column("target_section", sa.String(20), nullable=False),
        sa.Column("target_subsection", sa.String(20)),
        sa.Column("reference_text", sa.Text()),
        sa.Column("reference_type", sa.String(30)),
        sa.Column("extraction_method", sa.String(30)),
        sa.CheckConstraint(
            "reference_type IN ('definition_import', 'subject_to', 'procedure_link', "
            "'punishment_table', 'exception_reference', 'cross_act_reference') OR reference_type IS NULL",
            name="ck_cross_ref_type",
        ),
    )
    op.create_index("idx_xref_source", "cross_references", ["source_act", "source_section"])
    op.create_index("idx_xref_target", "cross_references", ["target_act", "target_section"])

    # ------------------------------------------------------------------
    # extraction_audit
    # ------------------------------------------------------------------
    op.create_table(
        "extraction_audit",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("section_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sections.id")),
        sa.Column("act_code", sa.String(20), nullable=False),
        sa.Column("section_number", sa.String(20), nullable=False),
        sa.Column("pipeline_version", sa.String(50)),
        sa.Column("checks_run", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("checks_passed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("check_failures", postgresql.JSONB()),
        sa.Column("extraction_confidence", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("noise_types_found", postgresql.JSONB()),
        sa.Column("raw_text_length", sa.Integer()),
        sa.Column("cleaned_text_length", sa.Integer()),
        sa.Column("requires_human_review", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index("idx_audit_act_section", "extraction_audit", ["act_code", "section_number"])
    op.create_index("idx_audit_confidence", "extraction_audit", ["extraction_confidence"])

    # ------------------------------------------------------------------
    # human_review_queue
    # ------------------------------------------------------------------
    op.create_table(
        "human_review_queue",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("section_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sections.id")),
        sa.Column("act_code", sa.String(20), nullable=False),
        sa.Column("section_number", sa.String(20), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("raw_text", sa.Text()),
        sa.Column("cleaned_text", sa.Text()),
        sa.Column("extraction_confidence", sa.Float(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("reviewed_by", sa.String(100)),
        sa.Column("reviewed_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("review_notes", sa.Text()),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'needs_reextraction')",
            name="ck_review_status",
        ),
    )
    op.create_index("idx_review_status", "human_review_queue", ["status"])
    op.create_index("idx_review_act", "human_review_queue", ["act_code"])


def downgrade() -> None:
    op.drop_table("human_review_queue")
    op.drop_table("extraction_audit")
    op.drop_table("cross_references")
    op.drop_table("law_transition_mappings")
    op.drop_table("sub_sections")
    op.drop_table("sections")
    op.drop_table("chapters")
    op.drop_table("acts")
