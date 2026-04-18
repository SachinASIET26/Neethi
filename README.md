# Neethi AI — Indian Legal Domain Agentic AI

> **Core Principle:** In legal, a wrong answer is worse than no answer.
> Every response is source-cited and double-verified before delivery.

Neethi AI is a multi-agent AI system built for the Indian legal domain. It serves lawyers, citizens, legal advisors, and police with legally grounded, citation-backed, hallucination-free legal assistance.

---

## Table of Contents

- [Overview](#overview)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Quick Start](#quick-start)
- [Environment Variables](#environment-variables)
- [Running Locally](#running-locally)
- [Running on Lightning AI (GPU)](#running-on-lightning-ai-gpu)
- [Frontend](#frontend)
- [API Reference](#api-reference)
- [Multi-Agent Architecture](#multi-agent-architecture)
- [LLM Provider Strategy](#llm-provider-strategy)
- [Data Pipeline](#data-pipeline)
- [Testing](#testing)
- [Architecture Diagrams](#architecture-diagrams)

---

## Overview

Neethi AI handles the 2023 Indian legal code reforms — transitioning from legacy law to:

| New Act | Replaces | Domain |
|---|---|---|
| Bharatiya Nyaya Sanhita (BNS) 2023 | Indian Penal Code (IPC) 1860 | Substantive Criminal Law |
| Bharatiya Nagarik Suraksha Sanhita (BNSS) 2023 | Code of Criminal Procedure (CrPC) 1973 | Criminal Procedure |
| Bharatiya Sakshya Adhiniyam (BSA) 2023 | Indian Evidence Act (IEA) 1872 | Evidence Law |

**User Roles:**
- **Citizen** — Simplified, step-by-step guidance with visual aids
- **Lawyer** — Full IRAC analysis, case law, technical terminology
- **Legal Advisor** — Corporate/compliance focus, risk assessment
- **Police** — Criminal procedure, IPC/BNS provisions, operational guidance

---

## Tech Stack

| Layer | Technology | Version | Purpose |
|---|---|---|---|
| AI Orchestration | CrewAI | 1.11.0 | Multi-agent pipeline coordination |
| API Backend | FastAPI + Uvicorn | 0.115.6 / 0.34.0 | Async REST API with SSE streaming |
| Vector Database | Qdrant | Client 1.12.0 | Hybrid dense+sparse RAG retrieval |
| Embeddings | BGE-M3 (FlagEmbedding) | 1.3.5 | Multi-vector: dense 1024d + sparse BM25 |
| Re-ranking | CrossEncoder ms-marco-MiniLM | sentence-transformers 5.2.0 | Precision re-ranking of retrieved chunks |
| LLM — Primary | Mistral Large | via LiteLLM | Multi-step agent tasks & tool use |
| LLM — Fallback 1 | Groq (Llama 3.3 70B) | groq 1.0.0 | Fast query classification & formatting |
| LLM — Fallback 2 | DeepSeek-Chat | via LiteLLM | Legal reasoning & citation verification |
| LLM — Drafting | Claude Sonnet | anthropic 0.40.0 | Legal document generation |
| LLM Abstraction | LiteLLM | via crewai | Unified multi-provider interface |
| Database | PostgreSQL via Supabase | SQLAlchemy 2.0.36 | Users, sessions, document drafts |
| Caching | Redis (Upstash) | redis 5.2.1 | Response caching & rate limiting |
| Translation | Sarvam AI | HTTP via httpx | Indian language support (Hindi + regional) |
| Visual Explanations | Thesys API | @thesysai/genui-sdk 0.8.5 | UI visuals for layman users |
| Nearby Resources | SerpAPI | HTTP via httpx | Location-aware legal resource search |
| PDF Extraction | PyMuPDF + pdfplumber | 1.24.14 / 0.11.4 | Legal document text extraction |
| OCR | pytesseract + Pillow | 0.3.13 / 11.0.0 | Scanned PDF fallback |
| Document Generation | Jinja2 + WeasyPrint + ReportLab | 3.1.4 / 62.3 / 4.2.5 | Legal draft PDF export |
| GPU Compute | Lightning AI (CUDA 12.8) | torch 2.8.0+cu128 | BGE-M3 embedding generation |
| Frontend | Next.js 16 + React 19 | next 16.1.6 | Role-based dashboard with SSE streaming |

---

## Project Structure

```
neethi-ai/
├── backend/                        # FastAPI application
│   ├── agents/                     # CrewAI agent definitions & tools
│   │   ├── agents/                 # Individual agent modules
│   │   │   ├── query_analyst.py
│   │   │   ├── retrieval_specialist.py
│   │   │   ├── legal_reasoner.py
│   │   │   ├── citation_checker.py
│   │   │   ├── response_formatter.py
│   │   │   └── document_analyst.py
│   │   ├── tools/                  # Custom CrewAI tools
│   │   │   ├── qdrant_search_tool.py
│   │   │   ├── citation_verification_tool.py
│   │   │   ├── irac_analyzer_tool.py
│   │   │   ├── query_classifier_tool.py
│   │   │   ├── section_lookup_tool.py
│   │   │   ├── statute_normalization_tool.py
│   │   │   └── cross_reference_tool.py
│   │   ├── tasks/                  # Task definitions per crew
│   │   ├── skills/                 # CrewAI skills (legal drafting)
│   │   ├── crew_config.py          # Crew assembly per user role
│   │   ├── query_router.py         # Tier 1 / Tier 3 routing logic
│   │   ├── intent_classifier.py    # Intent classification
│   │   └── response_templates.py  # Structured response templates
│   ├── api/                        # REST API layer
│   │   ├── routes/                 # Endpoint handlers (11 routers)
│   │   │   ├── auth.py             # JWT authentication
│   │   │   ├── query.py            # Legal query + SSE streaming
│   │   │   ├── cases.py            # Case law search & analysis
│   │   │   ├── documents.py        # Document drafting & PDF export
│   │   │   ├── document_analysis.py# Document analysis pipeline
│   │   │   ├── sections.py         # Acts & sections lookup
│   │   │   ├── resources.py        # Nearby legal resources
│   │   │   ├── translate.py        # Sarvam AI translation
│   │   │   ├── voice.py            # TTS/STT via Sarvam
│   │   │   ├── conversation.py     # Conversation session management
│   │   │   └── admin.py            # Admin operations & health
│   │   ├── schemas/                # Pydantic request/response models
│   │   └── dependencies.py         # Shared FastAPI dependencies
│   ├── config/
│   │   └── llm_config.py           # Multi-LLM provider selection (Mistral → Groq → DeepSeek)
│   ├── db/                         # Database layer
│   │   ├── migrations/             # Alembic SQL migrations (4 versions)
│   │   ├── models/                 # SQLAlchemy ORM models (User, QueryLog, Draft)
│   │   ├── repositories/           # Async data access layer
│   │   └── seed_data/              # BNS/BNSS/BSA seed JSON
│   ├── document_drafting/          # Legal document templates & generation
│   │   ├── references/             # Legal document reference guides (6 types)
│   │   ├── templates/              # Jinja2 document templates
│   │   └── evals.json              # Document quality evaluation data
│   ├── preprocessing/              # Data ingestion pipeline
│   │   ├── pipeline.py             # Main pipeline orchestrator
│   │   ├── sc_judgment_ingester.py # SC judgment ingestion
│   │   ├── chunkers/               # Legal-aware text chunking
│   │   ├── classifiers/            # Offence classification
│   │   ├── cleaners/               # Text normalisation
│   │   ├── enrichers/              # JSON metadata enrichment
│   │   ├── extractors/             # PDF text extraction (PyMuPDF + OCR)
│   │   ├── parsers/                # Act/section parsing
│   │   ├── validators/             # Data quality validation
│   │   └── verifiers/              # Adversarial assertion checks
│   ├── rag/                        # Retrieval-augmented generation
│   │   ├── embeddings.py           # BGE-M3 embedder (dense + sparse)
│   │   ├── hybrid_search.py        # Weighted dense + sparse Qdrant search
│   │   ├── indexer.py              # Document indexing to Qdrant
│   │   ├── transition_indexer.py   # IPC→BNS transition mapping indexer
│   │   ├── qdrant_setup.py         # Collection creation & configuration
│   │   ├── reranker.py             # CrossEncoder re-ranking
│   │   └── rrf.py                  # Reciprocal Rank Fusion (k=60)
│   ├── services/                   # Shared services
│   │   ├── cache.py                # Redis response cache with in-memory fallback
│   │   ├── pageindex.py            # PageIndex SDK integration
│   │   └── synthesis.py            # Response synthesis utilities
│   ├── tests/                      # Backend test suite
│   └── main.py                     # FastAPI application entry point
├── frontend/                       # Next.js 16 + React 19 frontend
│   ├── src/
│   │   ├── app/                    # Next.js App Router pages
│   │   │   ├── (auth)/             # Login, Register
│   │   │   ├── (dashboard)/        # All dashboard pages
│   │   │   │   ├── dashboard/      # Main dashboard
│   │   │   │   ├── query/          # Legal query interface + SSE streaming
│   │   │   │   ├── cases/          # Case search & analysis
│   │   │   │   ├── documents/      # Draft + Analyze
│   │   │   │   ├── statutes/       # Acts & sections browser
│   │   │   │   ├── resources/      # Nearby legal resources
│   │   │   │   ├── history/        # Query history
│   │   │   │   ├── profile/        # User profile
│   │   │   │   ├── settings/       # User settings
│   │   │   │   └── admin/          # Admin panel (users, activity)
│   │   │   └── api/                # Next.js API routes (Thesys proxy, doc analysis stream)
│   │   ├── components/             # Reusable UI components
│   │   │   ├── layout/             # Header, Sidebar
│   │   │   ├── ui/                 # Badge, Button, Card, Input
│   │   │   └── providers/          # ThemeProvider (dark/light mode)
│   │   ├── lib/                    # API client, i18n, utils, proxy
│   │   ├── store/                  # Zustand state (auth, UI)
│   │   └── types/                  # TypeScript type definitions
│   ├── package.json
│   └── next.config.ts              # Next.js config + backend proxy rewrites
├── data/
│   ├── raw/                        # Source legal JSON/PDF files
│   │   ├── bns_complete.json       # BNS 2023 (full act)
│   │   ├── bnss_complete.json      # BNSS 2023 (full act)
│   │   └── bsa_complete.json       # BSA 2023 (full act)
│   ├── processed/                  # Post-pipeline processed data
│   ├── keywords/                   # Domain keyword lists
│   └── scripts/                    # Data ingestion & indexing scripts
│       ├── run_indexing.py         # BGE-M3 embedding + Qdrant indexing
│       ├── run_ingestion.py        # Document ingestion pipeline
│       └── run_activation.py       # Transition mapping activation
├── docs/                           # Documentation
│   ├── architecture/               # Architecture diagrams (Mermaid)
│   ├── development/                # Development notes & breakdowns
│   ├── prompts/                    # System prompt specifications
│   ├── embedding_model_comparison.md
│   ├── document_drafting_design.md
│   ├── citation_verification_flow.md
│   ├── tech_stack_index.md
│   ├── neethi_architecture_report.md
│   ├── retrieval_quality_analysis.md
│   ├── crewai_async_migration_guide.md
│   └── fastapi_documentation.md
├── scripts/                        # Utility scripts
│   ├── run_api.sh                  # API startup & dependency verification
│   └── verify.py                   # General verification utility
├── .env                            # Environment variables (see below)
├── alembic.ini                     # Database migration configuration
├── CLAUDE.md                       # Agent roles & codebase instructions
├── plan.md                         # Detailed architecture & implementation plan
└── requirements.txt                # Consolidated Python dependencies
```

---

## Quick Start

```bash
# 1. Clone and enter the project
git clone <repo-url> neethi-ai
cd neethi-ai

# 2. Create a virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 3. Install backend dependencies
pip install -r requirements.txt

# 4. Install frontend dependencies
cd frontend && npm install --legacy-peer-deps && cd ..

# 5. Configure environment
cp .env.example .env
# Edit .env and fill in your API keys

# 6. Start the backend (port 8000)
uvicorn backend.main:app --reload --reload-dir backend --host 0.0.0.0 --port 8000 --loop asyncio

# 7. Start the frontend (port 3000) — in a second terminal
cd frontend && npm run dev

# 8. Open
# Frontend:    http://localhost:3000
# API docs:    http://localhost:8000/docs
# ReDoc:       http://localhost:8000/redoc
```

---

## Environment Variables

Configure `.env` at the project root:

```env
# --- Database ---
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/neethi

# --- Vector Database ---
QDRANT_URL=https://<cluster-id>.<region>.cloud.qdrant.io:6333
QDRANT_API_KEY=<your-qdrant-api-key>

# --- LLM Providers (primary → fallback chain) ---
MISTRAL_API_KEY=<your-mistral-api-key>       # Primary — Mistral Large
GROQ_API_KEY=<your-groq-api-key>             # Fallback 1 — Llama 3.3 70B
DEEPSEEK_API_KEY=<your-deepseek-api-key>     # Fallback 2 — DeepSeek-Chat
ANTHROPIC_API_KEY=<your-anthropic-api-key>   # Document drafting — Claude Sonnet

# --- External Services ---
SARVAM_API_KEY=<your-sarvam-api-key>         # Translation + TTS/STT
SERP_API_KEY=<your-serpapi-key>              # Nearby legal resources
THESYS_API_KEY=<your-thesys-api-key>         # Visual UI components
PAGEINDEX_API_KEY=<your-pageindex-api-key>   # PageIndex SDK

# --- Auth ---
JWT_SECRET_KEY=<long-random-secret>
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=60

# --- Caching ---
REDIS_URL=redis://<upstash-endpoint>:6379    # Upstash TLS: rediss://

# --- App ---
ENVIRONMENT=development                      # or: production
CORS_ORIGINS=http://localhost:3000           # Frontend URL(s), comma-separated
BGE_M3_MODEL_PATH=BAAI/bge-m3               # Default; cached after first download
LOG_LEVEL=INFO
```

---

## Running Locally

```bash
# Backend — development (auto-reload, only watches backend/ to avoid node_modules churn)
uvicorn backend.main:app --reload --reload-dir backend --port 8000 --loop asyncio
# IMPORTANT: --loop asyncio is required (CrewAI nest_asyncio incompatible with uvloop)
# IMPORTANT: --reload-dir backend prevents reloader watching frontend/node_modules/

# Backend — production (multi-worker)
gunicorn backend.main:app -w 4 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000

# Frontend — development
cd frontend && npm run dev          # port 3000

# Frontend — production build
cd frontend && npm run build && npm run start

# Database migrations
alembic upgrade head

# Run data ingestion pipeline
python data/scripts/run_ingestion.py

# Generate embeddings & index to Qdrant (GPU recommended)
python data/scripts/run_indexing.py --mode setup    # Create collections
python data/scripts/run_indexing.py --act ALL        # Index all acts
python data/scripts/run_indexing.py --mode transition  # Activate IPC→BNS mappings
```

---

## Running on Lightning AI (GPU)

Lightning AI has PyTorch + CUDA 12.8 pre-installed. **Do NOT reinstall torch** — it will downgrade to the CPU version.

```bash
# 1. Verify GPU is available
python -c "import torch; print(torch.cuda.is_available(), torch.__version__)"
# Expected: True  2.8.0+cu128

# 2. Install dependencies (torch >= constraint is safe — won't downgrade)
pip install -r requirements.txt

# 3. If torch was accidentally downgraded, restore CUDA version
pip install torch --index-url https://download.pytorch.org/whl/cu121

# 4. First run — BGE-M3 downloads ~2.3 GB from HuggingFace
python -c "from backend.rag.embeddings import BGEM3Embedder; BGEM3Embedder()"

# 5. Start backend
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --loop asyncio

# 6. Start frontend
cd frontend && npm run dev
```

---

## Frontend

The frontend is implemented in **Next.js 16 (App Router) + React 19** with Tailwind CSS v4.

### Pages

| Route | Description |
|---|---|
| `/` | Landing page |
| `/login`, `/register` | Authentication |
| `/dashboard` | Main dashboard (role-aware) |
| `/query` | Legal query interface with SSE streaming |
| `/cases` | Case law search & IRAC analysis |
| `/documents/draft` | Legal document drafting |
| `/documents/analyze` | Document upload & analysis |
| `/statutes` | Acts & sections browser |
| `/resources` | Nearby legal resource finder |
| `/history` | Query history |
| `/settings` | User settings |
| `/admin` | Admin panel (users, activity) |

### Key Frontend Packages

| Package | Version | Purpose |
|---|---|---|
| next | 16.1.6 | React framework with SSR |
| react | 19.2.3 | UI library |
| @crayonai/react-core | 0.7.7 | AI chat components |
| @thesysai/genui-sdk | 0.8.5 | Thesys visual components |
| zustand | 4.5.5 | Global state management |
| tailwindcss | 4.x | Styling |
| tailwind-merge | 2.x | Conditional class merging |
| axios | 1.x | HTTP client |

Backend API is proxied through Next.js rewrites — the browser always calls `/api/v1/...` and Next.js forwards to `http://localhost:8000/api/v1/...`.

---

## API Reference

Base URL: `http://localhost:8000/api/v1`

| Method | Endpoint | Description | Auth |
|---|---|---|---|
| POST | `/auth/register` | Register user with role | No |
| POST | `/auth/login` | JWT login | No |
| POST | `/auth/refresh` | Refresh JWT token | Yes |
| GET | `/auth/me` | Current user profile | Yes |
| GET | `/health` | API health check | No |
| POST | `/query/ask` | Legal query (role-aware) | Yes |
| POST | `/query/ask/stream` | Streaming response (SSE) | Yes |
| GET | `/query/history` | User query history | Yes |
| POST | `/cases/search` | Search similar case law | Yes |
| POST | `/cases/analyze` | Deep IRAC case analysis | Yes |
| GET | `/documents/templates` | List document templates | Yes |
| POST | `/documents/draft` | Generate legal document draft | Yes |
| GET | `/documents/draft/{id}` | Retrieve draft | Yes |
| PUT | `/documents/draft/{id}` | Update draft | Yes |
| POST | `/documents/draft/{id}/pdf` | Export draft as PDF | Yes |
| DELETE | `/documents/draft/{id}` | Delete draft | Yes |
| GET | `/sections/acts` | List all indexed acts | Yes |
| GET | `/sections/acts/{id}/sections/{num}` | Get specific section text | Yes |
| POST | `/resources/nearby` | Find nearby legal resources | Yes |
| POST | `/translate/text` | Translate response text | Yes |
| POST | `/voice/tts` | Text-to-speech | Yes |
| POST | `/voice/stt` | Speech-to-text | Yes |
| GET | `/conversation` | List conversations | Yes |
| POST | `/admin/ingest` | Ingest new legal documents | Admin |
| GET | `/admin/health` | Detailed system health | Admin |

Full interactive docs: `http://localhost:8000/docs`

---

## Multi-Agent Architecture

Six CrewAI agents run sequentially. Crew composition varies by user role:

| Agent | Model | Role |
|---|---|---|
| Query Analyst | Mistral Large / Groq | Classify, decompose, expand query |
| Retrieval Specialist | Mistral Large / Groq | Hybrid Qdrant search + RRF + rerank |
| Legal Reasoner | Mistral Large | IRAC analysis (lawyer/advisor only) |
| Citation Verifier | Mistral Large / DeepSeek | Verify every section reference |
| Response Formatter | Mistral Large / Groq | Role-appropriate formatting |
| Document Drafter | Claude Sonnet | Legal document generation |

**Crew pipelines by role:**

```
Citizen:         Query Analyst → Retrieval → Citation Verifier → Formatter
Lawyer:          Query Analyst → Retrieval → Legal Reasoner → Citation Verifier → Formatter
Legal Advisor:   Query Analyst → Retrieval → Legal Reasoner → Citation Verifier → Formatter
Police:          Query Analyst → Retrieval → Citation Verifier → Formatter
Document Draft:  Query Analyst → Document Drafter → Citation Verifier
```

**Query routing (no LLM):**

Before invoking CrewAI, the `QueryRouter` pre-screens queries with regex:
- **Tier 1 DIRECT** — Section lookups (e.g. `"BNS 103"`, `"IPC 302 BNS equivalent"`) are served directly from Qdrant/DB in milliseconds — 0 LLM calls, cached 24 hours.
- **Tier 3 FULL** — All other queries go through the full CrewAI crew pipeline, cached 1 hour.

---

## LLM Provider Strategy

`backend/config/llm_config.py` selects the LLM at startup:

| Priority | Provider | Model | Why |
|---|---|---|---|
| 1 | Mistral AI | mistral-large-latest | Reliable multi-step tool use, no daily token cap |
| 2 | Groq | llama-3.3-70b-versatile | Fast fallback, 100K tokens/day free tier |
| 3 | DeepSeek | deepseek-chat | Cost-effective fallback |

Configure in `.env`: `MISTRAL_API_KEY`, `GROQ_API_KEY`, `DEEPSEEK_API_KEY`. The first key found is used.

**Task-specific:**
- Document Drafting → always Claude Sonnet (`ANTHROPIC_API_KEY`)

---

## Data Pipeline

Legal documents flow through a multi-stage preprocessing pipeline before indexing:

```
Raw PDF / JSON
    ↓
PDF Extractor (PyMuPDF → pdfplumber → pytesseract OCR)
    ↓
Text Cleaner (strip headers, footers, page numbers, watermarks)
    ↓
Act Parser (identify sections, chapters, schedules)
    ↓
Statute Normalizer (IPC→BNS cross-reference mapping)
    ↓
Legal Chunker (respect section boundaries — no cross-section splits)
    ↓
JSON Enricher (add payload: act_code, section_number, legal_domain, access_level)
    ↓
Extraction Validator (required field checks, PII stripping, quality gates)
    ↓
BGE-M3 Embedder (batch: dense 1024d + sparse BM25 — GPU recommended)
    ↓
Qdrant Indexer (upsert with full payload — legal_documents + legal_sections)
    ↓
Transition Indexer (activate IPC→BNS cross-links in legal_documents)
```

**Qdrant Collections:**

| Collection | Purpose | Vectors |
|---|---|---|
| `legal_documents` | Main retrieval collection | Dense 1024d + Sparse BM25 |
| `legal_sections` | Citation verification lookups | Dense 1024d + Sparse BM25 |
| `document_templates` | Drafting template retrieval | Dense 1024d |

---

## Testing

```bash
# Run all tests
pytest backend/tests/ -v

# Run specific test suites
pytest backend/tests/test_retrieval.py -v        # RAG retrieval quality
pytest backend/tests/test_phase5_agents.py -v    # Agent pipeline
pytest backend/tests/test_phase4_tools.py -v     # CrewAI tools
pytest backend/tests/test_api_e2e.py -v          # End-to-end API

# Run with coverage
pytest backend/tests/ --cov=backend --cov-report=html
```

**Coverage targets:** 80% minimum for retrieval, citation, and drafting paths.

---

## Architecture Diagrams

High-level component diagrams are in `docs/architecture/`:

| Diagram | Description |
|---|---|
| `01_system_layers.md` | Overall system layer stack |
| `02_multi_agent_components.md` | CrewAI agent composition |
| `03_rag_pipeline.md` | RAG retrieval components |
| `04_data_ingestion_pipeline.md` | PDF → Qdrant ingestion flow |
| `05_api_routing.md` | FastAPI routing & middleware |

---

## Key References

- **Architecture Plan**: [`plan.md`](plan.md)
- **Agent & Codebase Rules**: [`CLAUDE.md`](CLAUDE.md)
- **Embedding Model Study**: [`docs/embedding_model_comparison.md`](docs/embedding_model_comparison.md)
- **Document Drafting Design**: [`docs/document_drafting_design.md`](docs/document_drafting_design.md)
- **Citation Verification Flow**: [`docs/citation_verification_flow.md`](docs/citation_verification_flow.md)
- **Tech Stack Index**: [`docs/tech_stack_index.md`](docs/tech_stack_index.md)
- **Architecture Report**: [`docs/neethi_architecture_report.md`](docs/neethi_architecture_report.md)
- **CrewAI Async Guide**: [`docs/crewai_async_migration_guide.md`](docs/crewai_async_migration_guide.md)
