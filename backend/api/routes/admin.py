"""Admin routes — health, ingestion, cache, Mistral fallback, user mgmt, stats."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.dependencies import get_cache, require_role
from backend.db.database import get_db
from backend.api.schemas.admin import (
    ActivityItem,
    ActivityResponse,
    AdminStats,
    CacheFlushRequest,
    CacheFlushResponse,
    ComponentHealth,
    HealthResponse,
    IngestResponse,
    JobStatus,
    MistralFallbackRequest,
    MistralFallbackResponse,
    RoleCount,
    UserDetail,
    UserListItem,
    UserListResponse,
    UserUpdateRequest,
)
from backend.db.models.user import Draft, QueryLog, User
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


# ---------------------------------------------------------------------------
# GET /admin/users
# ---------------------------------------------------------------------------

@router.get("/users", response_model=UserListResponse)
async def list_users(
    role: Optional[str] = Query(None, description="Filter by role"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    search: Optional[str] = Query(None, description="Search name or email"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """List all users with optional filters."""
    query = select(User)

    if role:
        query = query.where(User.role == role)
    if is_active is not None:
        query = query.where(User.is_active == is_active)
    if search:
        pattern = f"%{search}%"
        query = query.where(
            User.full_name.ilike(pattern) | User.email.ilike(pattern)
        )

    # Total count
    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    # Fetch page
    query = query.order_by(User.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(query)
    users = result.scalars().all()

    return UserListResponse(
        total=total,
        users=[
            UserListItem(
                user_id=str(u.id),
                full_name=u.full_name,
                email=u.email,
                role=u.role,
                is_active=u.is_active,
                is_email_verified=u.is_email_verified,
                query_count_today=u.query_count_today,
                created_at=u.created_at,
                updated_at=u.updated_at,
            )
            for u in users
        ],
    )


# ---------------------------------------------------------------------------
# GET /admin/users/{user_id}
# ---------------------------------------------------------------------------

@router.get("/users/{user_id}", response_model=UserDetail)
async def get_user(
    user_id: str,
    _: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Get detailed info for a single user."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404, detail="User not found.")

    # Count queries
    q_count = (await db.execute(
        select(func.count()).select_from(QueryLog).where(QueryLog.user_id == user.id)
    )).scalar() or 0

    # Count drafts
    d_count = (await db.execute(
        select(func.count()).select_from(Draft).where(Draft.user_id == user.id)
    )).scalar() or 0

    return UserDetail(
        user_id=str(user.id),
        full_name=user.full_name,
        email=user.email,
        role=user.role,
        is_active=user.is_active,
        is_email_verified=user.is_email_verified,
        bar_council_id=user.bar_council_id,
        police_badge_id=user.police_badge_id,
        organization=user.organization,
        query_count_today=user.query_count_today,
        total_queries=q_count,
        total_drafts=d_count,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


# ---------------------------------------------------------------------------
# PATCH /admin/users/{user_id}
# ---------------------------------------------------------------------------

@router.patch("/users/{user_id}", response_model=UserDetail)
async def update_user(
    user_id: str,
    request: UserUpdateRequest,
    _: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Update a user's role or active status."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404, detail="User not found.")

    if request.role is not None:
        user.role = request.role
    if request.is_active is not None:
        user.is_active = request.is_active

    await db.commit()
    await db.refresh(user)

    # Re-fetch counts for response
    q_count = (await db.execute(
        select(func.count()).select_from(QueryLog).where(QueryLog.user_id == user.id)
    )).scalar() or 0
    d_count = (await db.execute(
        select(func.count()).select_from(Draft).where(Draft.user_id == user.id)
    )).scalar() or 0

    return UserDetail(
        user_id=str(user.id),
        full_name=user.full_name,
        email=user.email,
        role=user.role,
        is_active=user.is_active,
        is_email_verified=user.is_email_verified,
        bar_council_id=user.bar_council_id,
        police_badge_id=user.police_badge_id,
        organization=user.organization,
        query_count_today=user.query_count_today,
        total_queries=q_count,
        total_drafts=d_count,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


# ---------------------------------------------------------------------------
# GET /admin/stats
# ---------------------------------------------------------------------------

@router.get("/stats", response_model=AdminStats)
async def get_admin_stats(
    _: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Aggregate dashboard statistics."""
    # Total & active users
    total_users = (await db.execute(select(func.count()).select_from(User))).scalar() or 0
    active_users = (await db.execute(
        select(func.count()).select_from(User).where(User.is_active == True)
    )).scalar() or 0

    # Users by role
    role_rows = await db.execute(
        select(User.role, func.count(User.id).label("cnt")).group_by(User.role)
    )
    users_by_role = [RoleCount(role=r.role, count=r.cnt) for r in role_rows]

    # Queries today
    from datetime import date
    today_start = datetime.combine(date.today(), datetime.min.time()).replace(tzinfo=timezone.utc)
    queries_today = (await db.execute(
        select(func.count()).select_from(QueryLog).where(QueryLog.created_at >= today_start)
    )).scalar() or 0

    # All-time queries
    queries_all = (await db.execute(
        select(func.count()).select_from(QueryLog)
    )).scalar() or 0

    # Total drafts
    total_drafts = (await db.execute(
        select(func.count()).select_from(Draft)
    )).scalar() or 0

    # Recent signups (last 7 days)
    seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
    recent_signups = (await db.execute(
        select(func.count()).select_from(User).where(User.created_at >= seven_days_ago)
    )).scalar() or 0

    return AdminStats(
        total_users=total_users,
        active_users=active_users,
        users_by_role=users_by_role,
        total_queries_today=queries_today,
        total_queries_all_time=queries_all,
        total_drafts=total_drafts,
        recent_signups_7d=recent_signups,
    )


# ---------------------------------------------------------------------------
# GET /admin/activity
# ---------------------------------------------------------------------------

@router.get("/activity", response_model=ActivityResponse)
async def get_activity(
    role: Optional[str] = Query(None, description="Filter by user role"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    _: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """System-wide query activity log."""
    query = select(QueryLog, User).join(User, QueryLog.user_id == User.id)

    if role:
        query = query.where(User.role == role)

    # Total count
    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    # Fetch page
    query = query.order_by(QueryLog.created_at.desc()).offset(offset).limit(limit)
    rows = (await db.execute(query)).all()

    return ActivityResponse(
        total=total,
        activities=[
            ActivityItem(
                query_id=str(ql.id),
                user_id=str(u.id),
                user_name=u.full_name,
                user_email=u.email,
                user_role=u.role,
                query_text=ql.query_text,
                verification_status=ql.verification_status,
                confidence=ql.confidence,
                processing_time_ms=ql.processing_time_ms,
                cached=ql.cached,
                created_at=ql.created_at,
            )
            for ql, u in rows
        ],
    )
