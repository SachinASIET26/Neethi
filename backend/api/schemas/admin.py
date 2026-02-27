"""Pydantic schemas for admin endpoints."""

from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel


class ComponentHealth(BaseModel):
    status: str  # healthy | degraded | unavailable
    latency_ms: Optional[int] = None
    error: Optional[str] = None
    impact: Optional[str] = None
    # Qdrant-specific
    collections: Optional[List[str]] = None
    # Redis-specific
    hit_rate: Optional[float] = None
    # Groq-specific
    tpm_used: Optional[int] = None
    tpm_limit: Optional[int] = None


class HealthResponse(BaseModel):
    status: str  # healthy | degraded
    timestamp: str
    components: Dict[str, ComponentHealth]
    mistral_fallback_active: bool
    indexed_sections: Dict[str, int]


class IngestResponse(BaseModel):
    job_id: str
    act_code: str
    status: str
    message: str
    estimated_duration_minutes: int = 5


class JobResults(BaseModel):
    sections_extracted: int = 0
    sections_passed_confidence: int = 0
    sections_indexed_qdrant: int = 0
    sections_queued_review: int = 0
    errors: int = 0


class JobStatus(BaseModel):
    job_id: str
    act_code: str
    status: str  # queued | running | completed | failed
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    results: Optional[JobResults] = None
    error: Optional[str] = None


class CacheFlushRequest(BaseModel):
    role: str = "all"


class CacheFlushResponse(BaseModel):
    flushed_keys: int
    role: str


class MistralFallbackRequest(BaseModel):
    active: bool


class MistralFallbackResponse(BaseModel):
    mistral_fallback_active: bool
    message: str
