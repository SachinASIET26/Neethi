"""Neethi AI — FastAPI application entry point.

Start the server:
    uvicorn backend.main:app --reload --port 8000

Or with Gunicorn (production):
    gunicorn backend.main:app -w 4 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from contextlib import asynccontextmanager

# Load .env early so all os.getenv() calls see the values
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# NOTE: nest_asyncio is intentionally NOT applied here.
# CrewAI v1.9.x internally calls nest_asyncio.apply() during akickoff().
# nest_asyncio cannot patch uvloop (uvicorn[standard] default).
# Start uvicorn with --loop asyncio to use the standard event loop:
#   uvicorn backend.main:app --host 0.0.0.0 --port 8000 --loop asyncio

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from backend.api.routes import admin, auth, cases, documents, query, resources, sections, translate, voice
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
_CORS_ORIGINS = os.getenv(
    "CORS_ORIGINS",
    "http://localhost:3000,https://neethiai.com",
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _CORS_ORIGINS],
    allow_credentials=True,
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
