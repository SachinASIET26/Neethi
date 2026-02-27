"""Admin routes — health, ingestion, cache, Mistral fallback toggle."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from backend.api.dependencies import get_cache, require_role
from backend.api.schemas.admin import (
    CacheFlushRequest,
    CacheFlushResponse,
    ComponentHealth,
    HealthResponse,
    IngestResponse,
    JobStatus,
    MistralFallbackRequest,
    MistralFallbackResponse,
)
from backend.db.models.user import User
from backend.services.cache import ResponseCache

router = APIRouter()

# In-memory job tracker (use Redis for multi-process deployments)
_jobs: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# GET /admin/health
# ---------------------------------------------------------------------------

@router.get("/health", response_model=HealthResponse)
async def health_check(
    _: User = Depends(require_role("admin")),
    cache: ResponseCache = Depends(get_cache),
):
    """Full system health check — all dependencies."""
    import os, time

    components: dict[str, ComponentHealth] = {}
    overall = "healthy"

    # --- Database ---
    try:
        from backend.db.database import health_check as db_health
        t0 = time.time()
        db_ok = await db_health()
        latency = int((time.time() - t0) * 1000)
        components["database"] = ComponentHealth(
            status="healthy" if db_ok else "unavailable", latency_ms=latency
        )
        if not db_ok:
            overall = "degraded"
    except Exception as exc:
        components["database"] = ComponentHealth(status="unavailable", error=str(exc))
        overall = "degraded"

    # --- Qdrant ---
    try:
        from qdrant_client import QdrantClient
        t0 = time.time()
        qclient = QdrantClient(
            url=os.getenv("QDRANT_URL", "http://localhost:6333"),
            api_key=os.getenv("QDRANT_API_KEY"),
        )
        collections = [c.name for c in qclient.get_collections().collections]
        latency = int((time.time() - t0) * 1000)
        components["qdrant"] = ComponentHealth(
            status="healthy", latency_ms=latency, collections=collections
        )
    except Exception as exc:
        components["qdrant"] = ComponentHealth(
            status="unavailable", error=str(exc),
            impact="Retrieval disabled — no sections or judgments can be searched"
        )
        overall = "degraded"

    # --- Redis ---
    try:
        cache_health = await cache.health()
        components["redis"] = ComponentHealth(
            status=cache_health.get("status", "unknown"),
            latency_ms=cache_health.get("latency_ms"),
        )
        if cache_health.get("status") != "healthy":
            overall = "degraded"
    except Exception as exc:
        components["redis"] = ComponentHealth(
            status="unavailable", error=str(exc),
            impact="Caching disabled — higher latency"
        )

    # --- Groq ---
    groq_key = os.getenv("GROQ_API_KEY", "")
    components["groq_api"] = ComponentHealth(
        status="healthy" if groq_key else "unconfigured",
        error=None if groq_key else "GROQ_API_KEY not set",
    )

    # --- Mistral ---
    mistral_key = os.getenv("MISTRAL_API_KEY", "")
    components["mistral_api"] = ComponentHealth(
        status="healthy" if mistral_key else "unconfigured",
        error=None if mistral_key else "MISTRAL_API_KEY not set",
    )

    # --- Anthropic ---
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
    components["anthropic_api"] = ComponentHealth(
        status="healthy" if anthropic_key else "unconfigured",
    )

    # --- Sarvam (voice / translate) ---
    sarvam_key = os.getenv("SARVAM_API_KEY", "")
    components["sarvam_api"] = ComponentHealth(
        status="healthy" if sarvam_key else "unconfigured",
        error=None if sarvam_key else "SARVAM_API_KEY not set — voice and translation disabled",
    )

    # --- Indexed section counts ---
    indexed: dict[str, int] = {}
    try:
        from sqlalchemy import select, func
        from backend.db.database import AsyncSessionLocal
        from backend.db.models.legal_foundation import Section

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Section.act_code, func.count(Section.id).label("cnt"))
                .where(Section.qdrant_indexed == True)
                .group_by(Section.act_code)
            )
            indexed = {row.act_code: row.cnt for row in result}
    except Exception:
        pass

    # --- Mistral fallback status ---
    try:
        from backend.config.llm_config import is_mistral_fallback_active
        fallback_active = is_mistral_fallback_active()
    except Exception:
        fallback_active = False

    return HealthResponse(
        status=overall,
        timestamp=datetime.now(timezone.utc).isoformat(),
        components=components,
        mistral_fallback_active=fallback_active,
        indexed_sections=indexed,
    )


# ---------------------------------------------------------------------------
# POST /admin/ingest
# ---------------------------------------------------------------------------

@router.post("/ingest", response_model=IngestResponse, status_code=202)
async def ingest_document(
    file: UploadFile = File(..., description="PDF legal document (max 50 MB)"),
    act_code: str = Form(..., description="e.g. BNS_2023"),
    document_type: str = Form("statutory", description="statutory | judgment"),
    source_url: str = Form("", description="Official source URL"),
    _: User = Depends(require_role("admin")),
):
    """Trigger ingestion of a new legal document PDF into the pipeline."""
    if file.size and file.size > 50 * 1024 * 1024:
        raise HTTPException(413, detail="File too large. Maximum is 50 MB.")

    ext = (file.filename or "doc.pdf").rsplit(".", 1)[-1].lower()
    if ext != "pdf":
        raise HTTPException(422, detail="Only PDF files are supported.")

    pdf_bytes = await file.read()
    job_id = f"job_{uuid.uuid4().hex[:16]}"

    # Store job state
    _jobs[job_id] = {
        "job_id": job_id,
        "act_code": act_code.upper(),
        "status": "queued",
        "started_at": None,
        "completed_at": None,
        "results": None,
        "error": None,
    }

    # Run ingestion as background task
    import asyncio

    async def _run_ingestion():
        _jobs[job_id]["status"] = "running"
        _jobs[job_id]["started_at"] = datetime.now(timezone.utc).isoformat()
        try:
            import tempfile, os as _os
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp.write(pdf_bytes)
                tmp_path = tmp.name

            from backend.preprocessing.pipeline import run_pipeline
            results = await run_pipeline(tmp_path, act_code=act_code.upper(), source_url=source_url)
            _os.unlink(tmp_path)

            _jobs[job_id]["status"] = "completed"
            _jobs[job_id]["results"] = results
        except Exception as exc:
            _jobs[job_id]["status"] = "failed"
            _jobs[job_id]["error"] = str(exc)
        finally:
            _jobs[job_id]["completed_at"] = datetime.now(timezone.utc).isoformat()

    asyncio.create_task(_run_ingestion())

    return IngestResponse(
        job_id=job_id,
        act_code=act_code.upper(),
        status="queued",
        message=f"Ingestion job queued. Check /admin/jobs/{job_id} for status.",
        estimated_duration_minutes=5,
    )


# ---------------------------------------------------------------------------
# GET /admin/jobs/{job_id}
# ---------------------------------------------------------------------------

@router.get("/jobs/{job_id}", response_model=JobStatus)
async def get_job_status(
    job_id: str,
    _: User = Depends(require_role("admin")),
):
    """Check the status of an ingestion job."""
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(404, detail=f"Job '{job_id}' not found.")
    return JobStatus(**job)


# ---------------------------------------------------------------------------
# POST /admin/cache/flush
# ---------------------------------------------------------------------------

@router.post("/cache/flush", response_model=CacheFlushResponse)
async def flush_cache(
    request: CacheFlushRequest,
    _: User = Depends(require_role("admin")),
    cache: ResponseCache = Depends(get_cache),
):
    """Flush the Redis response cache by role, or entirely."""
    if request.role == "all":
        # Flush all known roles
        total = 0
        for role in ("citizen", "lawyer", "legal_advisor", "police"):
            total += await cache.flush_role(role)
        return CacheFlushResponse(flushed_keys=total, role="all")
    else:
        count = await cache.flush_role(request.role)
        return CacheFlushResponse(flushed_keys=count, role=request.role)


# ---------------------------------------------------------------------------
# POST /admin/mistral-fallback
# ---------------------------------------------------------------------------

@router.post("/mistral-fallback", response_model=MistralFallbackResponse)
async def toggle_mistral_fallback(
    request: MistralFallbackRequest,
    _: User = Depends(require_role("admin")),
):
    """Toggle Mistral fallback mode (activate when Groq hits TPM limit)."""
    from backend.config.llm_config import set_mistral_fallback

    set_mistral_fallback(request.active)

    if request.active:
        msg = "Mistral fallback ACTIVATED — tool-heavy agents → mistral-large-latest, text-only → mistral-small-latest"
    else:
        msg = "Mistral fallback DEACTIVATED — all agents restored to Groq Llama 3.3 70B"

    return MistralFallbackResponse(
        mistral_fallback_active=request.active,
        message=msg,
    )
