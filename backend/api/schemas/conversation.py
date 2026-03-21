"""Pydantic schemas for the conversational turn endpoints."""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

from backend.api.schemas.query import CitationResult


class TurnRequest(BaseModel):
    session_id: Optional[str] = Field(
        None, description="Existing session ID. None creates a new session."
    )
    message: str = Field("", max_length=2000)
    language: str = Field("en", description="User's preferred language code")
    action_id: Optional[str] = Field(
        None, description="If the user clicked a suggestion button"
    )


class ActionSuggestionSchema(BaseModel):
    id: str
    label: str
    icon: str
    description: str


class ClarifyingQuestionSchema(BaseModel):
    """A clarifying question with optional pre-defined answer options."""
    id: str
    text: str
    options: Optional[List[str]] = None  # None = free text input


class FormulatedQuerySchema(BaseModel):
    """LLM-reformulated legal query with domain classification."""
    legal_query: str
    domain: str
    sub_domains: List[str] = []
    summary: str  # plain language for user confirmation


class RetrievedSectionSchema(BaseModel):
    """A retrieved legal section with reason for applicability."""
    act_code: str
    section_number: str
    section_title: str = ""
    reason_applicable: str = ""
    verification_status: str = "VERIFIED"
    relevance: str = "RELEVANT"  # RELEVANT | TANGENTIAL


class TurnResponse(BaseModel):
    session_id: str
    turn_number: int
    stage: str = "intake"  # current pipeline stage
    intent: str
    response: str
    suggestions: List[ActionSuggestionSchema] = []
    needs_clarification: bool = False

    # Stage-specific data
    clarifying_questions: Optional[List[ClarifyingQuestionSchema]] = None
    formulated_query: Optional[FormulatedQuerySchema] = None
    retrieved_sections: Optional[List[RetrievedSectionSchema]] = None

    verification_status: Optional[Literal["VERIFIED", "PARTIALLY_VERIFIED", "UNVERIFIED"]] = None
    confidence: Optional[Literal["high", "medium", "low"]] = None
    citations: List[CitationResult] = []
    processing_time_ms: int = 0
    cached: bool = False


class SessionResponse(BaseModel):
    session_id: str
    user_id: str
    turn_count: int
    status: str
    stage: str = "intake"
    context: dict = {}
    intent_history: list = []
    created_at: str
    updated_at: str
