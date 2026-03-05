"""Pydantic schemas for admin endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


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


# ---------------------------------------------------------------------------
# User management schemas
# ---------------------------------------------------------------------------

class UserListItem(BaseModel):
    user_id: str
    full_name: str
    email: str
    role: str
    is_active: bool
    is_email_verified: bool
    query_count_today: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class UserListResponse(BaseModel):
    total: int
    users: List[UserListItem]


class UserDetail(BaseModel):
    user_id: str
    full_name: str
    email: str
    role: str
    is_active: bool
    is_email_verified: bool
    bar_council_id: Optional[str] = None
    police_badge_id: Optional[str] = None
    organization: Optional[str] = None
    query_count_today: int = 0
    total_queries: int = 0
    total_drafts: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class UserUpdateRequest(BaseModel):
    role: Optional[str] = Field(None, pattern="^(citizen|lawyer|legal_advisor|police|admin)$")
    is_active: Optional[bool] = None


# ---------------------------------------------------------------------------
# Admin stats & activity schemas
# ---------------------------------------------------------------------------

class RoleCount(BaseModel):
    role: str
    count: int


class AdminStats(BaseModel):
    total_users: int
    active_users: int
    users_by_role: List[RoleCount]
    total_queries_today: int
    total_queries_all_time: int
    total_drafts: int
    recent_signups_7d: int


class ActivityItem(BaseModel):
    query_id: str
    user_id: str
    user_name: str
    user_email: str
    user_role: str
    query_text: str
    verification_status: Optional[str] = None
    confidence: Optional[str] = None
    processing_time_ms: Optional[int] = None
    cached: bool = False
    created_at: Optional[datetime] = None


class ActivityResponse(BaseModel):
    total: int
    activities: List[ActivityItem]
