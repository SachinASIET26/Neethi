"""Neethi AI — FastAPI application entry point.

Start the server:
    uvicorn backend.main:app --reload --reload-dir backend --port 8000 --loop asyncio

Or with Gunicorn (production):
    gunicorn backend.main:app -w 4 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000

IMPORTANT FLAGS:
    --loop asyncio      Required — CrewAI nest_asyncio cannot patch uvloop
    --reload-dir backend  Required — prevents reloader watching frontend/node_modules/
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager

# Load .env early so all os.getenv() calls see the values.
# Use an explicit path so it works regardless of CWD.
try:
    from pathlib import Path
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Redis reachability pre-check — MUST run before crewai is imported.
#
# CrewAI's lock_store.py reads REDIS_URL from os.environ at module import
# time (eagerly, when 'import crewai' is called). If REDIS_URL is set but
# Redis is unreachable, every crew.akickoff() raises "Error 111 connection
# refused" because portalocker.RedisLock tries a synchronous connection.
#
# Fix: do a cheap synchronous socket probe here, before the crewai import
# below. If Redis is unreachable, clear REDIS_URL so crewai falls back to
# file-based locking. Our ResponseCache already has its own fallback logic
# and is not affected by this unset.
# ---------------------------------------------------------------------------
def _probe_redis_reachable() -> bool:
    """Return True if REDIS_URL is set and the host:port is TCP-reachable."""
    import socket
    url = os.getenv("REDIS_URL", "")
    if not url:
        return False
    try:
        # Parse host and port from redis:// or rediss:// URL
        import urllib.parse
        parsed = urllib.parse.urlparse(url)
        host = parsed.hostname or "localhost"
        port = parsed.port or 6379
        with socket.create_connection((host, port), timeout=1):
            return True
    except Exception:
        return False

_redis_url_set = bool(os.getenv("REDIS_URL"))
if _redis_url_set and not _probe_redis_reachable():
    # Redis is configured but unreachable. Clear the env var so crewai's
    # lock_store uses file-based locking instead of attempting Redis.
    # ResponseCache will handle its own graceful fallback independently.
    _removed_redis_url = os.environ.pop("REDIS_URL", None)
    import logging as _log
    _log.getLogger(__name__).warning(
        "startup: REDIS_URL is set but Redis is unreachable — "
        "clearing REDIS_URL so CrewAI uses file-based locking. "
        "ResponseCache will use in-memory fallback."
    )

# NOTE: nest_asyncio is intentionally NOT applied here.
# CrewAI v1.9.x internally calls nest_asyncio.apply() during akickoff().
# nest_asyncio cannot patch uvloop (uvicorn[standard] default).
# Start uvicorn with --loop asyncio to use the standard event loop:
#   uvicorn backend.main:app --host 0.0.0.0 --port 8000 --loop asyncio

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from backend.api.routes import admin, auth, cases, conversation, documents, document_analysis, query, resources, sections, translate, voice
from backend.db.database import create_all_tables
from backend.services.cache import ResponseCache

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lifespan — startup / shutdown
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run startup tasks before serving requests, cleanup on shutdown."""
    # Create DB tables (dev/test only — use Alembic migrations in production)
    if os.getenv("ENVIRONMENT", "development") == "development":
        try:
            await create_all_tables()
            logger.info("Database tables verified.")
        except Exception as exc:
            logger.warning("create_all_tables failed (non-fatal): %s", exc)

    # Warm up cache connection
    cache = ResponseCache()
    app.state.cache = cache
    cache_health = await cache.health()
    logger.info("Cache status: %s", cache_health.get("status", "unknown"))

    # Pre-warm BGE-M3 embedder and CrossEncoder reranker in a thread executor.
    # These models download on first use (~2.3 GB BGE-M3 + ~90 MB CrossEncoder)
    # and take 10-15 seconds to load. Loading them here — before any request
    # arrives — prevents the first streaming request from blocking mid-stream
    # (which causes ECONNRESET on the Next.js proxy side).
    loop = asyncio.get_event_loop()

    def _warm_models():
        try:
            from backend.rag.embeddings import BGEM3Embedder
            app.state.embedder = BGEM3Embedder()
            logger.info("BGE-M3 embedder ready.")
        except Exception as exc:
            logger.warning("BGE-M3 warmup failed (non-fatal): %s", exc)
            app.state.embedder = None

        try:
            from backend.rag.reranker import get_reranker
            app.state.reranker = get_reranker()
            logger.info("CrossEncoder reranker ready.")
        except Exception as exc:
            logger.warning("CrossEncoder warmup failed (non-fatal): %s", exc)
            app.state.reranker = None

    await loop.run_in_executor(None, _warm_models)

    logger.info("Neethi AI API ready.")
    yield
    # Shutdown (add cleanup here if needed)
    logger.info("Neethi AI API shutting down.")


