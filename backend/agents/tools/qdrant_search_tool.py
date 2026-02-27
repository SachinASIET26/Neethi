"""QdrantHybridSearchTool — Phase 5 retrieval tool.

Wraps the Phase 3 HybridSearcher + CrossEncoderReranker pipeline for use
by the RetrievalSpecialist agent.

CRITICAL: The RetrievalSpecialist agent MUST call StatuteNormalizationTool
first whenever the query contains old-act references (IPC, CrPC, IEA).
This tool does NOT auto-normalize — that is a deliberate architectural choice
that keeps the agent in control of when normalization is needed.

Embedder loading is lazy and handles FlagEmbedding being absent gracefully:
    - On GPU machines (Lightning AI): FlagEmbedding available → full search
    - On local dev (Windows): FlagEmbedding absent → returns NOT_AVAILABLE
"""

from __future__ import annotations

import logging
from typing import Optional

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy singleton — expensive to load (BGE-M3 model ~2GB)
# ---------------------------------------------------------------------------

_searcher = None
_reranker = None


def _get_searcher():
    """Return a HybridSearcher singleton, loading it on first call.

    Returns None if FlagEmbedding is not installed (local dev without GPU).
    """
    global _searcher
    if _searcher is not None:
        return _searcher
    try:
        from backend.rag.embeddings import BGEM3Embedder
        from backend.rag.hybrid_search import HybridSearcher
        from backend.rag.qdrant_setup import get_qdrant_client

        client = get_qdrant_client()
        embedder = BGEM3Embedder()
        _searcher = HybridSearcher(qdrant_client=client, embedder=embedder)
        logger.info("qdrant_search_tool: HybridSearcher initialized")
        return _searcher
    except ImportError:
        logger.warning(
            "qdrant_search_tool: FlagEmbedding not installed — "
            "search tool unavailable on this machine"
        )
        return None
    except Exception as exc:
        logger.error("qdrant_search_tool: searcher init failed: %s", exc)
        return None


