"""Pydantic schemas for translation endpoints."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class TranslateTextRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000)
    source_language: str = Field("en")
    target_language: str = Field(..., description="Target language code, e.g. 'hi'")
    domain: str = Field("legal", description="Translation domain hint")


class TranslateTextResponse(BaseModel):
    translated_text: str
    source_language: str
    target_language: str
    preserved_terms: List[str] = []
    confidence: Optional[float] = None
    provider: str = "sarvam_ai"


class TranslateQueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    source_language: str = Field(..., description="Source language code, e.g. 'hi'")


class TranslateQueryResponse(BaseModel):
    original_query: str
    english_query: str
    source_language: str
    confidence: Optional[float] = None