# ---------------------------------------------------------------------------
# App instance
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Neethi AI Legal API",
    description=(
        "Indian Legal Domain Agentic AI — citation-verified, hallucination-free.\n\n"
        "**Core principle:** In legal, a wrong answer is worse than no answer. "
        "Every response is source-cited and double-verified.\n\n"
        "**Supported user roles:** citizen | lawyer | legal_advisor | police"
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

# 1. CORS
# On Lightning AI set: CORS_ORIGINS="*"
# Wildcard requires allow_credentials=False (JWT Authorization header still works fine)
_raw_cors = os.getenv("CORS_ORIGINS", "http://localhost:3000,https://neethiai.com")
if _raw_cors.strip() == "*":
    _CORS_ORIGINS = ["*"]
    _CORS_CREDENTIALS = False   # required by Starlette when origins=["*"]
else:
    _CORS_ORIGINS = [o.strip() for o in _raw_cors.split(",")]
    _CORS_CREDENTIALS = True

app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_credentials=_CORS_CREDENTIALS,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 2. Request ID + timing
@app.middleware("http")
async def request_id_and_timing(request: Request, call_next):
    request_id = uuid.uuid4().hex[:8]
    request.state.request_id = request_id
    start = time.time()
    response: Response = await call_next(request)
    elapsed_ms = int((time.time() - start) * 1000)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Response-Time-Ms"] = str(elapsed_ms)
    return response


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

PREFIX = "/api/v1"

app.include_router(auth.router,      prefix=f"{PREFIX}/auth",      tags=["Authentication"])
app.include_router(query.router,     prefix=f"{PREFIX}/query",     tags=["Legal Query"])
app.include_router(cases.router,     prefix=f"{PREFIX}/cases",     tags=["Case Law"])
app.include_router(documents.router, prefix=f"{PREFIX}/documents", tags=["Document Drafting"])
app.include_router(sections.router,  prefix=f"{PREFIX}/sections",  tags=["Acts & Sections"])
app.include_router(resources.router, prefix=f"{PREFIX}/resources", tags=["Legal Resources"])
app.include_router(translate.router, prefix=f"{PREFIX}/translate", tags=["Translation"])
app.include_router(voice.router,     prefix=f"{PREFIX}/voice",     tags=["Voice (TTS/STT)"])
app.include_router(admin.router,     prefix=f"{PREFIX}/admin",     tags=["Admin"])
app.include_router(conversation.router, prefix=f"{PREFIX}/conversation", tags=["Conversation"])
app.include_router(document_analysis.router, prefix=f"{PREFIX}/documents", tags=["Document Analysis"])


# ---------------------------------------------------------------------------
# Root health check (no auth required)
# ---------------------------------------------------------------------------

@app.get("/", tags=["Health"], include_in_schema=False)
async def root():
    return {
        "service": "Neethi AI Legal API",
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs",
    }


@app.get("/health", tags=["Health"])
async def public_health():
    """Quick health check — no auth required. Returns 200 when API is up."""
    return {"status": "healthy", "service": "neethi-ai"}
