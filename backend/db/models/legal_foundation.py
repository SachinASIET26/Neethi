"""SQLAlchemy async models for the Neethi AI legal data foundation.

These models define the complete PostgreSQL schema for all Indian legal domain data,
covering Acts, Chapters, Sections, Sub-sections, Law Transition Mappings, Cross-References,
and operational quality/audit tables.

Design principles:
- All PKs are UUID generated server-side via gen_random_uuid()
- section_number is VARCHAR, not INT (handles '53A', '124A' etc.)
- chapter_number stored as VARCHAR Roman numeral; chapter_number_int as INT for ordering
- All timestamps are TIMESTAMPTZ (timezone-aware)
- SQLAlchemy 2.0 async style with AsyncAttrs mixin
"""

import uuid
from datetime import date, datetime
from typing import List, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func, text as sa_text
from sqlalchemy import TIMESTAMP


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------

class Base(AsyncAttrs, DeclarativeBase):
    """Shared declarative base with async attribute support."""
    pass


# ---------------------------------------------------------------------------
# Act
# ---------------------------------------------------------------------------

class Act(Base):
    """Root table. Every section, chapter, and transition mapping is a child of a row here.

    act_code is the canonical short identifier used as a foreign key throughout the system.
    Values: 'BNS_2023', 'BNSS_2023', 'BSA_2023', 'IPC_1860', 'CrPC_1973', 'IEA_1872'.
    """

    __tablename__ = "acts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    act_code: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    act_name: Mapped[str] = mapped_column(String(200), nullable=False)
    act_name_hindi: Mapped[Optional[str]] = mapped_column(String(200))
    short_name: Mapped[Optional[str]] = mapped_column(String(50))
    act_number: Mapped[Optional[int]] = mapped_column(Integer)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    effective_date: Mapped[Optional[date]] = mapped_column(Date)
    repealed_date: Mapped[Optional[date]] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="active")
    era: Mapped[str] = mapped_column(String(30), nullable=False)
    replaces_act_code: Mapped[Optional[str]] = mapped_column(
        String(20), ForeignKey("acts.act_code")
    )
    domain: Mapped[Optional[str]] = mapped_column(String(50))
    total_sections: Mapped[Optional[int]] = mapped_column(Integer)
    total_chapters: Mapped[Optional[int]] = mapped_column(Integer)
    gazette_reference: Mapped[Optional[str]] = mapped_column(String(200))
    source_url: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'repealed', 'amended', 'notified')",
            name="ck_acts_status",
        ),
        CheckConstraint(
            "era IN ('colonial_codes', 'naveen_sanhitas', 'constitutional', 'other')",
            name="ck_acts_era",
        ),
        CheckConstraint(
            "domain IN ('criminal_substantive', 'criminal_procedure', 'evidence', 'civil', 'constitutional') OR domain IS NULL",
            name="ck_acts_domain",
        ),
    )

    # Relationships
    chapters: Mapped[List["Chapter"]] = relationship(
        "Chapter", back_populates="act", cascade="all, delete-orphan"
    )
    sections: Mapped[List["Section"]] = relationship(
        "Section", back_populates="act", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# Chapter
# ---------------------------------------------------------------------------

class Chapter(Base):
    """Chapter groupings within an Act.

    chapter_number is ALWAYS stored as a Roman numeral string ('I', 'II', 'III').
    chapter_number_int holds the Arabic equivalent for ORDER BY operations.
    This resolves the BNS/BNSS inconsistency found in the source JSON files.
    """

    __tablename__ = "chapters"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    act_code: Mapped[str] = mapped_column(
        String(20), ForeignKey("acts.act_code", ondelete="CASCADE"), nullable=False
    )
    chapter_number: Mapped[str] = mapped_column(String(10), nullable=False)
    chapter_number_int: Mapped[int] = mapped_column(Integer, nullable=False)
    chapter_title: Mapped[str] = mapped_column(String(300), nullable=False)
    sections_range: Mapped[Optional[str]] = mapped_column(String(30))
    domain: Mapped[Optional[str]] = mapped_column(String(100))
    section_count: Mapped[Optional[int]] = mapped_column(Integer)

    __table_args__ = (
        UniqueConstraint("act_code", "chapter_number", name="uq_chapters_act_number"),
    )

    # Relationships
    act: Mapped["Act"] = relationship("Act", back_populates="chapters")
    sections: Mapped[List["Section"]] = relationship("Section", back_populates="chapter")


# ---------------------------------------------------------------------------
# Section  (central table — most important in the system)
# ---------------------------------------------------------------------------

class Section(Base):
    """The central table. Every agent, citation verification, and statute normalization
    lookup ultimately traces back to a row here.

    CRITICAL: section_number is VARCHAR(20), NOT INT.
    Indian law section numbers include letters: '53A', '124A', '438A'.
    Storing as INT would silently corrupt these identifiers.

    punishment_max_years: 99999 represents life imprisonment.
    Do NOT use a sentinel string for this — use the integer constant.
    """

    __tablename__ = "sections"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    act_code: Mapped[str] = mapped_column(
        String(20), ForeignKey("acts.act_code", ondelete="CASCADE"), nullable=False
    )
    chapter_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chapters.id")
    )

    # Section identity
    section_number: Mapped[str] = mapped_column(String(20), nullable=False)
    section_number_int: Mapped[Optional[int]] = mapped_column(Integer)
    section_number_suffix: Mapped[Optional[str]] = mapped_column(String(5))
    section_title: Mapped[Optional[str]] = mapped_column(String(500))
    section_title_hindi: Mapped[Optional[str]] = mapped_column(String(500))

    # THE single most important field in the system.
    # Zero noise — exactly what a lawyer reads in the Gazette.
    legal_text: Mapped[str] = mapped_column(Text, nullable=False)

    # Temporal fields
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="active")
    applicable_from: Mapped[Optional[date]] = mapped_column(Date)
    applicable_until: Mapped[Optional[date]] = mapped_column(Date)
    era: Mapped[str] = mapped_column(String(30), nullable=False)

    # Offence classification (populated for criminal law sections only)
    is_offence: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    is_cognizable: Mapped[Optional[bool]] = mapped_column(Boolean)
    is_bailable: Mapped[Optional[bool]] = mapped_column(Boolean)
    triable_by: Mapped[Optional[str]] = mapped_column(String(50))
    punishment_type: Mapped[Optional[str]] = mapped_column(String(100))
    punishment_min_years: Mapped[Optional[int]] = mapped_column(Integer)
    punishment_max_years: Mapped[Optional[int]] = mapped_column(Integer)
    punishment_fine_max: Mapped[Optional[int]] = mapped_column(BigInteger)

    # Source quality flags
    has_subsections: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    has_illustrations: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    has_explanations: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    has_provisos: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    extraction_confidence: Mapped[float] = mapped_column(Float, nullable=False, server_default="1.0")

    # Cross-reference tracking (structured, not raw text)
    internal_refs: Mapped[Optional[dict]] = mapped_column(JSONB)
    external_refs: Mapped[Optional[dict]] = mapped_column(JSONB)

    # Qdrant indexing status
    qdrant_indexed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    __table_args__ = (
        UniqueConstraint("act_code", "section_number", name="uq_sections_act_num"),
        CheckConstraint(
            "status IN ('active', 'repealed', 'omitted', 'substituted', 'amended')",
            name="ck_sections_status",
        ),
        CheckConstraint(
            "era IN ('colonial_codes', 'naveen_sanhitas', 'constitutional', 'other')",
            name="ck_sections_era",
        ),
        Index("idx_sections_act_code", "act_code"),
        Index("idx_sections_status", "status"),
        Index("idx_sections_era", "era"),
        Index("idx_sections_is_offence", "is_offence"),
        Index("idx_sections_cognizable", "is_cognizable"),
        Index("idx_sections_qdrant_indexed", "qdrant_indexed"),
    )

    # Relationships
    act: Mapped["Act"] = relationship("Act", back_populates="sections")
    chapter: Mapped[Optional["Chapter"]] = relationship("Chapter", back_populates="sections")
    sub_sections: Mapped[List["SubSection"]] = relationship(
        "SubSection", back_populates="section", cascade="all, delete-orphan"
    )
    audit_records: Mapped[List["ExtractionAudit"]] = relationship(
        "ExtractionAudit", back_populates="section"
    )
    review_records: Mapped[List["HumanReviewQueue"]] = relationship(
        "HumanReviewQueue", back_populates="section"
    )


