"""Pydantic schemas for cases endpoints."""

from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class CaseSearchRequest(BaseModel):
    query: str = Field(..., min_length=3, max_length=500)
    act_filter: Optional[str] = None
    top_k: int = Field(5, ge=1, le=10)
    from_year: Optional[int] = Field(None, ge=1950, le=2030)
    to_year: Optional[int] = Field(None, ge=1950, le=2030)


class CaseResult(BaseModel):
    case_name: str
    citation: Optional[str] = None
    court: Optional[str] = None
    judgment_date: Optional[str] = None
    judges: List[str] = []
    legal_domain: Optional[str] = None
    relevance_score: float
    summary: Optional[str] = None
    sections_cited: List[str] = []


class CaseSearchResponse(BaseModel):
    results: List[CaseResult]
    total_found: int
    search_time_ms: int


class CaseAnalysisRequest(BaseModel):
    scenario: str = Field(..., min_length=20, max_length=3000)
    case_citation: Optional[str] = None
    applicable_acts: List[str] = []


class IRACSection(BaseModel):
    issue: str
    rule: str
    application: str
    conclusion: str


class AnalysisCitation(BaseModel):
    act_code: str
    section_number: str
    verification: str


class AnalysisPrecedent(BaseModel):
    case_name: str
    year: Optional[str] = None
    relevance: Optional[str] = None


class CaseAnalysisResponse(BaseModel):
    irac_analysis: IRACSection
    applicable_sections: List[AnalysisCitation]
    applicable_precedents: List[AnalysisPrecedent]
    confidence: str
    verification_status: str


class CaseDetail(BaseModel):
    case_id: str
    case_name: str
    citation: Optional[str] = None
    court: Optional[str] = None
    judgment_date: Optional[str] = None
    judges: List[str] = []
    full_text: Optional[str] = None
    sections_cited: List[str] = []
    headnotes: List[str] = []
    indexed_at: Optional[str] = None
