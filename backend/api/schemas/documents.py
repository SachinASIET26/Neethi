"""Pydantic schemas for document drafting endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class TemplateInfo(BaseModel):
    template_id: str
    template_name: str
    description: str
    required_fields: List[str]
    optional_fields: List[str]
    jurisdiction: str
    language: str
    access_roles: List[str]


class TemplateListResponse(BaseModel):
    templates: List[TemplateInfo]


class DraftRequest(BaseModel):
    template_id: str
    fields: Dict[str, str] = Field(..., description="Template field values")
    language: str = Field("en")
    include_citations: bool = True


class CitationInDraft(BaseModel):
    act_code: str
    section_number: str
    verification: str


class DraftResponse(BaseModel):
    draft_id: str
    template_id: str
    title: str
    draft_text: str
    verification_status: str
    citations_used: List[CitationInDraft] = []
    disclaimer: str = (
        "DRAFT ONLY — NOT LEGAL ADVICE. "
        "This document requires review by a qualified lawyer before filing."
    )
    created_at: datetime
    word_count: int

    model_config = {"from_attributes": True}


class DraftUpdateRequest(BaseModel):
    fields: Dict[str, str]