# ---------------------------------------------------------------------------
# SubSection
# ---------------------------------------------------------------------------

class SubSection(Base):
    """Granular sub-section chunks for precise retrieval.

    Separating sub-sections solves the semantic dilution problem:
    a 2000-word section embedding diffuses the signal of specific clauses.
    A user asking about an exception needs the Proviso — not the full section.

    sub_section_label examples: '(1)', '(2)', '(a)', 'Explanation', 'Proviso', 'Illustration_A'
    """

    __tablename__ = "sub_sections"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    section_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sections.id", ondelete="CASCADE"),
        nullable=False,
    )
    act_code: Mapped[str] = mapped_column(String(20), nullable=False)
    parent_section_number: Mapped[str] = mapped_column(String(20), nullable=False)
    sub_section_label: Mapped[str] = mapped_column(String(20), nullable=False)
    sub_section_type: Mapped[str] = mapped_column(String(30), nullable=False)
    legal_text: Mapped[str] = mapped_column(Text, nullable=False)
    position_order: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "section_id", "sub_section_label", name="uq_sub_sections_section_label"
        ),
        CheckConstraint(
            "sub_section_type IN ('numbered', 'lettered', 'explanation', 'proviso', 'illustration', 'exception')",
            name="ck_sub_sections_type",
        ),
    )

    # Relationships
    section: Mapped["Section"] = relationship("Section", back_populates="sub_sections")


