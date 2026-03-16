"""Pydantic schemas for the conversational turn endpoints."""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

from backend.api.schemas.query import CitationResult


class TurnRequest(BaseModel):
    session_id: Optional[str] = Field(
        None, description="Existing session ID. None creates a new session."
    )
    message: str = Field(..., min_length=1, max_length=2000)
    language: str = Field("en", description="User's preferred language code")
    action_id: Optional[str] = Field(
        None, description="If the user clicked a suggestion button"
    )


class ActionSuggestionSchema(BaseModel):
    id: str
    label: str
    icon: str
    description: str


class TurnResponse(BaseModel):
    session_id: str
    turn_number: int
    intent: str
    response: str
    suggestions: List[ActionSuggestionSchema] = []
    needs_clarification: bool = False
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
    context: dict = {}
    intent_history: list = []
    created_at: str
    updated_at: str
