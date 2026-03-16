"""API route modules."""

from backend.api.routes import (
    admin,
    auth,
    cases,
    conversation,
    document_analysis,
    documents,
    query,
    resources,
    sections,
    translate,
    voice,
)

__all__ = [
    "admin", "auth", "cases", "conversation", "document_analysis",
    "documents", "query", "resources", "sections", "translate", "voice",
]