# ---------------------------------------------------------------------------
# LawTransitionMapping  (the safety table)
# ---------------------------------------------------------------------------

class LawTransitionMapping(Base):
    """Maps old criminal codes to their replacements in the new Sanhitas.

    This table prevents the murder-snatching confusion (IPC 302 = Murder vs BNS 302 = Snatching).
    Every row is a deterministic fact about how the legal landscape changed on July 1, 2024.

    ONLY rows with is_active = TRUE are used by StatuteNormalizationTool.
    is_active = TRUE requires: confidence_score >= 0.65 AND approved_by IS NOT NULL.

    Split case: IPC 376 (Rape) → BNS 63, 64, 65, 66, 67, 68, 70 creates SEVEN rows,
    all with old_section='376' and transition_type='split_into'.
    """

    __tablename__ = "law_transition_mappings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    old_act: Mapped[str] = mapped_column(String(20), nullable=False)
    old_section: Mapped[str] = mapped_column(String(20), nullable=False)
    old_section_title: Mapped[Optional[str]] = mapped_column(String(500))
    new_act: Mapped[Optional[str]] = mapped_column(String(20))
    new_section: Mapped[Optional[str]] = mapped_column(String(20))
    new_section_title: Mapped[Optional[str]] = mapped_column(String(500))
    transition_type: Mapped[str] = mapped_column(String(20), nullable=False)
    transition_note: Mapped[Optional[str]] = mapped_column(Text)
    scope_change: Mapped[Optional[str]] = mapped_column(String(30))
    semantic_similarity: Mapped[Optional[float]] = mapped_column(Float)
    gazette_reference: Mapped[Optional[str]] = mapped_column(String(300))
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False, server_default="0.0")
    approved_by: Mapped[Optional[str]] = mapped_column(String(100))
    approved_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    user_correct_votes: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    user_wrong_votes: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    auto_demoted: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "transition_type IN ('equivalent', 'modified', 'split_into', 'merged_from', 'deleted', 'new')",
            name="ck_transition_type",
        ),
        CheckConstraint(
            "scope_change IN ('none', 'narrowed', 'expanded', 'restructured', 'unknown') OR scope_change IS NULL",
            name="ck_scope_change",
        ),
        Index("idx_transition_old", "old_act", "old_section"),
        Index("idx_transition_new", "new_act", "new_section"),
        Index("idx_transition_active", "is_active"),
    )


