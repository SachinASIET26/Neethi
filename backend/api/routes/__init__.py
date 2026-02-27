"""API route modules."""

from backend.api.routes import (
    admin,
    auth,
    cases,
    documents,
    query,
    resources,
    sections,
    translate,
    voice,
)

__all__ = [
    "admin", "auth", "cases", "documents",
    "query", "resources", "sections", "translate", "voice",
]