def _get_reranker():
    """Return a CrossEncoderReranker singleton."""
    global _reranker
    if _reranker is not None:
        return _reranker
    try:
        from backend.rag.reranker import CrossEncoderReranker
        _reranker = CrossEncoderReranker()
        return _reranker
    except Exception as exc:
        logger.warning("qdrant_search_tool: reranker init failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Input schema
# ---------------------------------------------------------------------------

def _normalize_filter(val: object) -> Optional[str]:
    """Convert sentinel 'none'/'null'/empty to Python None; strip whitespace.

    Groq's strict tool schema validation requires ALL schema fields to be
    present in every function call — even Optional ones. To work around this,
    act_filter and era_filter are typed as plain str with default 'none'.
    The agent sends 'none' when it doesn't want to filter; this function
    converts that sentinel to Python None before passing to HybridSearcher.
    """
    if not val:
        return None
    s = str(val).strip()
    return None if s.lower() in ("none", "null", "n/a", "") else s


class QdrantSearchInput(BaseModel):
    """Input for the QdrantHybridSearchTool.

    GROQ COMPATIBILITY NOTE: Groq's tool validation requires ALL schema fields
    to be present in every function call. Therefore act_filter, era_filter, and
    collection are typed as plain str with sentinel defaults.

    The agent MUST always send both filter fields:
        - To filter:    act_filter='BNS_2023', era_filter='naveen_sanhitas'
        - No filter:    act_filter='none',     era_filter='none'

    legal_domain_filter is intentionally excluded — the indexed data uses
    domain values like 'Bodily Harm & Kidnapping' that never match LLM-generated
    values like 'criminal_substantive', so filtering by domain returns 0 results.
    """

    query: str = Field(..., description="Natural language legal query to search for")
    act_filter: str = Field(
        "none",
        description=(
            "Act code to restrict results. Options: 'BNS_2023', 'BNSS_2023', 'BSA_2023', "
            "'IPC_1860', 'CrPC_1973', 'IEA_1872'. "
            "Use the string 'none' (NOT Python None) if no act filter is needed. "
            "Always use 'none' when collection='sc_judgments'."
        ),
    )
    era_filter: str = Field(
        "none",
        description=(
            "Era filter. Options: 'naveen_sanhitas' (BNS/BNSS/BSA 2023 laws) or "
            "'colonial_codes' (IPC/CrPC/IEA). "
            "Use the string 'none' (NOT Python None) if no era filter is needed. "
            "Always use 'none' when collection='sc_judgments'."
        ),
    )
    top_k: int = Field(5, description="Number of results to return (default 5, max 15)")
    rerank: bool = Field(True, description="Apply cross-encoder reranking after RRF fusion")
    collection: str = Field(
        "legal_sections",
        description=(
            "Which Qdrant collection to search. "
            "'legal_sections' (default) — statutory text from BNS/BNSS/BSA/IPC/CrPC and civil acts. "
            "'sc_judgments' — Supreme Court judgment chunks including 2024 and 2025 decisions. "
            "Use 'sc_judgments' for precedents, case law, and judicial interpretation of any statute. "
            "Use act_filter='none' and era_filter='none' when collection='sc_judgments'."
        ),
    )
    query_type: str = Field(
        "default",
        description=(
            "Query type from QueryClassifierTool output. Controls RRF weight distribution. "
            "Options: 'section_lookup' (keyword-exact, e.g. 'what does BNS 103 say'), "
            "'criminal_offence' (criminal substantive queries), "
            "'civil_conceptual' (civil/property/family/consumer conceptual queries), "
            "'procedural' (FIR filing, bail procedure, court steps), "
            "'old_statute' (IPC/CrPC references after normalization), "
            "'default' (constitutional, evidence, general). "
            "Pass the Query Type field directly from QueryClassifierTool classification."
        ),
    )
    mmr_diversity: float = Field(
        0.0,
        description=(
            "Maximal Marginal Relevance diversity [0.0–1.0]. "
            "0.0 = pure relevance (default, use for criminal/police/lawyer queries). "
            "0.3 = recommended for layman civil/property queries — forces results from "
            "multiple acts (e.g. both TPA and ICA sections for a tenancy query). "
            "Do NOT use for sc_judgments collection."
        ),
    )


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------

class QdrantHybridSearchTool(BaseTool):
    """Search the Neethi AI legal database using hybrid dense+sparse retrieval.

    Executes BGE-M3 dense search + BM25 sparse search, merges with Reciprocal
    Rank Fusion (RRF k=60), then optionally reranks with a cross-encoder.

    Two collections are supported:
        legal_sections  — BNS/BNSS/BSA/IPC/CrPC/civil act statutory sections (default)
        sc_judgments    — Supreme Court judgment chunks including 2024–2025 decisions

    IMPORTANT: Call StatuteNormalizationTool BEFORE this tool whenever the
    query mentions old statutes (IPC, CrPC, IEA). Use the normalized section
    references (BNS/BNSS/BSA) in the query and act_filter, not the old ones.

    Usage::

        tool = QdrantHybridSearchTool()
        # Statutory search (default)
        result = tool.run({
            "query": "punishment for murder",
            "act_filter": "BNS_2023",
            "era_filter": "naveen_sanhitas",
            "top_k": 5,
        })
        # Precedent search
        result = tool.run({
            "query": "anticipatory bail domestic violence precedent",
            "act_filter": "none",
            "era_filter": "none",
            "top_k": 3,
            "collection": "sc_judgments",
        })
    """

    name: str = "QdrantHybridSearchTool"
    description: str = (
        "Search the Indian legal database using hybrid semantic + keyword retrieval. "
        "Input: {query: str, act_filter: str, era_filter: str, top_k: int, rerank: bool, collection: str}. "
        "ALWAYS include act_filter and era_filter — use the string 'none' (not Python None) when no filter is needed. "
        "Example statutory:  act_filter='BNS_2023', era_filter='naveen_sanhitas', collection='legal_sections'. "
        "Example precedent:  act_filter='none', era_filter='none', collection='sc_judgments'. "
        "IMPORTANT: Run StatuteNormalizationTool first if query contains IPC/CrPC/IEA references. "
        "Output: ranked list of results — statutory sections OR Supreme Court judgment chunks depending on collection."
    )
    args_schema: type[BaseModel] = QdrantSearchInput

    def _run(  # type: ignore[override]
        self,
        query: str | dict,
        act_filter: str = "none",
        era_filter: str = "none",
        legal_domain_filter: Optional[str] = None,  # kept for direct-call compat; ignored by agent
        top_k: int = 5,
        rerank: bool = True,
        collection: str = "legal_sections",
        query_type: str = "default",
        mmr_diversity: float = 0.0,
    ) -> str:
        """Execute hybrid search and return formatted results.

        Synchronous — CrewAI's BaseTool.run() calls _run() synchronously from a
        thread pool executor.  Declaring _run as async def causes CrewAI to receive
        a coroutine object instead of a result, which it then tries to execute via
        asyncio.run() — failing with 'cannot be called from a running event loop'
        because uvicorn's loop is already running.

        Uses the synchronous HybridSearcher.search() method (sync Qdrant client,
        blocking embedding) which works correctly from any thread without needing
        an event loop.

        Handles both dict input (direct calls) and keyword args (CrewAI agent calls).

        act_filter / era_filter accept the sentinel string 'none' (or empty string)
        to mean no filter — required because Groq's tool validation enforces all
        schema fields to be present and typed as plain str avoids Optional issues.
        """
        # Handle dict input
        if isinstance(query, dict):
            act_filter = query.get("act_filter", "none")
            era_filter = query.get("era_filter", "none")
            legal_domain_filter = query.get("legal_domain_filter")
            top_k = query.get("top_k", 5)
            rerank = query.get("rerank", True)
            collection = query.get("collection", "legal_sections")
            query_type = query.get("query_type", "default")
            mmr_diversity = float(query.get("mmr_diversity", 0.0))
            query = query.get("query", "")

        # Normalize sentinel 'none' → Python None
        act_filter_norm = _normalize_filter(act_filter)
        era_filter_norm = _normalize_filter(era_filter)
        # legal_domain_filter intentionally ignored (domain values in indexed data
        # don't match LLM-generated values — always returns 0 results)

        top_k = min(max(1, top_k), 15)  # Clamp to [1, 15]

        # Validate collection
        valid_collections = {"legal_sections", "sc_judgments", "legal_sub_sections"}
        if collection not in valid_collections:
            logger.warning("qdrant_search: unknown collection %r — falling back to legal_sections", collection)
            collection = "legal_sections"

        # Clamp mmr_diversity to valid range
        mmr_diversity = max(0.0, min(1.0, float(mmr_diversity)))

        logger.info(
            "qdrant_search: query=%r act=%s era=%s top_k=%d rerank=%s collection=%s query_type=%s mmr=%.1f",
            query[:60], act_filter_norm, era_filter_norm, top_k, rerank, collection, query_type, mmr_diversity,
        )

        # --- Get searcher ---
        searcher = _get_searcher()
        if searcher is None:
            return (
                "SEARCH UNAVAILABLE: FlagEmbedding (BGE-M3) is not installed on this machine. "
                "Run the search on a GPU instance (Lightning AI) where FlagEmbedding is available. "
                "Install with: pip install FlagEmbedding"
            )

        # --- Execute synchronous hybrid search ---
        # Uses the sync Qdrant client — safe to call from any thread without an event loop.
        try:
            results = searcher.search(
                query=query,
                act_filter=act_filter_norm,
                era_filter=era_filter_norm,
                legal_domain_filter=None,  # always None — domain values don't match indexed data
                collection=collection,
                top_k=top_k * 2 if rerank else top_k,  # Fetch more for reranker
                query_type=query_type,
                mmr_diversity=mmr_diversity,
            )
        except Exception as exc:
            logger.exception("qdrant_search: search failed: %s", exc)
            return f"SEARCH ERROR: {exc}"

        if not results:
            return (
                f"SEARCH RESULTS: 0 results found for query: {query!r}\n"
                f"Collection: {collection}\n"
                f"Filters applied: act={act_filter}, era={era_filter}\n"
                "Consider broadening filters or rephrasing the query."
            )

        # --- Optional cross-encoder reranking ---
        if rerank:
            reranker = _get_reranker()
            if reranker is not None:
                try:
                    results = reranker.rerank(query=query, results=results, top_k=top_k)
                except Exception as exc:
                    logger.warning("qdrant_search: reranking failed (%s) — using RRF order", exc)
                    results = results[:top_k]
            else:
                results = results[:top_k]

        # --- Format output for agent ---
        return _format_results(query, results, act_filter_norm, era_filter_norm, collection)


# ---------------------------------------------------------------------------
# Output formatter
# ---------------------------------------------------------------------------

def _format_results(
    query: str,
    results: list,
    act_filter: Optional[str],
    era_filter: Optional[str],
    collection: str = "legal_sections",
) -> str:
    """Format retrieval results as a readable string for the agent.

    Detects whether results are statutory sections or SC judgment chunks
    and formats accordingly. Judgment chunks are identified by the presence
    of a non-empty 'diary_no' field in the payload.
    """
    lines = [
        f"SEARCH RESULTS: {len(results)} result(s) for query: {query!r}",
        f"Collection: {collection}",
    ]
    if act_filter or era_filter:
        filters = ", ".join(f for f in [act_filter, era_filter] if f)
        lines.append(f"Filters: {filters}")
    lines.append("")

    for i, r in enumerate(results, start=1):
        payload = r.payload or {}
        score = getattr(r, "score", 0.0)

        # Detect result type from payload
        diary_no = payload.get("diary_no", "")
        if diary_no:
            # ── SC Judgment chunk ────────────────────────────────────────────
            case_name = payload.get("case_name", "Unknown Case")
            year = payload.get("year", "")
            disposal = payload.get("disposal_nature", "")
            section_type = payload.get("section_type", "")
            chunk_idx = payload.get("chunk_index", "?")
            total_chunks = payload.get("total_chunks", "?")
            legal_domain = payload.get("legal_domain", "")

            header = f"[{i}] {case_name}"
            if year:
                header += f" ({year})"
            if disposal:
                header += f" — {disposal}"
            header += f"  (score: {score:.4f})"
            lines.append(header)

            # Text preview
            text = (r.text or "").strip()
            if text:
                preview = text[:400].replace("\n", " ")
                if len(text) > 400:
                    preview += "..."
                lines.append(f"    {preview}")

            # Key judgment metadata
            meta_parts = [f"diary_no={diary_no}", f"chunk={chunk_idx}/{total_chunks}"]
            if section_type:
                meta_parts.append(f"type={section_type}")
            if legal_domain:
                meta_parts.append(f"domain={legal_domain}")
            ik_url = payload.get("ik_url", "")
            if ik_url:
                meta_parts.append(f"url={ik_url}")
            lines.append(f"    [{', '.join(meta_parts)}]")

        else:
            # ── Statutory Section ────────────────────────────────────────────
            act = r.act_code or "Unknown"
            sec = r.section_number or "?"
            title = r.section_title or ""

            header = f"[{i}] {act} s.{sec}"
            if title:
                header += f' — "{title}"'
            header += f"  (score: {score:.4f})"
            lines.append(header)

            # Text preview
            text = (r.text or "").strip()
            if text:
                preview = text[:300].replace("\n", " ")
                if len(text) > 300:
                    preview += "..."
                lines.append(f"    {preview}")

            # Key statutory metadata
            meta_parts = []
            era = payload.get("era") or r.era
            if era:
                meta_parts.append(f"era={era}")
            is_offence = payload.get("is_offence")
            if is_offence is not None:
                meta_parts.append(f"offence={is_offence}")
            is_bailable = payload.get("is_bailable")
            if is_bailable is not None:
                meta_parts.append(f"bailable={is_bailable}")
            triable = payload.get("triable_by")
            if triable:
                meta_parts.append(f"court={triable}")
            if meta_parts:
                lines.append(f"    [{', '.join(meta_parts)}]")

        lines.append("")

    return "\n".join(lines)
