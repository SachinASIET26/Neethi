"""Pydantic schemas for query endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    query: str = Field(..., min_length=5, max_length=2000)
    language: str = Field("en", description="Response language code")
    include_precedents: bool = Field(
        False, description="Force SC judgment search (lawyer crew only)"
    )


class CitationResult(BaseModel):
    act_code: str
    section_number: str
    section_title: Optional[str] = None
    verification: Literal["VERIFIED", "VERIFIED_INCOMPLETE", "NOT_FOUND"]


class PrecedentResult(BaseModel):
    case_name: str
    year: Optional[str] = None
    court: Optional[str] = None
    citation: Optional[str] = None
    verification: Literal["VERIFIED", "NOT_FOUND"] = "VERIFIED"


class QueryResponse(BaseModel):
    query_id: str
    query: str
    response: str
    verification_status: Literal["VERIFIED", "PARTIALLY_VERIFIED", "UNVERIFIED"]
    confidence: Literal["high", "medium", "low"]
    citations: List[CitationResult] = []
    precedents: List[PrecedentResult] = []
    user_role: str
    processing_time_ms: int
    cached: bool
    disclaimer: str = (
        "This is AI-assisted legal information. "
        "Consult a qualified legal professional for advice specific to your situation."
    )


class QueryHistoryItem(BaseModel):
    query_id: str
    query_text: str
    verification_status: Optional[str]
    confidence: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class QueryHistoryResponse(BaseModel):
    total: int
    queries: List[QueryHistoryItem]


class FeedbackRequest(BaseModel):
    query_id: str
    rating: int = Field(..., ge=1, le=5)
    feedback_type: Literal[
        "helpful", "citation_wrong", "hallucination", "incomplete", "language_issue"
    ]
    comment: Optional[str] = Field(None, max_length=500)


class FeedbackResponse(BaseModel):
    feedback_id: str
    message: str