# ---------------------------------------------------------------------------
# CrossReference
# ---------------------------------------------------------------------------

class CrossReference(Base):
    """Structured cross-references between sections extracted from legal text.

    Examples of reference_text: 'as defined in Section 2(1)(d)',
    'subject to the provisions of Section 45', 'except as provided in Section X'.

    These enable graph traversal without a dedicated graph database in Phase 1.
    """

    __tablename__ = "cross_references"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    source_act: Mapped[str] = mapped_column(String(20), nullable=False)
    source_section: Mapped[str] = mapped_column(String(20), nullable=False)
    target_act: Mapped[str] = mapped_column(String(20), nullable=False)
    target_section: Mapped[str] = mapped_column(String(20), nullable=False)
    target_subsection: Mapped[Optional[str]] = mapped_column(String(20))
    reference_text: Mapped[Optional[str]] = mapped_column(Text)
    reference_type: Mapped[Optional[str]] = mapped_column(String(30))
    extraction_method: Mapped[Optional[str]] = mapped_column(String(30))

    __table_args__ = (
        CheckConstraint(
            "reference_type IN ('definition_import', 'subject_to', 'procedure_link', "
            "'punishment_table', 'exception_reference', 'cross_act_reference') OR reference_type IS NULL",
            name="ck_cross_ref_type",
        ),
        Index("idx_xref_source", "source_act", "source_section"),
        Index("idx_xref_target", "target_act", "target_section"),
    )


# ---------------------------------------------------------------------------
# ExtractionAudit
# ---------------------------------------------------------------------------

class ExtractionAudit(Base):
    """Quality control record for every section processed by the extraction pipeline.

    Every section in the sections table has a corresponding audit row.
    Tracks what noise was found, what was removed, and final extraction confidence.
    """

    __tablename__ = "extraction_audit"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    section_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sections.id")
    )
    act_code: Mapped[str] = mapped_column(String(20), nullable=False)
    section_number: Mapped[str] = mapped_column(String(20), nullable=False)
    pipeline_version: Mapped[Optional[str]] = mapped_column(String(50))
    checks_run: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    checks_passed: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    check_failures: Mapped[Optional[list]] = mapped_column(JSONB)
    extraction_confidence: Mapped[float] = mapped_column(Float, nullable=False, server_default="1.0")
    noise_types_found: Mapped[Optional[list]] = mapped_column(JSONB)
    raw_text_length: Mapped[Optional[int]] = mapped_column(Integer)
    cleaned_text_length: Mapped[Optional[int]] = mapped_column(Integer)
    requires_human_review: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("idx_audit_act_section", "act_code", "section_number"),
        Index("idx_audit_confidence", "extraction_confidence"),
    )

    # Relationships
    section: Mapped[Optional["Section"]] = relationship(
        "Section", back_populates="audit_records"
    )


# ---------------------------------------------------------------------------
# HumanReviewQueue
# ---------------------------------------------------------------------------

