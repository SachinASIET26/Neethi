"""PageIndex AI service — Vectify's vectorless document RAG.

Architecture (from docs.pageindex.ai):
  Phase 1 — Tree Generation: PageIndex LLM reads the PDF and builds a JSON TOC tree
             (root → chapters/sections → page-level leaf nodes).
  Phase 2 — Reasoning-Based Retrieval: Given a query, PageIndex LLM navigates the tree,
             selects the relevant node IDs, and returns only that text — no vector math.

Flow for Neethi AI:
  1. submit_document()   → POST /doc/  → doc_id
  2. wait_for_ready()    → poll GET /doc/{doc_id}/ until status == "completed"
  3. retrieve()          → POST /retrieval/ → retrieved_nodes
  4. Caller feeds retrieved_nodes into Neethi's LegalReasoner for IRAC formatting.

Trade-offs documented in CLAUDE.md:
  - High extraction accuracy (critical for dense legal text)
  - External data transit (documents leave the local server)
  - Latency: tree generation is slower than embedding search at query time
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.pageindex.ai"
_POLL_INTERVAL_S = 3          # seconds between doc-tree status polls
_MAX_POLLS = 40               # 40 × 3 s = 2 minutes max wait (tree generation)
_RETRIEVAL_POLL_INTERVAL_S = 2  # seconds between retrieval polls
_MAX_RETRIEVAL_POLLS = 30       # 30 × 2 s = 1 minute max wait (retrieval)


class PageIndexService:
    """Async client for the Vectify PageIndex API."""

    def is_available(self) -> bool:
        """Return True if the API key is configured."""
        return bool(os.getenv("PAGEINDEX_API_KEY", "").strip())

    @property
    def _api_key(self) -> str:
        """Read the key lazily so dotenv has time to load."""
        return os.getenv("PAGEINDEX_API_KEY", "").strip()

    @property
    def _headers(self) -> dict[str, str]:
        return {"api_key": self._api_key}

    # ------------------------------------------------------------------
    # Step 1 — Submit document
    # ------------------------------------------------------------------

    async def submit_document(self, file_bytes: bytes, filename: str = "document.pdf") -> str:
        """Upload a PDF to PageIndex and return the doc_id.

        POST /doc/  (multipart/form-data, field name: "file")
        Response: {"doc_id": "...", "status": "processing"}
        """
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{_BASE_URL}/doc/",
                headers=self._headers,
                files={"file": (filename, file_bytes, "application/pdf")},
                data={"if_retrieval": "true"},
            )
            if not resp.is_success:
                # Surface the PageIndex error body (e.g. "LimitReached") instead of a bare 403
                try:
                    detail = resp.json().get("detail", resp.text)
                except Exception:
                    detail = resp.text
                raise RuntimeError(
                    f"PageIndex rejected the document (HTTP {resp.status_code}): {detail}. "
                    "If this is 'LimitReached', the file exceeds your plan's page/size limit — "
                    "try a shorter document or upgrade your PageIndex plan."
                )
            data = resp.json()
            doc_id: str = data["doc_id"]
            logger.info("PageIndex: submitted %s → doc_id=%s", filename, doc_id)
            return doc_id

    # ------------------------------------------------------------------
    # Step 2 — Poll until tree is ready
    # ------------------------------------------------------------------

    async def wait_for_ready(
        self,
        doc_id: str,
        on_poll: Any = None,
    ) -> None:
        """Poll GET /doc/{doc_id}/ until status == "completed".

        Args:
            doc_id:   PageIndex document ID.
            on_poll:  Optional async callable(attempt: int) called each poll cycle.

        Raises:
            TimeoutError: If the document is still processing after MAX_POLLS attempts.
            httpx.HTTPStatusError: On API errors.
        """
        async with httpx.AsyncClient(timeout=30) as client:
            for attempt in range(1, _MAX_POLLS + 1):
                resp = await client.get(
                    f"{_BASE_URL}/doc/{doc_id}/",
                    headers=self._headers,
                )
                resp.raise_for_status()
                data = resp.json()
                status = data.get("status")

                logger.debug("PageIndex poll %d/%d — doc_id=%s status=%s", attempt, _MAX_POLLS, doc_id, status)

                if status == "completed":
                    logger.info("PageIndex: tree ready for doc_id=%s after %d polls", doc_id, attempt)
                    return

                if on_poll is not None:
                    await on_poll(attempt)

                await asyncio.sleep(_POLL_INTERVAL_S)

        raise TimeoutError(
            f"PageIndex document {doc_id} was still processing after {_MAX_POLLS * _POLL_INTERVAL_S}s."
        )

    # ------------------------------------------------------------------
    # Step 3 — Retrieval query
    # ------------------------------------------------------------------

    async def retrieve(self, doc_id: str, query: str, *, thinking: bool = False) -> dict[str, Any]:
        """Run a reasoning-based retrieval query against the indexed document.

        Retrieval is async on PageIndex's side:
          POST /retrieval/  → {"retrieval_id": "..."}   (no nodes yet)
          GET  /retrieval/{retrieval_id}/  → poll until status == "completed"
          Final response:  {"retrieved_nodes": [...], ...}

        Node structure returned by the API:
          {
            "id": str,
            "title": str,
            "metadata": list,
            "relevant_contents": [[{"section_title", "physical_index", "relevant_content"}, ...], ...]
          }
        """
        async with httpx.AsyncClient(timeout=120) as client:
            # Step A — submit retrieval job
            resp = await client.post(
                f"{_BASE_URL}/retrieval/",
                headers={**self._headers, "Content-Type": "application/json"},
                json={"doc_id": doc_id, "query": query, "thinking": thinking},
            )
            resp.raise_for_status()
            retrieval_id: str = resp.json()["retrieval_id"]
            logger.info("PageIndex: retrieval job started for doc_id=%s retrieval_id=%s", doc_id, retrieval_id)

            # Step B — poll until retrieval completes
            for attempt in range(1, _MAX_RETRIEVAL_POLLS + 1):
                r = await client.get(
                    f"{_BASE_URL}/retrieval/{retrieval_id}/",
                    headers=self._headers,
                )
                r.raise_for_status()
                data = r.json()
                status = data.get("status")
                logger.debug(
                    "PageIndex retrieval poll %d/%d — retrieval_id=%s status=%s",
                    attempt, _MAX_RETRIEVAL_POLLS, retrieval_id, status,
                )
                if status == "completed":
                    nodes = data.get("retrieved_nodes", [])
                    logger.info(
                        "PageIndex: retrieval complete for doc_id=%s, nodes=%d",
                        doc_id, len(nodes),
                    )
                    return data
                await asyncio.sleep(_RETRIEVAL_POLL_INTERVAL_S)

        raise TimeoutError(
            f"PageIndex retrieval {retrieval_id} was still processing after "
            f"{_MAX_RETRIEVAL_POLLS * _RETRIEVAL_POLL_INTERVAL_S}s."
        )

    # ------------------------------------------------------------------
    # Convenience: full pipeline with async status callbacks
    # ------------------------------------------------------------------

    async def analyze_document(
        self,
        file_bytes: bytes,
        query: str,
        filename: str = "document.pdf",
        *,
        on_status: Any = None,
    ) -> dict[str, Any]:
        """Run the full submit → poll → retrieve pipeline.

        Args:
            file_bytes: Raw PDF bytes.
            query:      User's analysis query.
            filename:   Original filename (used for multipart upload).
            on_status:  Optional async callable(message: str) for progress updates.

        Returns:
            Dict with keys:
              doc_id, query, retrieved_nodes, summary (first relevant_content block)
        """
        async def _emit(msg: str) -> None:
            if on_status is not None:
                await on_status(msg)

        await _emit("Submitting document to PageIndex…")
        doc_id = await self.submit_document(file_bytes, filename)

        poll_count = 0

        async def _on_poll(attempt: int) -> None:
            nonlocal poll_count
            poll_count = attempt
            await _emit(f"Building document tree… ({attempt}/{_MAX_POLLS})")

        await self.wait_for_ready(doc_id, on_poll=_on_poll)
        await _emit("Running retrieval query…")

        retrieval = await self.retrieve(doc_id, query)
        retrieved_nodes: list[dict[str, Any]] = retrieval.get("retrieved_nodes", [])

        # Build a flat summary from the first relevant_content block of each node.
        # relevant_contents is an array of arrays: [[{section_title, physical_index, relevant_content}, ...], ...]
        summary_parts = []
        for node in retrieved_nodes:
            for rc_group in node.get("relevant_contents", []):
                # Each group is a list; take the first item that has content
                for rc in (rc_group if isinstance(rc_group, list) else [rc_group]):
                    text = rc.get("relevant_content", "").strip()
                    if text:
                        summary_parts.append(text)
                        break
                if summary_parts and summary_parts[-1]:  # one excerpt per node is enough
                    break

        return {
            "doc_id": doc_id,
            "query": query,
            "retrieved_nodes": retrieved_nodes,
            "summary": "\n\n".join(summary_parts) if summary_parts else "No relevant content retrieved.",
        }


# Singleton
pageindex_service = PageIndexService()
