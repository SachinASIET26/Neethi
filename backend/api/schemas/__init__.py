"""Pydantic schemas for all API endpoints."""

from backend.api.schemas.auth import (
    LoginRequest,
    RefreshResponse,
    RegisterRequest,
    RegisterResponse,
    TokenResponse,
    UserProfile,
)
from backend.api.schemas.query import (
    CitationResult,
    FeedbackRequest,
    FeedbackResponse,
    PrecedentResult,
    QueryHistoryItem,
    QueryHistoryResponse,
    QueryRequest,
    QueryResponse,
)
from backend.api.schemas.cases import (
    CaseAnalysisRequest,
    CaseAnalysisResponse,
    CaseDetail,
    CaseSearchRequest,
    CaseSearchResponse,
)
from backend.api.schemas.documents import (
    DraftRequest,
    DraftResponse,
    DraftUpdateRequest,
    TemplateInfo,
    TemplateListResponse,
)
from backend.api.schemas.sections import (
    ActInfo,
    ActListResponse,
    NormalizeResponse,
    SectionDetail,
    SectionListResponse,
    VerifyRequest,
    VerifyResponse,
)
from backend.api.schemas.resources import (
    EligibilityResponse,
    NearbyRequest,
    NearbyResponse,
)
from backend.api.schemas.translate import (
    TranslateQueryRequest,
    TranslateQueryResponse,
    TranslateTextRequest,
    TranslateTextResponse,
)
from backend.api.schemas.voice import (
    STTResponse,
    TTSRequest,
    VoiceAskResponse,
)
from backend.api.schemas.admin import (
    CacheFlushRequest,
    CacheFlushResponse,
    HealthResponse,
    IngestResponse,
    JobStatus,
    MistralFallbackRequest,
    MistralFallbackResponse,
)

__all__ = [
    "LoginRequest", "RefreshResponse", "RegisterRequest", "RegisterResponse",
    "TokenResponse", "UserProfile",
    "CitationResult", "FeedbackRequest", "FeedbackResponse", "PrecedentResult",
    "QueryHistoryItem", "QueryHistoryResponse", "QueryRequest", "QueryResponse",
    "CaseAnalysisRequest", "CaseAnalysisResponse", "CaseDetail",
    "CaseSearchRequest", "CaseSearchResponse",
    "DraftRequest", "DraftResponse", "DraftUpdateRequest",
    "TemplateInfo", "TemplateListResponse",
    "ActInfo", "ActListResponse", "NormalizeResponse", "SectionDetail",
    "SectionListResponse", "VerifyRequest", "VerifyResponse",
    "EligibilityResponse", "NearbyRequest", "NearbyResponse",
    "TranslateQueryRequest", "TranslateQueryResponse",
    "TranslateTextRequest", "TranslateTextResponse",
    "STTResponse", "TTSRequest", "VoiceAskResponse",
    "CacheFlushRequest", "CacheFlushResponse", "HealthResponse",
    "IngestResponse", "JobStatus",
    "MistralFallbackRequest", "MistralFallbackResponse",
]