class HumanReviewQueue(Base):
    """Sections flagged for manual review before Qdrant indexing.

    Any section where extraction_confidence < 0.7 routes here.
    Nothing with a pending review enters Qdrant indexing.
    """

    __tablename__ = "human_review_queue"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    section_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sections.id")
    )
    act_code: Mapped[str] = mapped_column(String(20), nullable=False)
    section_number: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    raw_text: Mapped[Optional[str]] = mapped_column(Text)
    cleaned_text: Mapped[Optional[str]] = mapped_column(Text)
    extraction_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pending")
    reviewed_by: Mapped[Optional[str]] = mapped_column(String(100))
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    review_notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'needs_reextraction')",
            name="ck_review_status",
        ),
        Index("idx_review_status", "status"),
        Index("idx_review_act", "act_code"),
    )

    # Relationships
    section: Mapped[Optional["Section"]] = relationship(
        "Section", back_populates="review_records"
    )


# ---------------------------------------------------------------------------
# IngestedJudgment  (SC Judgments audit trail + deduplication registry)
# ---------------------------------------------------------------------------

class IngestedJudgment(Base):
    """Audit trail and deduplication registry for Supreme Court judgment ingestion.

    Before processing any judgment PDF, the pipeline checks this table.
    Prevents re-downloading PDFs, enables incremental updates, and logs
    Indian Kanoon URL enrichment status.

    diary_no is the primary deduplication key — guaranteed unique per judgment.
    UNIQUE(diary_no) means re-running the pipeline for an already-ingested year
    is fully idempotent: duplicate rows are silently rejected.

    qdrant_point_ids stores the list of chunk UUIDs (uuid5 derived) so that
    targeted deletion or re-indexing of a specific judgment is possible without
    scanning all 200,000+ points.

    ik_url is stored as empty string until the Indian Kanoon enrichment pass runs.
    ik_resolved_at = NULL means not yet enriched; the partial index on this column
    makes the enrichment query (WHERE ik_resolved_at IS NULL) O(log n).
    """

    __tablename__ = "ingested_judgments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    # Primary deduplication key — eCourts internal filing number
    diary_no: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    # Formal case number (e.g. "C.A. No.-004292-004292 - 2002") — NOT an AIR/SCC citation
    case_no: Mapped[Optional[str]] = mapped_column(String(200))
    # "Petitioner v. Respondent" — derived from pet + res fields in Vanga data
    case_name: Mapped[Optional[str]] = mapped_column(Text)
    # Year partition key from Vanga S3 tarball (always correct, unlike judgment_dates)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    # Decision date after century-bug correction applied
    decision_date: Mapped[Optional[date]] = mapped_column(Date)
    # From Vanga Parquet — "Dismissed", "Allowed", "Bail Granted", etc.
    disposal_nature: Mapped[Optional[str]] = mapped_column(String(100))
    # Inferred from case_no prefix: "C.A." → civil, "Crl.A." → criminal, etc.
    legal_domain: Mapped[Optional[str]] = mapped_column(String(50))
    # All Qdrant chunk point UUIDs for this judgment (uuid5 of diary_no__chunkN)
    qdrant_point_ids: Mapped[Optional[list]] = mapped_column(JSONB)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    # Indian Kanoon URL — empty string until enrichment pass runs
    ik_url: Mapped[str] = mapped_column(Text, nullable=False, server_default="''")
    # Indian Kanoon internal doc ID (no mathematical relationship to diary_no)
    ik_tid: Mapped[Optional[int]] = mapped_column(Integer)
    # NULL = not yet enriched; set to NOW() when ik_url is populated
    ik_resolved_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP(timezone=True))
    ingested_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now()
    )
    # SHA-256 of source PDF for change detection on re-ingestion
    pdf_hash: Mapped[Optional[str]] = mapped_column(String(64))
    # True if PyMuPDF extracted < 200 chars on a multi-page PDF → OCR was used
    ocr_required: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    __table_args__ = (
        Index("idx_ingested_year", "year"),
        Index("idx_ingested_disposal", "disposal_nature"),
        # Partial index — efficiently finds records that still need IK URL enrichment
        Index(
            "idx_ingested_ik_unresolved",
            "ik_resolved_at",
            postgresql_where=sa_text("ik_resolved_at IS NULL"),
        ),
    )
