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
- [API Reference](#api-reference)
- [Multi-Agent Architecture](#multi-agent-architecture)
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

| Layer | Technology | Purpose |
|---|---|---|
| AI Orchestration | CrewAI 1.9.2 | Multi-agent pipeline coordination |
| API Backend | FastAPI 0.115.6 + Uvicorn | Async REST API with SSE streaming |
| Vector Database | Qdrant | Hybrid dense+sparse RAG retrieval |
| Embeddings | BGE-M3 (FlagEmbedding) | Multi-vector: dense + sparse in one pass |
| Re-ranking | CrossEncoder ms-marco-MiniLM | Precision re-ranking of retrieved chunks |
| LLM — Classification | Groq (Llama 3.3 70B) | Fast query classification & formatting |
| LLM — Reasoning | DeepSeek-R1 / Claude Sonnet | IRAC legal reasoning |
| LLM — Verification | DeepSeek-Chat | Citation verification |
| LLM — Drafting | Claude Sonnet | Legal document generation |
| LLM Abstraction | LiteLLM | Unified multi-provider interface |
| Database | PostgreSQL via Supabase | Users, sessions, document drafts |
| Caching | Redis (Upstash) | Response caching & rate limiting |
| Translation | Sarvam AI | Indian language support (Hindi + regional) |
| Visual Explanations | Thesys API | UI visuals for layman users |
| Nearby Resources | SerpAPI | Location-aware legal resource search |
| PDF Extraction | PyMuPDF + pdfplumber | Legal document text extraction |
| OCR | pytesseract + Pillow | Scanned PDF fallback |
| Document Generation | Jinja2 + WeasyPrint + ReportLab | Legal draft PDF export |
| GPU Compute | Lightning AI | BGE-M3 embedding generation |
| Frontend (planned) | Next.js (React) | Role-based dashboard with SSR |

---

## Project Structure

```
neethi-ai/
├── backend/                        # FastAPI application
│   ├── agents/                     # CrewAI agent definitions & tools
│   │   ├── agents/                 # Individual agent modules
│   │   ├── tools/                  # Custom CrewAI tools
│   │   ├── tasks/                  # Task definitions per crew
│   │   ├── crew_config.py          # Crew assembly configurations
│   │   └── query_router.py         # Role-based crew routing
│   ├── api/                        # REST API layer
│   │   ├── routes/                 # Endpoint handlers (9 routers)
│   │   ├── schemas/                # Pydantic request/response models
│   │   └── dependencies.py         # Shared FastAPI dependencies
│   ├── config/                     # LLM & app configuration
│   ├── db/                         # Database layer
│   │   ├── migrations/             # Alembic SQL migrations
│   │   ├── models/                 # SQLAlchemy ORM models
│   │   └── repositories/           # Async data access layer
│   ├── document_drafting/          # Legal document templates & generation
│   ├── preprocessing/              # Data ingestion pipeline
│   │   ├── chunkers/               # Legal-aware text chunking
│   │   ├── classifiers/            # Offence classification
│   │   ├── cleaners/               # Text normalisation
│   │   ├── enrichers/              # JSON metadata enrichment
│   │   ├── extractors/             # PDF text extraction
│   │   ├── parsers/                # Act/section parsing
│   │   └── validators/             # Data quality validation
│   ├── rag/                        # Retrieval-augmented generation
│   │   ├── embeddings.py           # BGE-M3 embedder
│   │   ├── hybrid_search.py        # Dense + sparse Qdrant search
│   │   ├── indexer.py              # Document indexing to Qdrant
│   │   ├── qdrant_setup.py         # Collection creation & configuration
│   │   ├── reranker.py             # CrossEncoder re-ranking
│   │   └── rrf.py                  # Reciprocal Rank Fusion
│   ├── services/                   # Shared services (cache, etc.)
│   ├── tests/                      # Backend test suite
│   └── main.py                     # FastAPI application entry point
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
│   ├── archive/                    # Archived design documents
│   ├── progress/                   # Phase progress reports
│   ├── prompts/                    # System prompt specifications
│   ├── references/                 # External guides & references
│   ├── sessions/                   # Claude Code session logs
│   ├── embedding_model_comparison.md
│   ├── document_drafting_design.md
│   ├── citation_verification_flow.md
│   ├── tech_stack_index.md
│   └── ...
├── logs/
│   └── lightning/                  # Lightning AI training & embedding logs
├── scripts/                        # Utility scripts
│   ├── run_api.sh                  # API startup & dependency verification
│   ├── check_bns103.py             # BNS section validation
│   ├── extract_super.py            # Superscript text extraction
│   ├── sarvam_extract.py           # Sarvam AI translation extraction
│   └── verify.py                   # General verification utility
├── Project Documents/              # Reference PDFs & reports
├── .env.example                    # Environment variable template
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

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env and fill in your API keys

# 5. Start the API server
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000 --loop asyncio

# 6. Open API docs
# Swagger UI:  http://localhost:8000/docs
# ReDoc:       http://localhost:8000/redoc
```

---

## Environment Variables

Copy `.env.example` to `.env` and configure:

```env
# --- Required ---
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/neethi
QDRANT_URL=https://<cluster-id>.<region>.cloud.qdrant.io:6333
QDRANT_API_KEY=<your-qdrant-api-key>
GROQ_API_KEY=<your-groq-api-key>
DEEPSEEK_API_KEY=<your-deepseek-api-key>
JWT_SECRET_KEY=<long-random-secret>

# --- Recommended ---
ANTHROPIC_API_KEY=<your-anthropic-api-key>   # Claude Sonnet for document drafting
REDIS_URL=redis://<upstash-endpoint>:6379    # Response caching

# --- Optional ---
SARVAM_API_KEY=<your-sarvam-api-key>         # Translation + TTS/STT
SERP_API_KEY=<your-serpapi-key>              # Nearby legal resources
BGE_M3_MODEL_PATH=BAAI/bge-m3               # Default; cached after first download
ENVIRONMENT=development                      # or: production
CORS_ORIGINS=http://localhost:3000           # Frontend URL(s)
```

---

## Running Locally

```bash
# Development (auto-reload)
uvicorn backend.main:app --reload --port 8000 --loop asyncio

# Production (multi-worker)
gunicorn backend.main:app -w 4 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000

# Database migrations
alembic upgrade head

# Run data ingestion pipeline
python data/scripts/run_ingestion.py

# Generate embeddings & index to Qdrant (requires GPU or takes time on CPU)
python data/scripts/run_indexing.py --mode setup    # Create collections
python data/scripts/run_indexing.py --act ALL        # Index all acts
python data/scripts/run_indexing.py --mode transition  # Activate IPC→BNS mappings
```

---

## Running on Lightning AI (GPU)

Lightning AI has PyTorch + CUDA pre-installed. **Do NOT reinstall torch** — it will downgrade to the CPU version.

```bash
# 1. Verify GPU is available
python -c "import torch; print(torch.cuda.is_available())"
# Must print: True

# 2. Use the setup script (installs deps, verifies imports, starts server)
bash scripts/run_api.sh

# 3. Or install manually (skip torch)
pip install -r requirements.txt --no-deps torch

# 4. If torch was accidentally downgraded
pip install torch --index-url https://download.pytorch.org/whl/cu121

# 5. First run — BGE-M3 downloads ~2.3 GB from HuggingFace
python -c "from backend.rag.embeddings import BGEM3Embedder; BGEM3Embedder()"
```

---

## API Reference

Base URL: `http://localhost:8000/api/v1`

| Method | Endpoint | Description | Auth |
|---|---|---|---|
| POST | `/auth/register` | Register user with role | No |
| POST | `/auth/login` | JWT login | No |
| GET | `/health` | API health check | No |
| POST | `/query/ask` | Legal query (role-aware) | Yes |
| POST | `/query/ask/stream` | Streaming response (SSE) | Yes |
| POST | `/cases/search` | Search similar case law | Yes |
| POST | `/cases/analyze` | Deep IRAC case analysis | Yes |
| POST | `/documents/draft` | Generate legal document draft | Yes |
| POST | `/documents/draft/{id}/pdf` | Export draft as PDF | Yes |
| GET | `/sections/acts` | List all indexed acts | Yes |
| GET | `/sections/acts/{id}/sections/{num}` | Get specific section text | Yes |
| POST | `/resources/nearby` | Find nearby legal resources | Yes |
| POST | `/translate/text` | Translate response text | Yes |
| POST | `/voice/tts` | Text-to-speech | Yes |
| POST | `/voice/stt` | Speech-to-text | Yes |
| POST | `/admin/ingest` | Ingest new legal documents | Admin |
| GET | `/admin/health` | Detailed system health | Admin |

Full interactive docs: `http://localhost:8000/docs`

---

## Multi-Agent Architecture

Five CrewAI agents run sequentially. Crew composition varies by user role:

| Agent | Model | Role |
|---|---|---|
| Query Analyst | Groq Llama 3.3 70B | Classify, decompose, expand query |
| Retrieval Specialist | DeepSeek-Chat | Hybrid Qdrant search + RRF + rerank |
| Legal Reasoner | DeepSeek-R1 / Claude Sonnet | IRAC analysis (lawyer/advisor only) |
| Citation Verifier | DeepSeek-Chat | Verify every section reference |
| Response Formatter | Groq Llama 3.3 70B | Role-appropriate formatting |

**Crew pipelines by role:**

```
Citizen:         Query Analyst → Retrieval → Citation Verifier → Formatter
Lawyer:          Query Analyst → Retrieval → Legal Reasoner → Citation Verifier → Formatter
Legal Advisor:   Query Analyst → Retrieval → Legal Reasoner → Citation Verifier → Formatter
Police:          Query Analyst → Retrieval → Citation Verifier → Formatter
Document Draft:  Query Analyst → Document Drafter → Citation Verifier
```

---

## Data Pipeline

Legal documents flow through a multi-stage preprocessing pipeline before indexing:

```
Raw PDF/JSON
    ↓
PDF Extractor (PyMuPDF + pdfplumber + OCR fallback)
    ↓
Text Cleaner (remove headers, footers, page numbers)
    ↓
Act Parser (identify sections, chapters, schedules)
    ↓
Legal Chunker (respect section boundaries)
    ↓
Metadata Enricher (act code, section number, domain, access level)
    ↓
Extraction Validator
    ↓
BGE-M3 Embedder (dense + sparse vectors, GPU recommended)
    ↓
Qdrant Indexer (hybrid collections: legal_documents, legal_sections, templates)
```

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

# Test specific API groups
python backend/tests/test_api_e2e.py --groups auth sections query
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
- **Qdrant Optimization Guide**: [`docs/references/qdrant_resource_optimization_guide.pdf`](docs/references/qdrant_resource_optimization_guide.pdf)
