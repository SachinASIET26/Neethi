# Neethi AI — Indian Legal Domain Agentic AI

> **Core Principle:** In legal, a wrong answer is worse than no answer.
> Every response is source-cited and double-verified before delivery.

Neethi AI is a production-grade multi-agent AI system for the Indian legal domain. It serves **lawyers, citizens, legal advisors, and police** with legally grounded, citation-backed, hallucination-free legal assistance — powered by CrewAI, FastAPI, Qdrant, and BGE-M3.

[![Python](https://img.shields.io/badge/Python-3.11+-blue?logo=python)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115.6-009688?logo=fastapi)](https://fastapi.tiangolo.com)
[![CrewAI](https://img.shields.io/badge/CrewAI-1.9.2-orange)](https://crewai.com)
[![Qdrant](https://img.shields.io/badge/Qdrant-1.12.0-red)](https://qdrant.tech)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)

---

## Table of Contents

- [Overview](#overview)
- [Tech Stack](#tech-stack)
- [System Architecture](#system-architecture)
- [Multi-Agent Pipeline](#multi-agent-pipeline)
- [RAG Retrieval Pipeline](#rag-retrieval-pipeline)
- [Qdrant Collections](#qdrant-collections)
- [Project Structure](#project-structure)
- [Quick Start](#quick-start)
- [Environment Variables](#environment-variables)
- [Running on Lightning AI (GPU)](#running-on-lightning-ai-gpu)
- [Data Ingestion](#data-ingestion)
- [API Reference](#api-reference)
- [Testing](#testing)
- [Legal Data Coverage](#legal-data-coverage)

---

## Overview

Neethi AI handles the 2023 Indian legal code reforms — covering both legacy law and the new Bharatiya sanhitas:

| New Act | Replaces | Domain |
|---|---|---|
| Bharatiya Nyaya Sanhita (BNS) 2023 | Indian Penal Code (IPC) 1860 | Substantive Criminal Law |
| Bharatiya Nagarik Suraksha Sanhita (BNSS) 2023 | Code of Criminal Procedure (CrPC) 1973 | Criminal Procedure |
| Bharatiya Sakshya Adhiniyam (BSA) 2023 | Indian Evidence Act (IEA) 1872 | Evidence Law |

**User Roles — Role-aware response formatting:**

| Role | Response Style | Crew Used |
|---|---|---|
| **Citizen** | Plain language, step-by-step, visual aids | Layman Crew |
| **Lawyer** | Full IRAC analysis, case law citations, technical language | Lawyer Crew |
| **Legal Advisor** | Corporate/compliance focus, risk assessment format | Advisor Crew |
| **Police** | Criminal procedure, BNS/BNSS provisions, operational steps | Police Crew |

---

## Tech Stack

| Layer | Technology | Version | Purpose |
|---|---|---|---|
| AI Orchestration | CrewAI | 1.9.2 | Multi-agent pipeline coordination |
| LLM Abstraction | LiteLLM | 1.81.5 | Unified Groq / DeepSeek / Claude interface |
| API Backend | FastAPI + Uvicorn | 0.115.6 / 0.34.0 | Async REST API with SSE streaming |
| Vector Database | Qdrant | 1.12.0 | Hybrid dense+sparse RAG retrieval |
| Embeddings | BGE-M3 (FlagEmbedding) | 1.3.3 | Multi-vector: dense + sparse in one model pass |
| Re-ranking | CrossEncoder ms-marco-MiniLM | — | Precision re-ranking of retrieved chunks |
| LLM — Classification | Groq (Llama 3.3 70B) | — | Fast query classification & response formatting |
| LLM — Reasoning | DeepSeek-R1 / Claude Sonnet | — | IRAC legal reasoning (lawyer/advisor roles) |
| LLM — Verification | DeepSeek-Chat | — | Citation verification & cross-referencing |
| LLM — Drafting | Claude Sonnet | — | Legal document generation |
| Database | PostgreSQL via Supabase | — | Users, sessions, document drafts |
| Caching | Redis (Upstash) | 5.2.1 | Response caching & rate limiting |
| Translation | Sarvam AI | — | Indian language support (Hindi + 10 regional) |
| Visual Explanations | Thesys API | — | Citizen-facing visual UI components |
| Nearby Resources | SerpAPI | — | Location-aware legal resource search |
| PDF Extraction | PyMuPDF + pdfplumber | 1.24.14 / 0.11.4 | Legal document text extraction |
| OCR | pytesseract + Pillow | 0.3.13 / 11.0.0 | Scanned PDF fallback |
| Document Generation | Jinja2 + WeasyPrint + ReportLab | — | Legal draft PDF export |
| GPU Compute | Lightning AI | — | BGE-M3 embedding generation |
| Frontend (planned) | Next.js (React) | — | Role-based dashboard with SSR |

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                          CLIENT LAYER                               │
│   Citizen App  │  Lawyer Portal  │  Police Dashboard  │  Admin UI  │
└────────────────────────────┬────────────────────────────────────────┘
                             │  REST / SSE
┌────────────────────────────▼────────────────────────────────────────┐
│                       FastAPI (Port 8000)                           │
│  /auth  /query  /cases  /documents  /sections  /translate  /admin   │
│  JWT Auth  │  Rate Limiting  │  Redis Cache  │  OpenAPI Docs        │
└────────────────────────────┬────────────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────────────┐
│                    Query Router (Tier Detection)                    │
│  DIRECT tier: explicit section refs (e.g. "BNS 103")               │
│  FULL crew:   all other legal queries → CrewAI pipeline            │
└──────────┬──────────────────────────────────────────┬──────────────┘
           │ DIRECT                                   │ FULL Crew
           │                                          │
┌──────────▼──────────┐              ┌────────────────▼──────────────┐
│ CitationVerification│              │         CrewAI Pipeline        │
│ StatuteNormalization│              │  Query Analyst                 │
│ (zero-LLM, <1s)     │              │    ↓                           │
└─────────────────────┘              │  Retrieval Specialist          │
                                     │    ↓                           │
                                     │  Legal Reasoner (lawyer only)  │
                                     │    ↓                           │
                                     │  Citation Verifier             │
                                     │    ↓                           │
                                     │  Response Formatter            │
                                     └───────────────────────────────┘
                                                    │
                         ┌──────────────────────────▼──────────────────────────┐
                         │                  Qdrant Vector DB                   │
                         │  legal_documents  │  legal_sections  │  templates   │
                         │  Hybrid Search (Dense BGE-M3 + Sparse BM25)         │
                         │  Weighted RRF  │  Score Boosting  │  MMR Diversity  │
                         └─────────────────────────────────────────────────────┘
```

---

## Multi-Agent Pipeline

Five CrewAI agents run sequentially. Crew composition varies by user role:

| Agent | Model | Role | When Active |
|---|---|---|---|
| **Query Analyst** | Groq Llama 3.3 70B | Classify domain, decompose query, extract entities | All roles |
| **Retrieval Specialist** | DeepSeek-Chat | Hybrid Qdrant search + RRF + CrossEncoder rerank | All roles |
| **Legal Reasoner** | DeepSeek-R1 / Claude Sonnet | IRAC analysis, precedent mapping | Lawyer, Advisor |
| **Citation Verifier** | DeepSeek-Chat | Verify every section reference — unverified = removed | All roles |
| **Response Formatter** | Groq Llama 3.3 70B | Role-appropriate language, Sarvam translation | All roles |

**Crew pipelines by role:**

```
Citizen:         Query Analyst → Retrieval Specialist → Citation Verifier → Response Formatter
Lawyer:          Query Analyst → Retrieval Specialist → Legal Reasoner → Citation Verifier → Response Formatter
Legal Advisor:   Query Analyst → Retrieval Specialist → Legal Reasoner → Citation Verifier → Response Formatter
Police:          Query Analyst → Retrieval Specialist → Citation Verifier → Response Formatter
Document Draft:  Query Analyst → Document Drafter → Citation Verifier
```

**CRITICAL RULE:** If a citation cannot be verified in the vector store, it is **removed** — never delivered unverified. If confidence < 0.5, the system returns: *"I cannot provide a verified answer. Please consult a qualified legal professional."*

---

## RAG Retrieval Pipeline

```
User Query
    │
    ▼
Query Expansion (LLM → legal synonyms, alternate phrasing)
    │
    ▼
Weighted Hybrid Search (Qdrant)
    ├── Dense Search   (BGE-M3 768d)  — weight varies by query_type
    └── Sparse Search  (BM25/SPLADE)  — weight varies by query_type
    │
    ▼
Reciprocal Rank Fusion (RRF, k=60)
    │
    ▼
Score Boosting
    ├── Era recency boost  (+0.15 for naveen_sanhitas — BNS/BNSS/BSA)
    ├── Extraction confidence weight  (×0.85–1.0)
    └── is_offence boost  (+0.10 for criminal queries)
    │
    ▼
CrossEncoder Re-ranking (ms-marco-MiniLM-L-6-v2)
    │
    ▼
MMR Diversity  (diversity=0.3 for civil/layman — forces multi-act coverage)
    │
    ▼
Role-based Access Filter  (user_access_level payload filter)
    │
    ▼
Citation Verification  (every source checked against legal_sections collection)
```

**Query type weights (dense / sparse):**

| Query Type | Dense Weight | Sparse Weight | Use Case |
|---|---|---|---|
| `section_lookup` | 1.0 | 4.0 | Direct section reference |
| `criminal_offence` | 2.0 | 1.5 | Offence + punishment queries |
| `civil_conceptual` | 3.0 | 1.0 | Conceptual civil law queries |
| `procedural` | 2.5 | 2.0 | Procedural / step-by-step |
| `default` | 2.0 | 1.5 | Fallback |

---

## Qdrant Collections

| Collection | Vectors | Count | Purpose |
|---|---|---|---|
| `legal_sections` | Dense 768d + Sparse | ~1,933 | Section-level statutory law (primary lookup) |
| `legal_sub_sections` | Dense 768d + Sparse | ~2,104 | Sub-section granular text |
| `sc_judgments` | Dense 768d + Sparse | ~37,965 | Supreme Court precedents (1950–2024) |
| `law_transition_context` | Dense 768d + Sparse | ~1,440 | IPC→BNS / CrPC→BNSS transition mappings |
| `document_templates` | Dense 768d | — | Legal document drafting templates |

**Payload fields indexed:** `act_name`, `act_code`, `section_number`, `document_type`, `court`, `legal_domain`, `state`, `language`, `user_access_level`, `judgment_date`, `era`, `is_offence`

---

## Project Structure

```
neethi-ai/
├── backend/                        # FastAPI application
│   ├── agents/                     # CrewAI agent definitions & tools
│   │   ├── agents/                 # Individual agent modules
│   │   │   ├── query_analyst.py    # Groq Llama 3.3 70B — classify & expand
│   │   │   ├── retrieval_specialist.py
│   │   │   ├── legal_reasoner.py   # DeepSeek-R1 / Claude — IRAC analysis
│   │   │   ├── citation_checker.py # DeepSeek-Chat — verify every cite
│   │   │   └── response_formatter.py
│   │   ├── tools/                  # Custom CrewAI tools
│   │   │   ├── citation_verification_tool.py
│   │   │   ├── qdrant_search_tool.py
│   │   │   ├── query_classifier_tool.py
│   │   │   ├── irac_analyzer_tool.py
│   │   │   ├── cross_reference_tool.py
│   │   │   ├── section_lookup_tool.py
│   │   │   └── statute_normalization_tool.py
│   │   ├── crew_config.py          # Crew assembly per role
│   │   └── query_router.py         # Tier detection (DIRECT vs FULL crew)
│   ├── api/                        # REST API layer
│   │   ├── routes/                 # Endpoint handlers (9 routers)
│   │   │   ├── auth.py             # /auth/register, /auth/login
│   │   │   ├── query.py            # /query/ask, /query/ask/stream (SSE)
│   │   │   ├── cases.py            # /cases/search, /cases/analyze
│   │   │   ├── documents.py        # /documents/draft, /documents/draft/{id}/pdf
│   │   │   ├── sections.py         # /sections/acts, /sections/acts/{id}/sections/{num}
│   │   │   ├── resources.py        # /resources/nearby
│   │   │   ├── translate.py        # /translate/text
│   │   │   ├── voice.py            # /voice/tts, /voice/stt
│   │   │   └── admin.py            # /admin/ingest, /admin/health
│   │   ├── schemas/                # Pydantic request/response models
│   │   └── dependencies.py         # JWT, cache, DB shared deps
│   ├── config/
│   │   └── llm_config.py           # LLM provider config (Groq, DeepSeek, Claude)
│   ├── db/                         # Database layer
│   │   ├── migrations/             # Alembic SQL migrations
│   │   ├── models/                 # SQLAlchemy ORM models
│   │   │   ├── user.py             # User accounts & roles
│   │   │   └── legal_foundation.py # Acts, sections, cases
│   │   ├── repositories/           # Async data access layer
│   │   └── seed_data/              # BNSS Schedule I seed JSON
│   ├── document_drafting/          # Legal document templates & generation
│   ├── preprocessing/              # Data ingestion pipeline
│   │   ├── parsers/act_parser.py   # Section extraction with compound numbering
│   │   ├── extractors/             # PyMuPDF + pdfplumber PDF extraction
│   │   ├── cleaners/               # Text normalisation
│   │   ├── classifiers/            # Offence classification
│   │   ├── enrichers/              # JSON metadata enrichment
│   │   ├── validators/             # Data quality validation
│   │   ├── pipeline.py             # Orchestrated ingestion pipeline
│   │   └── sc_judgment_ingester.py # Supreme Court judgment bulk ingester
│   ├── rag/                        # Retrieval-augmented generation
│   │   ├── embeddings.py           # BGE-M3 embedder (dense + sparse)
│   │   ├── hybrid_search.py        # Weighted RRF + Score Boost + MMR
│   │   ├── indexer.py              # Document indexing to Qdrant
│   │   ├── qdrant_setup.py         # Collection creation & configuration
│   │   ├── reranker.py             # CrossEncoder re-ranking
│   │   └── rrf.py                  # Reciprocal Rank Fusion
│   ├── services/
│   │   └── cache.py                # Redis response cache
│   ├── tests/                      # Backend test suite
│   │   ├── test_retrieval.py       # RAG retrieval quality tests
│   │   ├── test_full_pipeline.py   # Full pipeline integration tests
│   │   ├── test_api_e2e.py         # End-to-end API tests
│   │   ├── test_phase4_tools.py    # CrewAI tools tests
│   │   └── test_phase5_agents.py   # Agent pipeline tests
│   └── main.py                     # FastAPI application entry point
├── data/
│   ├── raw/
│   │   ├── acts/                   # Source legal files
│   │   │   ├── *.json              # Structured JSON for indexed acts
│   │   │   └── *.pdf               # Source PDFs (not committed — download separately)
│   │   ├── bns_complete.json       # BNS 2023 — all 358 sections
│   │   ├── bnss_complete.json      # BNSS 2023 — full act
│   │   └── bsa_complete.json       # BSA 2023 — full act
│   ├── keywords/
│   │   └── bns_procedural_keywords.txt
│   ├── scripts/                    # Data pipeline scripts
│   │   ├── run_ingestion.py        # PDF/JSON → parsed sections
│   │   ├── run_indexing.py         # BGE-M3 embed + Qdrant index
│   │   └── run_activation.py       # IPC→BNS transition mapping activation
│   └── audit/                      # Audit trail placeholder
├── docs/                           # Project documentation
│   ├── architecture/               # Architecture diagrams (Mermaid)
│   │   ├── 01_system_layers.md
│   │   ├── 02_multi_agent_components.md
│   │   ├── 03_rag_pipeline.md
│   │   ├── 04_data_ingestion_pipeline.md
│   │   └── 05_api_routing.md
│   ├── development/
│   │   └── data_pipeline_breakdown.md
│   ├── embedding_model_comparison.md   # BGE-M3 vs alternatives study
│   ├── document_drafting_design.md
│   ├── citation_verification_flow.md
│   ├── retrieval_quality_analysis.md
│   ├── tech_stack_index.md
│   ├── indian_legal_data_sources.md    # Where to get legal PDFs
│   └── neethi_architecture_report.md
├── scripts/                        # Utility & ops scripts
│   ├── run_api.sh                  # API startup + dependency verification
│   ├── sarvam_extract.py           # Sarvam AI translation pipeline
│   ├── tag_sc_judgment_domains.py  # Domain tagging for SC judgments
│   ├── reindex_unindexed_sections.py
│   └── verify.py                   # General verification utility
├── stitch/                         # UI prototype mockups (HTML)
│   ├── Login - Neethi AI.html
│   ├── Register - Neethi AI.html
│   ├── AI Legal Assistant Chat.html
│   ├── Legal Command Center Dashboard.html
│   ├── Drafting Wizard - Neethi AI.html
│   ├── Legal Resources & Aid Hub - Neethi AI.html
│   ├── Premium AI Chat Interface.html
│   └── Premium Dashboard Overview.html
├── .env.example                    # Environment variable template (fill & rename to .env)
├── .gitignore
├── alembic.ini                     # Database migration configuration
├── CLAUDE.md                       # Agent roles & codebase instructions
├── plan.md                         # Detailed architecture & implementation plan
└── requirements.txt                # Consolidated Python dependencies
```

---

## Quick Start

```bash
# 1. Clone the repository
git clone https://github.com/SachinASIET26/Neethi.git
cd Neethi

# 2. Create a virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env and fill in your API keys (see Environment Variables section)

# 5. Apply database migrations
alembic upgrade head

# 6. Start the API server
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000 --loop asyncio

# 7. Open API docs
# Swagger UI:  http://localhost:8000/docs
# ReDoc:       http://localhost:8000/redoc
```

---

## Environment Variables

Copy `.env.example` to `.env` and configure:

```env
# --- Database (Supabase) ---
DATABASE_URL=postgresql+asyncpg://postgres:YOUR_PASSWORD@db.YOUR_PROJECT_REF.supabase.co:5432/postgres

# --- Vector Database (Qdrant Cloud) ---
QDRANT_URL=https://<cluster-id>.<region>.cloud.qdrant.io:6333
QDRANT_API_KEY=<your-qdrant-api-key>

# --- LLM Providers ---
GROQ_API_KEY=<your-groq-api-key>           # Llama 3.3 70B (classification + formatting)
DEEPSEEK_API_KEY=<your-deepseek-api-key>   # DeepSeek-R1 (reasoning) + Chat (verification)
ANTHROPIC_API_KEY=<your-anthropic-key>     # Claude Sonnet (document drafting)
MISTRAL_API_KEY=<your-mistral-key>         # Optional fallback when Groq rate-limits

# --- External Services ---
SARVAM_API_KEY=<your-sarvam-key>           # Indian language translation + TTS/STT
SERP_API_KEY=<your-serpapi-key>            # Nearby legal resource search
THESYS_API_KEY=<your-thesys-key>          # Visual UI components for citizens

# --- Auth ---
JWT_SECRET_KEY=<long-random-secret-min-32-chars>
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=60

# --- Cache (Upstash Redis) ---
REDIS_URL=redis://localhost:6379           # Local dev
# REDIS_URL=rediss://default:<token>@<host>.upstash.io:6380  # Production

# --- Embeddings ---
BGE_M3_MODEL_PATH=BAAI/bge-m3             # Downloads ~2.3 GB on first use

# --- App ---
ENVIRONMENT=development
LOG_LEVEL=INFO
CORS_ORIGINS=http://localhost:3000
```

---

## Running on Lightning AI (GPU)

Lightning AI has PyTorch + CUDA pre-installed. **Do NOT reinstall torch** — it will downgrade to the CPU version.

```bash
# 1. Verify GPU is available (must print True)
python -c "import torch; print(torch.cuda.is_available())"

# 2. Use the setup script (installs deps, verifies imports, starts server)
bash scripts/run_api.sh

# 3. If torch was accidentally downgraded to CPU
pip install torch --index-url https://download.pytorch.org/whl/cu121

# 4. First run — BGE-M3 downloads ~2.3 GB from HuggingFace automatically
python -c "from backend.rag.embeddings import BGEM3Embedder; BGEM3Embedder()"
```

---

## Data Ingestion

Legal documents are too large for Git. Download source PDFs separately (see [`docs/indian_legal_data_sources.md`](docs/indian_legal_data_sources.md)), then run:

```bash
# Stage 1 — Parse PDFs/JSONs into structured sections
python data/scripts/run_ingestion.py

# Stage 2 — Generate BGE-M3 embeddings + index to Qdrant (GPU recommended)
python data/scripts/run_indexing.py --mode setup        # Create Qdrant collections
python data/scripts/run_indexing.py --act ALL           # Index all acts
python data/scripts/run_indexing.py --mode transition   # Activate IPC→BNS mappings

# Stage 3 — Ingest Supreme Court judgments
python backend/preprocessing/sc_judgment_ingester.py

# Stage 4 — Tag judgment legal domains
python scripts/tag_sc_judgment_domains.py
```

**Currently indexed (production):**

| Collection | Records | Content |
|---|---|---|
| `legal_sections` | 1,933 | BNS, BNSS, BSA, IPC, CrPC, IEA, CPC, HSA, HMA, TPA, SRA, CPA, ICA, LA, ACA |
| `legal_sub_sections` | 2,104 | Sub-section granular text |
| `sc_judgments` | 37,965 | Supreme Court judgments (1950–2024), domain-tagged |
| `law_transition_context` | 1,440 | IPC→BNS / CrPC→BNSS section mappings |

---

## API Reference

Base URL: `http://localhost:8000/api/v1`

| Method | Endpoint | Description | Auth |
|---|---|---|---|
| POST | `/auth/register` | Register with role (citizen/lawyer/advisor/police) | — |
| POST | `/auth/login` | JWT login → access token | — |
| GET | `/health` | API health check | — |
| POST | `/query/ask` | Legal query (role-aware, full crew) | JWT |
| POST | `/query/ask/stream` | Streaming response (SSE) | JWT |
| POST | `/cases/search` | Search similar case law | JWT |
| POST | `/cases/analyze` | Deep IRAC case analysis | JWT |
| POST | `/documents/draft` | Generate legal document draft | JWT |
| POST | `/documents/draft/{id}/pdf` | Export draft as PDF | JWT |
| GET | `/sections/acts` | List all indexed acts | JWT |
| GET | `/sections/acts/{id}/sections/{num}` | Get specific section text | JWT |
| POST | `/resources/nearby` | Find nearby legal resources (SerpAPI) | JWT |
| POST | `/translate/text` | Translate response via Sarvam AI | JWT |
| POST | `/voice/tts` | Text-to-speech | JWT |
| POST | `/voice/stt` | Speech-to-text | JWT |
| POST | `/admin/ingest` | Ingest new legal documents | Admin |
| GET | `/admin/health` | Detailed system health + Qdrant stats | Admin |

Full interactive docs: `http://localhost:8000/docs`

**Example: Citizen legal query**

```bash
# Register
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"full_name":"Rahul Sharma","email":"rahul@example.com","password":"Secret123","role":"citizen"}'

# Login → get token
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"rahul@example.com","password":"Secret123"}'

# Query
curl -X POST http://localhost:8000/api/v1/query/ask \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"query":"Someone slapped me and threatened me. What law applies and what can I do?","language":"en"}'
```

---

## Testing

```bash
# Run all tests
pytest backend/tests/ -v

# Specific test suites
pytest backend/tests/test_retrieval.py -v           # RAG retrieval quality
pytest backend/tests/test_full_pipeline.py -v       # Full pipeline integration
pytest backend/tests/test_api_e2e.py -v             # End-to-end API
pytest backend/tests/test_phase4_tools.py -v        # CrewAI tools
pytest backend/tests/test_phase5_agents.py -v       # Agent pipeline

# With coverage report
pytest backend/tests/ --cov=backend --cov-report=html
open htmlcov/index.html
```

**Coverage targets:** 80% minimum for retrieval, citation, and document drafting paths.

---

## Legal Data Coverage

**Acts indexed with full section text:**

| Act | Code | Sections | Era |
|---|---|---|---|
| Bharatiya Nyaya Sanhita 2023 | BNS_2023 | 358 | naveen_sanhitas |
| Bharatiya Nagarik Suraksha Sanhita 2023 | BNSS_2023 | 531 | naveen_sanhitas |
| Bharatiya Sakshya Adhiniyam 2023 | BSA_2023 | 170 | naveen_sanhitas |
| Indian Penal Code 1860 | IPC_1860 | 511 | legacy |
| Code of Criminal Procedure 1973 | CrPC_1973 | 484 | legacy |
| Indian Evidence Act 1872 | IEA_1872 | 167 | legacy |
| Code of Civil Procedure 1908 | CPC_1908 | 387 | legacy |
| Hindu Succession Act 1956 | HSA_1956 | 28 | civil |
| Hindu Marriage Act 1955 | HMA_1955 | — | civil |
| Transfer of Property Act 1882 | TPA_1882 | — | civil |
| Specific Relief Act 1963 | SRA_1963 | — | civil |
| Indian Contract Act 1872 | ICA_1872 | — | civil |
| Limitation Act 1963 | LA_1963 | — | civil |
| Consumer Protection Act 2019 | CPA_2019 | — | civil |
| Arbitration & Conciliation Act 1996 | ACA_1996 | — | civil |

**Supreme Court Judgments:** 37,965 indexed, domain-tagged across Criminal, Civil, Constitutional, Family, and Corporate domains.

---

## Key References

- **Architecture Plan**: [`plan.md`](plan.md)
- **Agent & Codebase Rules**: [`CLAUDE.md`](CLAUDE.md)
- **Embedding Model Study**: [`docs/embedding_model_comparison.md`](docs/embedding_model_comparison.md)
- **Document Drafting Design**: [`docs/document_drafting_design.md`](docs/document_drafting_design.md)
- **Citation Verification Flow**: [`docs/citation_verification_flow.md`](docs/citation_verification_flow.md)
- **Retrieval Quality Analysis**: [`docs/retrieval_quality_analysis.md`](docs/retrieval_quality_analysis.md)
- **Tech Stack Index**: [`docs/tech_stack_index.md`](docs/tech_stack_index.md)
- **Legal Data Sources**: [`docs/indian_legal_data_sources.md`](docs/indian_legal_data_sources.md)
- **Architecture Diagrams**: [`docs/architecture/`](docs/architecture/)

---

## License

MIT License — see [LICENSE](LICENSE) for details.

---

*Built for the Indian legal ecosystem. Every response is source-cited, double-verified, and role-formatted.*
