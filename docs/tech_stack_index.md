# Tech Stack Documentation Index
## Neethi AI — Indian Legal Domain Agentic AI System

> **Last Updated:** 2026-03-23
> **Versions below are exact pinned versions from `requirements.txt` as of this date.**
> **Python:** 3.12 | **Platform:** Lightning AI (CUDA 12.8) / Linux

---

## Table of Contents

1. [Qdrant — Vector Database for RAG](#1-qdrant--vector-database-for-rag)
2. [FastAPI — Python API Framework](#2-fastapi--python-api-framework)
3. [CrewAI — Multi-Agent AI Framework](#3-crewai--multi-agent-ai-framework)
4. [Next.js / React — Frontend](#4-nextjs--react--frontend)
5. [LLM Providers (Mistral / Groq / DeepSeek / Anthropic)](#5-llm-providers)
6. [FlagEmbedding BGE-M3 — Embeddings](#6-flagembedding-bge-m3--embeddings)
7. [Sarvam AI — Indian Language Support](#7-sarvam-ai--indian-language-support)
8. [Thesys API — Visual UI Components](#8-thesys-api--visual-ui-components)
9. [SERP API — Legal Resource Discovery](#9-serp-api--legal-resource-discovery)
10. [PyMuPDF + pdfplumber — PDF Processing](#10-pymupdf--pdfplumber--pdf-processing)
11. [Jinja2 + WeasyPrint + ReportLab — Document Generation](#11-jinja2--weasyprint--reportlab--document-generation)
12. [PostgreSQL / SQLAlchemy — Database](#12-postgresql--sqlalchemy--database)
13. [Redis — Caching](#13-redis--caching)
14. [Integration Architecture Overview](#14-integration-architecture-overview)
15. [Package Version Reference](#15-package-version-reference)

---

## 1. Qdrant — Vector Database for RAG

### Role in Neethi
Stores BGE-M3 dense (1024d) and sparse (BM25) vector embeddings of Indian legal documents. Powers hybrid search with Reciprocal Rank Fusion (RRF) across three collections.

### Installed Version
- **Python Client:** `qdrant-client==1.12.0`

### Documentation

| Resource | URL |
|---|---|
| Official Docs | https://qdrant.tech/documentation/ |
| Python Client | https://python-client.qdrant.tech/ |
| GitHub | https://github.com/qdrant/qdrant |

### Collections in Neethi

| Collection | Purpose | Vectors |
|---|---|---|
| `legal_documents` | Main retrieval — BNS, BNSS, BSA, SC judgments | Dense 1024d + Sparse BM25 |
| `legal_sections` | Citation verification lookups | Dense 1024d + Sparse BM25 |
| `document_templates` | Drafting template retrieval | Dense 1024d |

### Integration Pattern (Direct — no LangChain)

```python
from qdrant_client import QdrantClient, AsyncQdrantClient
from qdrant_client.models import NamedVector, NamedSparseVector

# Async client used in FastAPI endpoints
client = AsyncQdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)

# Hybrid search with prefetch (dense + sparse)
results = await client.query_points(
    collection_name="legal_documents",
    prefetch=[
        Prefetch(query=dense_vector, using="dense", limit=top_k * 4),
        Prefetch(query=SparseVector(indices=sparse_indices, values=sparse_values),
                 using="sparse", limit=top_k * 4),
    ],
    query=FusionQuery(fusion=Fusion.RRF),
    limit=top_k,
    query_filter=payload_filter,
)
```

### Key Configuration Notes
- Always create payload indexes on filter fields: `act_code`, `section_number`, `legal_domain`, `user_access_level`
- Scalar INT8 quantization enabled on `legal_documents` to reduce VRAM usage
- Batch upsert: keep under 100 points per call when including large sparse vectors
- See `backend/rag/qdrant_setup.py` for collection initialization

---

## 2. FastAPI — Python API Framework

### Role in Neethi
REST API backend with JWT auth, SSE streaming for agent responses, CORS for Next.js frontend, and async Qdrant/Redis access.

### Installed Version
- **FastAPI:** `0.115.6`
- **Uvicorn (ASGI):** `0.34.0` (with standard extras — websockets, httptools)
- **python-multipart:** `0.0.20`

### Documentation

| Resource | URL |
|---|---|
| Official Docs | https://fastapi.tiangolo.com/ |
| GitHub | https://github.com/fastapi/fastapi |

### Startup Pattern

```python
# backend/main.py
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_all_tables()           # Dev only — use Alembic in prod
    app.state.cache = ResponseCache()   # Redis warmup
    yield

app = FastAPI(lifespan=lifespan)
```

### Start Command

```bash
# Development
uvicorn backend.main:app --reload --port 8000 --loop asyncio

# IMPORTANT: --loop asyncio is required — CrewAI akickoff() uses nest_asyncio
# which cannot patch uvloop (uvicorn's default). Use asyncio loop.

# Production
gunicorn backend.main:app -w 4 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000
```

### Gotchas
- Always use `--loop asyncio` — uvloop breaks CrewAI's nested async pattern
- CORS: set `CORS_ORIGINS=*` on Lightning AI (with `allow_credentials=False`)
- Pydantic v2 syntax is required: `model_validator`, `ConfigDict`, `model_fields`
- SSE: use `sse-starlette` (`EventSourceResponse`) for streaming responses

---

## 3. CrewAI — Multi-Agent AI Framework

### Role in Neethi
Orchestrates sequential agent pipelines per user role. Each crew runs: Query Analyst → [Retrieval] → [Legal Reasoner] → Citation Verifier → Response Formatter.

### Installed Version
- **CrewAI:** `1.11.0`
- **Dependency managed:** litellm, openai, tokenizers (via crewai)

### Documentation

| Resource | URL |
|---|---|
| Official Docs | https://docs.crewai.com/ |
| GitHub | https://github.com/crewAIInc/crewAI |

### Crew Definition Pattern

```python
from crewai import Agent, Task, Crew, Process

query_analyst = Agent(
    role="Indian Legal Query Analyst",
    goal="Classify and decompose the user's legal query",
    backstory="Expert in Indian legal domain classification...",
    tools=[query_classifier_tool, statute_normalization_tool],
    llm=get_llm_config(),   # Mistral → Groq → DeepSeek chain
    verbose=False,
)

crew = Crew(
    agents=[query_analyst, retrieval_specialist, citation_verifier, formatter],
    tasks=[classify_task, retrieve_task, verify_task, format_task],
    process=Process.sequential,
    verbose=False,
)

# Async kickoff (in FastAPI endpoints)
result = await crew.kickoff_async(inputs={"query": user_query, "role": user_role})
```

### Crew Configurations (by Role)

| Role | Crew Factory | Agents |
|---|---|---|
| citizen | `make_layman_crew()` | Analyst → Retrieval → Citation → Formatter |
| lawyer | `make_lawyer_crew()` | Analyst → Retrieval → Reasoner → Citation → Formatter |
| legal_advisor | `make_legal_advisor_crew()` | Analyst → Retrieval → Reasoner → Citation → Formatter |
| police | `make_police_crew()` | Analyst → Retrieval → Citation → Formatter |

See `backend/agents/crew_config.py`.

### Async Notes
- Use `crew.kickoff_async()` inside FastAPI async endpoints
- `nest_asyncio==1.6.0` is required — CrewAI applies it internally during `akickoff()`
- **Always start uvicorn with `--loop asyncio`** — nest_asyncio cannot patch uvloop

---

## 4. Next.js / React — Frontend

### Role in Neethi
Role-based legal dashboard with real-time SSE streaming, document drafting, admin panel, and Thesys visual integration.

### Installed Versions
- **Next.js:** `16.1.6` (App Router)
- **React:** `19.2.3`
- **TypeScript:** `5.9.3`
- **Tailwind CSS:** `4.x`

### Key Packages

| Package | Version | Purpose |
|---|---|---|
| `@crayonai/react-core` | 0.7.7 | AI chat UI components |
| `@crayonai/react-ui` | 0.9.16 | AI chat UI theme layer |
| `@thesysai/genui-sdk` | 0.8.5 | Thesys visual explanations |
| `zustand` | 4.5.x | Global state (auth, UI) |
| `tailwind-merge` | 2.x | Conditional class merging |
| `axios` | 1.x | HTTP client |
| `react-markdown` | 10.x | Render agent markdown responses |
| `recharts` | 3.x | Analytics charts in admin |
| `react-hot-toast` | 2.x | Notifications |

### Installation

```bash
cd frontend
npm install --legacy-peer-deps
# legacy-peer-deps required: @crayonai packages have pinned peer deps
# (tailwind-merge ^2, zustand ^4, zod ^3) while the project tracks newer minor versions
```

### Backend Proxy

`next.config.ts` rewrites all `/api/v1/...` calls to the backend:

```typescript
async rewrites() {
  const backendUrl = process.env.BACKEND_URL || "http://localhost:8000";
  return [
    { source: "/api/v1/:path*", destination: `${backendUrl}/api/v1/:path*` },
    { source: "/health", destination: `${backendUrl}/health` },
  ];
}
```

The browser never sees the backend URL directly.

### Start Command

```bash
npm run dev        # port 3000 (explicit --port 3000 set in package.json)
npm run build      # production build
npm run start      # serve production build
```

---

## 5. LLM Providers

### Role in Neethi
Multi-provider LLM strategy with automatic fallback chain. Selection happens at startup in `backend/config/llm_config.py`.

### Installed Versions
- **anthropic:** `0.40.0`
- **groq:** `1.0.0`
- **litellm:** managed by crewai dependency
- **openai:** managed by crewai dependency

### Provider Chain

| Priority | Provider | Model ID | Key | Use |
|---|---|---|---|---|
| 1 | Mistral AI | `mistral/mistral-large-latest` | `MISTRAL_API_KEY` | Primary for all agent tasks |
| 2 | Groq | `groq/llama-3.3-70b-versatile` | `GROQ_API_KEY` | Fallback — fast, free tier |
| 3 | DeepSeek | `deepseek/deepseek-chat` | `DEEPSEEK_API_KEY` | Fallback |
| Dedicated | Anthropic | `claude-sonnet-4-5-20251001` | `ANTHROPIC_API_KEY` | Document drafting only |

**Why Mistral Large as primary?**
- Reliably follows multi-step tool-use instructions required by CrewAI
- No hard daily token cap (Groq free tier: 100K tokens/day, 12K TPM)
- Competitive performance on structured legal reasoning tasks

### Configuration Pattern

```python
# backend/config/llm_config.py
import os

def get_llm_config() -> str:
    """Returns the LiteLLM model string for the first available provider."""
    if os.getenv("MISTRAL_API_KEY"):
        return "mistral/mistral-large-latest"
    if os.getenv("GROQ_API_KEY"):
        return "groq/llama-3.3-70b-versatile"
    if os.getenv("DEEPSEEK_API_KEY"):
        return "deepseek/deepseek-chat"
    raise RuntimeError("No LLM API key configured. Set MISTRAL_API_KEY, GROQ_API_KEY, or DEEPSEEK_API_KEY.")
```

---

## 6. FlagEmbedding BGE-M3 — Embeddings

### Role in Neethi
Single-model pass that generates both dense (1024-dimensional) and sparse (BM25 token-weight) vectors. Powers Qdrant hybrid search without needing a separate BM25 index.

### Installed Versions
- **FlagEmbedding:** `1.3.5`
- **sentence-transformers:** `5.2.0` (CrossEncoder re-ranking)
- **torch:** `2.8.0+cu128` (pre-installed on Lightning AI)

### Documentation

| Resource | URL |
|---|---|
| FlagEmbedding GitHub | https://github.com/FlagOpen/FlagEmbedding |
| BGE-M3 Paper | https://arxiv.org/abs/2402.03216 |
| HuggingFace Model | https://huggingface.co/BAAI/bge-m3 |

### Usage Pattern

```python
from FlagEmbedding import BGEM3FlagModel

model = BGEM3FlagModel(
    "BAAI/bge-m3",
    use_fp16=True,    # faster on GPU
    device="cuda",    # or "cpu"
)

# Asymmetric embedding: different prefixes for documents vs queries
output = model.encode(
    ["Represent this Indian legal provision for retrieval: Section 103 BNS..."],
    batch_size=12,
    return_dense=True,
    return_sparse=True,
    return_colbert_vecs=False,
)
dense_vector  = output["dense_vecs"][0]        # shape: (1024,)
sparse_vector = output["lexical_weights"][0]   # dict: {token_id: weight}
```

### Notes
- Model downloads ~2.3 GB on first use to `~/.cache/huggingface/hub/`
- On Lightning AI (CUDA 12.8 / torch 2.8.0+cu128): GPU is automatically detected
- **Do not reinstall torch** — the pre-installed CUDA version will be downgraded
- `FlagEmbedding==1.3.5` requires `transformers>=4.44.2` — compatible with current `transformers==4.57.3`
- For re-ranking: `CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")` via sentence-transformers

---

## 7. Sarvam AI — Indian Language Support

### Role in Neethi
Translates user queries from Indian languages to English (for the RAG pipeline) and translates responses back to the user's preferred language. Also provides TTS and STT for voice access.

### API Integration

```python
import httpx

SARVAM_API = "https://api.sarvam.ai"

async def translate_to_english(text: str, source_lang: str) -> str:
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{SARVAM_API}/translate",
            json={"input": text, "source_language_code": source_lang,
                  "target_language_code": "en-IN"},
            headers={"api-subscription-key": SARVAM_API_KEY},
        )
    return r.json()["translated_text"]
```

### Supported Languages
Hindi (hi-IN), Bengali (bn-IN), Tamil (ta-IN), Telugu (te-IN), Kannada (kn-IN), Malayalam (ml-IN), Gujarati (gu-IN), Marathi (mr-IN), Punjabi (pa-IN), Odia (od-IN)

---

## 8. Thesys API — Visual UI Components

### Role in Neethi
Generates structured visual components (timelines, comparison tables, step-by-step guides) for layman users who find raw legal text hard to follow.

### Installed Version
- **@thesysai/genui-sdk:** `0.8.5` (frontend)

### Integration
- Frontend: Thesys React SDK renders visual components from structured JSON
- Backend proxy: Next.js `/api/thesys` route proxies requests to Thesys API
- Environment: `THESYS_API_KEY` in `.env`

---

## 9. SERP API — Legal Resource Discovery

### Role in Neethi
Finds nearby lawyers, legal aid centers, courts, and police stations based on user location. Used by the `/resources/nearby` endpoint.

### Integration

```python
import httpx

async def find_nearby_legal_resources(location: str, resource_type: str) -> list:
    async with httpx.AsyncClient() as client:
        r = await client.get(
            "https://serpapi.com/search",
            params={
                "q": f"{resource_type} near {location}",
                "api_key": SERP_API_KEY,
                "engine": "google_maps",
            }
        )
    return r.json().get("local_results", [])
```

---

## 10. PyMuPDF + pdfplumber — PDF Processing

### Role in Neethi
Extracts text from Indian legal PDFs (BNS/BNSS/BSA handbooks, SC judgment PDFs). Cascading strategy: PyMuPDF first, pdfplumber for tables, pytesseract for scanned pages.

### Installed Versions
- **PyMuPDF (fitz):** `1.24.14`
- **pdfplumber:** `0.11.4`
- **pytesseract:** `0.3.13`
- **Pillow:** `11.0.0`

### Pipeline

```python
import fitz  # PyMuPDF

def extract_text(pdf_path: str) -> str:
    doc = fitz.open(pdf_path)
    text = ""
    for page in doc:
        page_text = page.get_text("text")
        if not page_text.strip():
            # Fallback to pdfplumber for tables
            page_text = extract_with_pdfplumber(pdf_path, page.number)
        if not page_text.strip():
            # Final fallback: OCR
            page_text = ocr_page(page)
        text += page_text
    return text
```

---

## 11. Jinja2 + WeasyPrint + ReportLab — Document Generation

### Role in Neethi
Generates legal document drafts as HTML (Jinja2 templates), converts to PDF (WeasyPrint preferred, ReportLab fallback).

### Installed Versions
- **Jinja2:** `3.1.4`
- **WeasyPrint:** `62.3`
- **lxml:** `5.3.0`
- **ReportLab:** `4.2.5`

### 10 Document Templates Available

| Template | Document Type |
|---|---|
| `bail_application` | Bail Application |
| `anticipatory_bail` | Anticipatory Bail Application |
| `legal_notice` | Legal Notice |
| `fir_complaint` | FIR Complaint |
| `power_of_attorney` | Power of Attorney |
| `vakalatnama` | Vakalatnama |
| `affidavit` | General Affidavit |
| `rti_application` | RTI Application |
| `consumer_complaint` | Consumer Complaint |
| `rent_agreement` | Rent Agreement |

See `backend/document_drafting/references/` for reference guides and `backend/api/routes/documents.py` for template definitions.

---

## 12. PostgreSQL / SQLAlchemy — Database

### Role in Neethi
Stores users, query logs, document drafts, conversation sessions, and feedback. Hosted on Supabase.

### Installed Versions
- **SQLAlchemy:** `2.0.36` (async)
- **asyncpg:** `0.30.0` (async driver)
- **alembic:** `1.13.3` (migrations)
- **psycopg2-binary:** `2.9.10` (Alembic env.py sync driver)

### Models

| Model | Key Fields |
|---|---|
| `User` | id, email, role, hashed_password, bar_council_id, police_badge_id |
| `QueryLog` | id, user_id, query_text, response_text, verification_status, tier, cached |
| `Draft` | id, user_id, template_id, draft_text, fields_used, language |
| `ConversationSession` | id, user_id, messages, created_at |

### Migrations

```bash
alembic upgrade head        # Apply all migrations
alembic revision --autogenerate -m "description"  # Create new migration
```

Migrations in `backend/db/migrations/` — 4 versions: initial schema, ingested judgments, conversation sessions, staged pipeline columns.

---

## 13. Redis — Caching

### Role in Neethi
Response caching to avoid re-running expensive CrewAI pipelines for repeated legal queries. Falls back gracefully to in-memory cache if Redis is unavailable.

### Installed Version
- **redis:** `5.2.1` (with asyncio extras)

### Cache Strategy

| Query Tier | TTL | Rationale |
|---|---|---|
| Tier 1 DIRECT (section lookup) | 86,400s (24h) | Statutory text is stable |
| Tier 3 FULL (crew pipeline) | 3,600s (1h) | New documents may be indexed |

### Cache Key Format

```
neethi:v1:{user_role}:{sha256(normalized_query)[:24]}
```

### Configuration

```env
# Local Redis
REDIS_URL=redis://localhost:6379

# Upstash (TLS)
REDIS_URL=rediss://:password@endpoint.upstash.io:6379
```

If `REDIS_URL` is not set or Redis is unreachable, the system falls back to an in-memory `dict` cache. See `backend/services/cache.py`.

---

## 14. Integration Architecture Overview

```
Browser / Mobile
    │ HTTPS
    ▼
Next.js 16 (port 3000)
    │ /api/v1/* → rewrite
    ▼
FastAPI 0.115.6 (port 8000)
    │ JWT Auth  │ CORS  │ Rate Limit
    ├── QueryRouter (regex Tier 1/3)
    │       │ Tier 1: direct Qdrant lookup (0 LLM calls)
    │       │ Tier 3: ↓
    │       ▼
    │   CrewAI 1.11.0 (sequential pipeline)
    │       Mistral Large → Groq → DeepSeek
    │       │           │
    │       ▼           ▼
    │   BGE-M3      PostgreSQL
    │   FlagEmbed   (Supabase)
    │   1.3.5
    │       │
    │       ▼
    │   Qdrant Cloud
    │   (qdrant-client 1.12.0)
    │   legal_documents + legal_sections
    │
    ├── Redis (Upstash) — response cache
    ├── Sarvam AI — translation / TTS / STT
    ├── Thesys API — visual components
    └── SerpAPI — nearby resources
```

---

## 15. Package Version Reference

Exact pinned versions as of 2026-03-23:

### Backend (Python 3.12)

| Package | Version | Purpose |
|---|---|---|
| fastapi | 0.115.6 | Web framework |
| uvicorn | 0.34.0 | ASGI server |
| python-multipart | 0.0.20 | File uploads |
| sqlalchemy | 2.0.36 | ORM (async) |
| asyncpg | 0.30.0 | Async PostgreSQL driver |
| alembic | 1.13.3 | DB migrations |
| psycopg2-binary | 2.9.10 | Sync PostgreSQL (Alembic) |
| qdrant-client | 1.12.0 | Vector DB client |
| crewai | 1.11.0 | Multi-agent framework |
| apscheduler | 3.10.4 | LiteLLM scheduler |
| nest_asyncio | 1.6.0 | Nested async for CrewAI |
| groq | 1.0.0 | Groq LLM SDK |
| anthropic | 0.40.0 | Anthropic Claude SDK |
| FlagEmbedding | 1.3.5 | BGE-M3 embeddings |
| sentence-transformers | 5.2.0 | CrossEncoder reranker |
| torch | ≥2.5.1 (2.8.0+cu128 on GPU) | ML framework |
| pymupdf | 1.24.14 | PDF extraction |
| pdfplumber | 0.11.4 | Table extraction |
| pytesseract | 0.3.13 | OCR |
| Pillow | 11.0.0 | Image processing |
| Jinja2 | 3.1.4 | Template engine |
| weasyprint | 62.3 | HTML→PDF |
| lxml | 5.3.0 | XML/HTML parser |
| reportlab | 4.2.5 | PDF fallback |
| python-jose | 3.5.0 | JWT |
| passlib | 1.7.4 | Password hashing |
| email-validator | 2.2.0 | Email validation |
| redis | 5.2.1 | Redis client (async) |
| httpx | 0.28.1 | Async HTTP client |
| pageindex | 0.2.8 | PageIndex SDK |
| python-dotenv | 1.1.1 | .env loading |
| structlog | 24.4.0 | Structured logging |
| pytest | 8.3.4 | Test framework |
| pytest-asyncio | 0.24.0 | Async test support |
| pytest-cov | 6.0.0 | Coverage |

### Frontend (Node.js 22.x)

| Package | Version | Purpose |
|---|---|---|
| next | 16.1.6 | React framework |
| react | 19.2.3 | UI library |
| typescript | 5.9.3 | Type safety |
| tailwindcss | 4.x | Styling |
| tailwind-merge | 2.x | Class merging (pinned for @crayonai compat) |
| zustand | 4.5.x | State management (pinned for @crayonai compat) |
| zod | 3.x | Schema validation (pinned for @crayonai compat) |
| @crayonai/react-core | 0.7.7 | AI chat components |
| @crayonai/react-ui | 0.9.16 | AI chat UI theme |
| @thesysai/genui-sdk | 0.8.5 | Thesys visual SDK |
| axios | 1.x | HTTP client |
| react-markdown | 10.x | Markdown renderer |
| recharts | 3.x | Charts |
| lucide-react | 0.575.x | Icons |
| react-hot-toast | 2.x | Notifications |
