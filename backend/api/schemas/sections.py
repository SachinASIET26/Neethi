"""Pydantic schemas for sections & acts endpoints."""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel


class ActInfo(BaseModel):
    act_code: str
    act_name: str
    short_name: Optional[str] = None
    era: Optional[str] = None
    effective_from: Optional[str] = None
    superseded_by: Optional[List[str]] = None
    superseded_on: Optional[str] = None
    replaces: Optional[List[str]] = None
    total_sections: int = 0
    indexed_sections: int = 0


class ActListResponse(BaseModel):
    acts: List[ActInfo]


class SectionSummary(BaseModel):
    section_number: str
    section_title: Optional[str] = None
    chapter: Optional[str] = None
    is_offence: Optional[bool] = None
    is_cognizable: Optional[bool] = None
    is_bailable: Optional[bool] = None
    triable_by: Optional[str] = None


class SectionListResponse(BaseModel):
    act_code: str
    total_sections: int
    sections: List[SectionSummary]


class SectionReplaces(BaseModel):
    act_code: str
    section_number: str


class SectionDetail(BaseModel):
    act_code: str
    act_name: str
    section_number: str
    section_title: Optional[str] = None
    chapter: Optional[str] = None
    chapter_title: Optional[str] = None
    legal_text: Optional[str] = None
    is_offence: Optional[bool] = None
    is_cognizable: Optional[bool] = None
    is_bailable: Optional[bool] = None
    triable_by: Optional[str] = None
    replaces: List[SectionReplaces] = []
    related_sections: List[str] = []
    verification_status: str = "VERIFIED"
    extraction_confidence: Optional[float] = None


class NormalizeResponse(BaseModel):
    input: dict
    mapped_to: Optional[dict] = None
    new_section_title: Optional[str] = None
    transition_type: Optional[str] = None
    warning: Optional[str] = None
    effective_from: Optional[str] = None
    source: str = "database"
    message: Optional[str] = None


class VerifyCitation(BaseModel):
    act_code: str
    section_number: str


class VerifyRequest(BaseModel):
    citations: List[VerifyCitation]


class VerifyResult(BaseModel):
    act_code: str
    section_number: str
    status: Literal["VERIFIED", "VERIFIED_INCOMPLETE", "NOT_FOUND"]
    section_title: Optional[str] = None
    warning: Optional[str] = None


class VerifyResponse(BaseModel):
    results: List[VerifyResult]
