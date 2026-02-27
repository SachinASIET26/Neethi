"""User-facing database models — auth, query logs, drafts, feedback."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.models.legal_foundation import Base


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------

class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    full_name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))

    # Role: citizen | lawyer | legal_advisor | police | admin
    role: Mapped[str] = mapped_column(String(20), index=True)

    # Role-specific verification IDs
    bar_council_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    police_badge_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    organization: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_email_verified: Mapped[bool] = mapped_column(Boolean, default=False)

    # Rate-limit counters (reset daily)
    query_count_today: Mapped[int] = mapped_column(Integer, default=0)
    query_count_reset_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    queries: Mapped[list["QueryLog"]] = relationship(
        "QueryLog", back_populates="user", cascade="all, delete-orphan"
    )
    drafts: Mapped[list["Draft"]] = relationship(
        "Draft", back_populates="user", cascade="all, delete-orphan"
    )
    feedback: Mapped[list["QueryFeedback"]] = relationship(
        "QueryFeedback", back_populates="user", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# Query Log
# ---------------------------------------------------------------------------

class QueryLog(Base):
    __tablename__ = "query_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )

    query_text: Mapped[str] = mapped_column(Text)
    response_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    verification_status: Mapped[Optional[str]] = mapped_column(
        String(30), nullable=True
    )  # VERIFIED | PARTIALLY_VERIFIED | UNVERIFIED
    confidence: Mapped[Optional[str]] = mapped_column(
        String(10), nullable=True
    )  # high | medium | low

    citations: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    precedents: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    user_role: Mapped[str] = mapped_column(String(20))
    processing_time_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    cached: Mapped[bool] = mapped_column(Boolean, default=False)
    tier: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)  # DIRECT | FULL

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="queries")
    feedback: Mapped[list["QueryFeedback"]] = relationship(
        "QueryFeedback", back_populates="query_log", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# Draft
# ---------------------------------------------------------------------------

class Draft(Base):
    __tablename__ = "drafts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )

    template_id: Mapped[str] = mapped_column(String(100))
    title: Mapped[str] = mapped_column(String(255))
    draft_text: Mapped[str] = mapped_column(Text)
    fields_used: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    verification_status: Mapped[Optional[str]] = mapped_column(
        String(30), nullable=True
    )
    citations_used: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)

    language: Mapped[str] = mapped_column(String(10), default="en")
    word_count: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="drafts")


# ---------------------------------------------------------------------------
# Query Feedback
# ---------------------------------------------------------------------------

class QueryFeedback(Base):
    __tablename__ = "query_feedback"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    query_log_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("query_logs.id", ondelete="SET NULL"),
        nullable=True,
    )

    rating: Mapped[int] = mapped_column(Integer)  # 1-5
    feedback_type: Mapped[str] = mapped_column(String(50))
    comment: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="feedback")
    query_log: Mapped[Optional["QueryLog"]] = relationship(
        "QueryLog", back_populates="feedback"
    )
