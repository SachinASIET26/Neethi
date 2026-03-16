"""PageIndex AI stub service.

Provides document analysis capabilities via the PageIndex MCP API.
Currently a stub — returns mock data when PAGEINDEX_API_KEY is not configured.
Ready to activate when API key is available.

Usage:
    from backend.services.pageindex import pageindex_service

    if pageindex_service.is_available():
        result = await pageindex_service.analyze_document(file_bytes, "Summarize this contract")
    else:
        # Service unavailable — return 503
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


class PageIndexService:
    """PageIndex document analysis service (stub/mock)."""

    def __init__(self) -> None:
        self._api_key = os.getenv("PAGEINDEX_API_KEY", "").strip()

    def is_available(self) -> bool:
        """Return True if PageIndex API key is configured."""
        return bool(self._api_key)

    async def analyze_document(
        self,
        file_bytes: bytes,
        query: str,
        *,
        extract_tables: bool = True,
        extract_sections: bool = True,
    ) -> dict[str, Any]:
        """Analyze a document using PageIndex.

        Args:
            file_bytes: Raw PDF bytes.
            query: Analysis query/instruction.
            extract_tables: Whether to extract table structures.
            extract_sections: Whether to extract document sections.

        Returns:
            Analysis result dict with structure:
            {
                "summary": str,
                "sections": [{"title": str, "content": str, "page": int}],
                "tables": [{"headers": list, "rows": list, "page": int}],
                "entities": [{"type": str, "value": str, "context": str}],
                "key_findings": [str],
            }

        Raises:
            RuntimeError: If PageIndex is not configured.
        """
        if not self.is_available():
            raise RuntimeError("PageIndex API key not configured.")

        # ──────────────────────────────────────────────────────────
        # TODO: Activate when PAGEINDEX_API_KEY is available
        #
        # Full MCP client implementation:
        #
        # import httpx
        #
        # async with httpx.AsyncClient(timeout=120) as client:
        #     resp = await client.post(
        #         "https://api.pageindex.ai/v1/analyze",
        #         headers={
        #             "Authorization": f"Bearer {self._api_key}",
        #             "Content-Type": "application/pdf",
        #         },
        #         content=file_bytes,
        #         params={
        #             "query": query,
        #             "extract_tables": str(extract_tables).lower(),
        #             "extract_sections": str(extract_sections).lower(),
        #         },
        #     )
        #     resp.raise_for_status()
        #     return resp.json()
        # ──────────────────────────────────────────────────────────

        # Return mock response for development/testing
        return self._mock_response(query)

    def _mock_response(self, query: str) -> dict[str, Any]:
        """Return a mock analysis response for development."""
        return {
            "summary": f"[PageIndex Stub] Analysis requested: {query[:100]}",
            "sections": [
                {
                    "title": "Document Overview",
                    "content": "This is a stub response. Configure PAGEINDEX_API_KEY to enable real analysis.",
                    "page": 1,
                },
            ],
            "tables": [],
            "entities": [],
            "key_findings": [
                "PageIndex integration is configured but API key is not set.",
                "Set PAGEINDEX_API_KEY environment variable to activate.",
            ],
        }


# Singleton instance
pageindex_service = PageIndexService()
