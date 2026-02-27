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
- [LLM Provider Strategy](#llm-provider-strategy)
- [System Architecture](#system-architecture)
- [Multi-Agent Pipeline](#multi-agent-pipeline)
- [Query Routing](#query-routing)
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

Neethi AI handles the 2023 Indian legal code reforms — covering both the new Bharatiya sanhitas and legacy colonial law:

| New Act | Replaces | Domain |
|---|---|---|
| Bharatiya Nyaya Sanhita (BNS) 2023 | Indian Penal Code (IPC) 1860 | Substantive Criminal Law |
| Bharatiya Nagarik Suraksha Sanhita (BNSS) 2023 | Code of Criminal Procedure (CrPC) 1973 | Criminal Procedure |
| Bharatiya Sakshya Adhiniyam (BSA) 2023 | Indian Evidence Act (IEA) 1872 | Evidence Law |

**User Roles — role-aware crew and response formatting:**

| Role | Response Style | Crew Used |
|---|---|---|
| **Citizen** | Plain language, step-by-step, practical next steps | Layman Crew |
| **Lawyer** | Full IRAC analysis, case law citations, technical precision | Lawyer Crew |
| **Legal Advisor** | Compliance-focused, risk assessment, regulatory mapping | Advisor Crew |
| **Police** | Procedural steps, cognizable/bailable status, FIR guidance | Police Crew |

---

## Tech Stack

| Layer | Technology | Version | Purpose |
|---|---|---|---|
| AI Orchestration | CrewAI | 1.9.2 | Multi-agent sequential pipeline |
| LLM Abstraction | LiteLLM | 1.81.5 | Unified Mistral / Groq / DeepSeek interface |
| API Backend | FastAPI + Uvicorn | 0.115.6 / 0.34.0 | Async REST API with SSE streaming |
| Vector Database | Qdrant | 1.12.0 | Hybrid dense+sparse RAG retrieval |
| Embeddings | BGE-M3 (FlagEmbedding) | 1.3.3 | 1024-dim dense + sparse in one model pass |
| Re-ranking | CrossEncoder ms-marco-MiniLM-L-6-v2 | — | Precision re-ranking of retrieved chunks |
| LLM — Primary | Mistral Large (`mistral/mistral-large-latest`) | — | All agent tasks (fast, light, reasoning, drafting) |
| LLM — Fallback 1 | Groq Llama 3.3 70B (`groq/llama-3.3-70b-versatile`) | — | When `MISTRAL_API_KEY` not set; capped 100K tokens/day |
| LLM — Fallback 2 | DeepSeek Chat (`deepseek/deepseek-chat`) | — | Last resort when Groq unavailable |
| Database | PostgreSQL via Supabase | — | Users, sessions, sections, document drafts |
| Caching | Redis via Upstash | 5.2.1 | Response caching (24h DIRECT / 1h FULL) + rate limiting |
| Translation | Sarvam AI | — | Indian language support (Hindi + regional) |
| Visual Explanations | Thesys API | — | Citizen-facing visual UI components |
| Nearby Resources | SerpAPI | — | Location-aware legal resource search |
| PDF Extraction | PyMuPDF + pdfplumber | 1.24.14 / 0.11.4 | Legal document text extraction (two-pass) |
| OCR Fallback | pytesseract + Pillow | 0.3.13 / 11.0.0 | Scanned PDF handling |
| Document Generation | Jinja2 + WeasyPrint + ReportLab | — | Legal draft PDF export |
| GPU Compute | Lightning AI | — | BGE-M3 embedding generation |
| Frontend (planned) | Next.js (React) | — | Role-based dashboard with SSR |

---

## LLM Provider Strategy

All LLM calls go through **LiteLLM** — no direct SDK per provider. The active model is resolved at crew-build time from which API key is set:

```
Priority 1: MISTRAL_API_KEY  → mistral/mistral-large-latest   (preferred — no daily cap)
Priority 2: GROQ_API_KEY     → groq/llama-3.3-70b-versatile   (fallback — 100K tokens/day, 12K TPM)
Priority 3: DEEPSEEK_API_KEY → deepseek/deepseek-chat          (last resort)
None set                     → RuntimeError at startup
```

**LLM factory functions** — the same model resolves differently per task:

| Factory | Temp | Max Tokens | Used By |
|---|---|---|---|
| `get_fast_llm()` | 0.1 | 2048 | Query Analyst, Response Formatter |
| `get_light_llm()` | 0.0 | 4096 | Retrieval Specialist, Citation Checker |
| `get_standard_llm()` | 0.1 | 4096 | General purpose |
| `get_reasoning_llm()` | 0.3 | 8192 | Legal Reasoner (IRAC analysis) |
| `get_drafting_llm()` | 0.2 | 8192 | Document Drafter |

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                            CLIENT LAYER                                 │
│   Citizen App  │  Lawyer Portal  │  Police Dashboard  │  Admin Panel   │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │  REST / SSE  (JWT Bearer)
┌───────────────────────────────▼─────────────────────────────────────────┐
│                    FastAPI  (Port 8000)  /api/v1                        │
│  CORS  │  Request-ID  │  Response-Timing  │  JWT Auth  │  Rate Limiting  │
│  /auth  /query  /cases  /documents  /sections  /translate  /voice  /admin│
└───────────────────────────────┬─────────────────────────────────────────┘
                                │
                    ┌───────────▼────────────┐
                    │  Redis Cache Check      │  HIT → return cached JSON
                    │  (24h DIRECT / 1h FULL) │
                    └───────────┬────────────┘
                                │ MISS
                    ┌───────────▼────────────┐
                    │     Query Router        │
                    │  (regex tier detection) │
                    └───┬───────────────┬────┘
                        │ DIRECT        │ FULL CREW
           ┌────────────▼──────┐   ┌───▼───────────────────────────────┐
           │  Zero-LLM Tools   │   │          CrewAI Pipeline           │
           │  CitationVerif.   │   │  Query Analyst (get_fast_llm)      │
           │  StatuteNorm.     │   │    ↓                               │
           │  (~50–300ms)      │   │  Retrieval Specialist (light_llm)  │
           └────────────┬──────┘   │    ↓                               │
                        │          │  Legal Reasoner* (reasoning_llm)   │
                        │          │    ↓  (* lawyer/advisor only)       │
                        │          │  Citation Checker (light_llm)       │
                        │          │    ↓                               │
                        │          │  Response Formatter (fast_llm)     │
                        │          └───────────────────┬───────────────┘
                        │                              │
                        └──────────────────────────────┘
                                        │
              ┌─────────────────────────▼──────────────────────────────┐
              │                    Qdrant Vector DB                     │
              │   legal_sections │ legal_sub_sections │ sc_judgments   │
              │   law_transition_context │ document_templates           │
              │   Hybrid Search: 1024-dim BGE-M3 dense + BM25 sparse   │
              │   Weighted RRF  │  Score Boosting  │  MMR Diversity     │
              └────────────────────────────────────────────────────────┘
```

---

## Multi-Agent Pipeline

Five CrewAI agents run sequentially. Crew composition varies by user role.

**MANDATORY ORDER: CitationChecker ALWAYS runs BEFORE ResponseFormatter.**

### Agent Definitions

| Agent | LLM Factory | Max Iter | Tools | Role |
|---|---|---|---|---|
| **Query Analyst** | `get_fast_llm()` | 3 | QueryClassifierTool, StatuteNormalizationTool | Classify domain, decompose query, identify entities |
| **Retrieval Specialist** | `get_light_llm()` | 4 | StatuteNormalizationTool, QdrantHybridSearchTool | Hybrid Qdrant search + RRF + CrossEncoder rerank |
| **Legal Reasoner** | `get_reasoning_llm()` | 3 | IRACAnalyzerTool | IRAC analysis — Issue, Rule, Application, Conclusion |
| **Citation Checker** | `get_light_llm()` | 8 | CitationVerificationTool | Verify every cite; strip NOT_FOUND; remove hallucinated sections |
| **Response Formatter** | `get_fast_llm()` | 2 | **None** | Role-appropriate formatting on verified context only |

### Crew Pipelines by Role

```
Citizen:        Query Analyst → Retrieval Specialist → Citation Checker → Response Formatter
Lawyer:         Query Analyst → Retrieval Specialist → Legal Reasoner → Citation Checker → Response Formatter
Legal Advisor:  Query Analyst → Retrieval Specialist → Legal Reasoner → Citation Checker → Response Formatter
Police:         Query Analyst → Retrieval Specialist → Citation Checker → Response Formatter
Document Draft: Query Analyst → Document Drafter → Citation Checker
```

### Hallucination Prevention

**Citation Checker enforces:**
- Any 4-digit number (2020–2026) flagged as hallucinated year, removed before delivery
- SC case names must match verbatim from retrieved precedent list
- Any section returning `NOT_FOUND` from CitationVerificationTool is stripped entirely
- RetrievalSpecialist must reproduce tool output entries `[1]`, `[2]`, `[3]` exactly as returned

**Response Formatter enforces:**
- Has **zero tools** — operates on verified context only, never on raw model knowledge
- If CitationChecker output is UNVERIFIED with zero verified citations → outputs standard cannot-verify message
- Cannot upgrade confidence level (e.g. cannot promote Low → Medium)
- Never cites IPC sections, out-of-scope laws, or cases not present in verified context

**System rule:** If confidence < 0.5 → *"I cannot provide a verified answer to this query. Please consult a qualified legal professional."*

---

## Query Routing

The Query Router sits between the API and CrewAI. It detects whether a query can be answered with zero LLM calls (**DIRECT tier**) or needs the full crew (**FULL tier**).

```
POST /query/ask
    │
    ├─ Redis cache? → HIT: return cached response
    │
    └─ MISS: Query Router
              │
              ├─ DIRECT tier (regex match — zero LLM, ~50–300ms)
              │   ├─ Pattern A: "BNS 103", "BNSS s.482", "BSA section 23"
              │   │   └─ Tool: CitationVerificationTool (Qdrant scroll, no embedding)
              │   ├─ Pattern B: "IPC 302 in BNS", "CrPC 438 equivalent"
              │   │   └─ Tool: StatuteNormalizationTool (DB lookup)
              │   └─ Pattern C: "SRA 10", "TPA 58", "CPC Order 7"
              │       └─ Tool: CitationVerificationTool
              │
              └─ FULL tier (all other queries → CrewAI pipeline, ~60–120s)
```

**Regex safeguards (preventing false DIRECT matches):**
- `_SEC_NUM = r"(\d{1,3}[A-Za-z]?)(?!\d)"` — max 3-digit section numbers with negative lookahead prevents 4-digit years (e.g. "BNS 2023") from matching as section references
- Cache TTL: 24h for DIRECT (statutory text is stable), 1h for FULL (new documents may be indexed)

---

## RAG Retrieval Pipeline

```
User Query
    │
    ▼
[Query Analyst] — identifies act_filter, era_filter, query_type, mmr_diversity
    │
    ▼
[Retrieval Specialist] — BGE-M3 query embedding (NO instruction prefix)
    │
    ├── Dense Prefetch   (top_k × 5 candidates, 1024-dim cosine)
    └── Sparse Prefetch  (top_k × 5 candidates, BM25)
    │
    ▼
Weighted Reciprocal Rank Fusion  (RRF, k=60)
    — weights vary by query_type (see table below)
    │
    ▼
Client-side Score Boosting
    ├── Era recency:           +0.15  (naveen_sanhitas over colonial_codes)
    ├── Extraction confidence: ×0.85–1.0 (penalises OCR-uncertain text)
    └── Offence classification: +0.10  (is_offence=True for criminal queries)
    │
    ▼
CrossEncoder Re-ranking  (cross-encoder/ms-marco-MiniLM-L-6-v2)
    — evaluates (query, text) pairs jointly; graceful fallback if load fails
    │
    ▼
MMR Diversity  (if mmr_diversity > 0)
    — same act_code similarity = 1.0; different act = 0.2
    — diversity=0.3 forces multi-act coverage for civil/layman queries
    │
    ▼
Role-based Access Filter  (user_access_level payload filter)
    │
    ▼
[Citation Checker] — every source cross-checked against legal_sections collection
```

**Query type weights (dense\_weight, sparse\_weight):**

| Query Type | Dense | Sparse | Use Case |
|---|---|---|---|
| `section_lookup` | 1.0 | 4.0 | Explicit section reference — favour keyword match |
| `criminal_offence` | 2.0 | 1.5 | Offence + punishment queries |
| `civil_conceptual` | 3.0 | 1.0 | Conceptual civil law — favour semantic |
| `procedural` | 2.0 | 1.0 | Step-by-step procedural queries |
| `old_statute` | 1.0 | 3.0 | IPC/CrPC reference mapping |
| `default` | 2.0 | 1.0 | Fallback |

**Embeddings — BGE-M3 (BAAI/bge-m3, FlagEmbedding 1.3.3):**
- Dense vectors: **1024 dimensions**, cosine distance
- Sparse vectors: lexical weight dict (token\_id → float)
- Asymmetric strategy:
  - **Index time**: prepend `"Represent this Indian legal provision for retrieval: "` to document text
  - **Query time**: NO prefix — raw query text embedded directly

---

## Qdrant Collections

| Collection | Dense Dim | Quantization | Purpose |
|---|---|---|---|
| `legal_sections` | 1024 + Sparse | INT8 scalar | Primary statute retrieval (section-level) |
| `legal_sub_sections` | 1024 + Sparse | INT8 scalar | Granular clause/proviso/explanation retrieval |
| `sc_judgments` | 1024 + Sparse | INT8 scalar | Supreme Court judgment chunks (1950–2024) |
| `law_transition_context` | 1024 + Sparse | INT8 scalar | IPC→BNS / CrPC→BNSS transition mappings |
| `document_templates` | 1024 | INT8 scalar | Legal document drafting templates |

**Payload indexes (all collections):** `act_code`, `act_name`, `section_number`, `section_title`, `chapter`, `court`, `case_name`, `case_citation`, `legal_domain`, `era`, `is_offence` (bool), `extraction_confidence` (float), `language`, `state`, `user_access_level`, `judgment_date`, `source_url`

**Era values:** `naveen_sanhitas` (BNS/BNSS/BSA — effective 2024-07-01), `colonial_codes` (IPC/CrPC/IEA), `civil_statutes` (TPA/SRA/CPC/ICA/CPA etc.)

**Current indexed counts (production):**

| Collection | Records |
|---|---|
| `legal_sections` | 1,933 |
| `legal_sub_sections` | 2,104 |
| `sc_judgments` | 37,965 |
| `law_transition_context` | 1,440 |

---

## Project Structure

```
neethi-ai/
├── backend/
│   ├── agents/
│   │   ├── agents/
│   │   │   ├── query_analyst.py        # get_fast_llm() — classify, decompose, expand
│   │   │   ├── retrieval_specialist.py # get_light_llm() — hybrid search, RRF, rerank
│   │   │   ├── legal_reasoner.py       # get_reasoning_llm() — IRAC (lawyer/advisor only)
│   │   │   ├── citation_checker.py     # get_light_llm() — verify every cite, strip NOT_FOUND
│   │   │   └── response_formatter.py   # get_fast_llm() — no tools, role-specific format
│   │   ├── tools/
│   │   │   ├── citation_verification_tool.py   # Qdrant scroll — section existence check
│   │   │   ├── qdrant_search_tool.py            # Hybrid search wrapper
│   │   │   ├── query_classifier_tool.py         # Domain + intent classification
│   │   │   ├── irac_analyzer_tool.py            # IRAC structured analysis
│   │   │   ├── cross_reference_tool.py          # Cross-act section linking
│   │   │   ├── section_lookup_tool.py           # Direct section text fetch
│   │   │   └── statute_normalization_tool.py    # IPC→BNS / CrPC→BNSS mapping
│   │   ├── crew_config.py     # make_layman_crew / make_lawyer_crew / make_advisor_crew / make_police_crew
│   │   └── query_router.py    # DIRECT vs FULL tier detection (regex + cache)
│   ├── api/
│   │   ├── routes/
│   │   │   ├── auth.py        # POST /register, POST /login
│   │   │   ├── query.py       # POST /ask, POST /ask/stream (SSE)
│   │   │   ├── cases.py       # POST /search, POST /analyze
│   │   │   ├── documents.py   # POST /draft, POST /draft/{id}/pdf
│   │   │   ├── sections.py    # GET /acts, GET /acts/{id}/sections/{num}
│   │   │   ├── resources.py   # POST /nearby (SerpAPI)
│   │   │   ├── translate.py   # POST /text (Sarvam AI)
│   │   │   ├── voice.py       # POST /tts, POST /stt
│   │   │   └── admin.py       # POST /ingest, GET /health
│   │   ├── schemas/           # Pydantic request/response models (one file per router)
│   │   └── dependencies.py    # get_current_user, get_db, get_cache, check_rate_limit
│   ├── config/
│   │   └── llm_config.py      # get_fast_llm / get_light_llm / get_reasoning_llm / get_drafting_llm
│   ├── db/
│   │   ├── migrations/        # Alembic SQL migrations (001_initial, 002_judgments)
│   │   ├── models/
│   │   │   ├── user.py            # User, Role, query_count_today
│   │   │   └── legal_foundation.py # Acts, Sections, SubSections, TransitionMappings
│   │   ├── repositories/          # Async data access (section, judgment, transition repos)
│   │   └── seed_data/             # BNSS Schedule I seed JSON
│   ├── document_drafting/         # Jinja2 templates + WeasyPrint PDF generation
│   ├── preprocessing/
│   │   ├── parsers/act_parser.py  # Section extraction; compound numbering (CPC First Schedule)
│   │   ├── extractors/            # PyMuPDF two-pass + OCR fallback
│   │   ├── cleaners/              # Header/footer/watermark removal
│   │   ├── classifiers/           # is_offence classification
│   │   ├── enrichers/             # JSON metadata merge (act_code, era, domain)
│   │   ├── validators/            # Confidence scoring; < 0.5 → human_review_queue
│   │   ├── pipeline.py            # Orchestrates all stages; v2.0.0
│   │   └── sc_judgment_ingester.py # Supreme Court bulk ingester
│   ├── rag/
│   │   ├── embeddings.py      # BGEM3Embedder — 1024-dim dense + sparse, asymmetric prefix
│   │   ├── hybrid_search.py   # Weighted RRF + Score Boost + MMR (sync + async)
│   │   ├── indexer.py         # Batch upsert to Qdrant
│   │   ├── qdrant_setup.py    # Collection creation (5 collections, INT8 quantization)
│   │   ├── reranker.py        # CrossEncoder ms-marco-MiniLM-L-6-v2; singleton; graceful fallback
│   │   └── rrf.py             # Reciprocal Rank Fusion (k=60)
│   ├── services/
│   │   └── cache.py           # Redis primary + in-memory fallback; key: neethi:v1:{role}:{sha256}
│   ├── tests/
│   │   ├── test_retrieval.py       # RAG retrieval quality benchmarks
│   │   ├── test_full_pipeline.py   # Full pipeline with act_filter / era_filter / query_type
│   │   ├── test_api_e2e.py         # End-to-end API tests (register → login → query)
│   │   ├── test_phase4_tools.py    # CrewAI tools unit tests
│   │   └── test_phase5_agents.py   # Agent pipeline integration tests
│   └── main.py                # FastAPI app; CORS + timing middleware; startup DB + cache warmup
├── data/
│   ├── raw/
│   │   ├── acts/
│   │   │   ├── *.json          # Structured enrichment JSON per act (9 civil acts)
│   │   │   └── *.pdf           # Source PDFs — NOT committed (download separately)
│   │   ├── bns_complete.json   # BNS 2023 — 358 sections (complete act)
│   │   ├── bnss_complete.json  # BNSS 2023 — full act
│   │   └── bsa_complete.json   # BSA 2023 — full act
│   ├── keywords/
│   │   └── bns_procedural_keywords.txt
│   └── scripts/
│       ├── run_ingestion.py    # PDF/JSON → parsed sections → PostgreSQL
│       ├── run_indexing.py     # BGE-M3 embed → Qdrant upsert
│       └── run_activation.py   # Activate IPC→BNS transition mappings
├── docs/
│   ├── architecture/           # Mermaid architecture diagrams (5 files)
│   ├── development/            # Data pipeline breakdown notes
│   ├── embedding_model_comparison.md   # BGE-M3 selection rationale
│   ├── document_drafting_design.md
│   ├── citation_verification_flow.md
│   ├── retrieval_quality_analysis.md   # Failure analysis + Phase 1 fixes
│   ├── tech_stack_index.md
│   └── indian_legal_data_sources.md    # Where to obtain legal PDFs
├── scripts/
│   ├── run_api.sh                  # Startup + dependency verification
│   ├── tag_sc_judgment_domains.py  # Domain-tag SC judgments in Qdrant
│   ├── reindex_unindexed_sections.py
│   ├── sarvam_extract.py           # Sarvam AI translation pipeline
│   └── verify.py                   # General verification utility
├── stitch/                     # UI prototype mockups (8 HTML files — all 4 roles)
├── .env.example                # All required env vars with descriptions
├── .gitattributes              # LF line endings enforced
├── .gitignore
├── alembic.ini
├── CLAUDE.md                   # Agent roles, codebase rules, architecture spec
├── LICENSE                     # MIT
├── plan.md                     # Full architecture and implementation plan
└── requirements.txt            # Consolidated Python dependencies
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
# Edit .env — minimum required: DATABASE_URL, QDRANT_URL, MISTRAL_API_KEY, JWT_SECRET_KEY

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
# --- Database (Supabase PostgreSQL) ---
DATABASE_URL=postgresql+asyncpg://postgres:YOUR_PASSWORD@db.YOUR_PROJECT_REF.supabase.co:5432/postgres

# --- Vector Database (Qdrant Cloud) ---
QDRANT_URL=https://<cluster-id>.<region>.cloud.qdrant.io:6333
QDRANT_API_KEY=<your-qdrant-api-key>

# --- LLM Providers (first key found is used as primary) ---
MISTRAL_API_KEY=<your-mistral-key>       # PRIMARY — mistral-large-latest, no daily cap
GROQ_API_KEY=<your-groq-key>            # FALLBACK 1 — llama-3.3-70b, 100K tokens/day cap
DEEPSEEK_API_KEY=<your-deepseek-key>    # FALLBACK 2 — deepseek-chat
ANTHROPIC_API_KEY=<your-anthropic-key>  # Optional — document drafting override

# --- Auth ---
JWT_SECRET_KEY=<long-random-secret-min-32-chars>
JWT_ALGORITHM=HS256
JWT_EXPIRY_HOURS=24                      # Default: 24 hours

# --- Cache (Upstash Redis) ---
REDIS_URL=redis://localhost:6379         # Local dev
# REDIS_URL=rediss://default:<token>@<host>.upstash.io:6380  # Production (TLS)
CACHE_TTL_DIRECT=86400                   # 24h — statutory text is stable
CACHE_TTL_FULL=3600                      # 1h  — LLM responses

# --- External Services ---
SARVAM_API_KEY=<your-sarvam-key>         # Indian language translation + TTS/STT
SERP_API_KEY=<your-serpapi-key>          # Nearby legal resources
THESYS_API_KEY=<your-thesys-key>         # Visual UI components for citizens

# --- Embeddings ---
BGE_M3_MODEL_PATH=BAAI/bge-m3           # Downloads ~2.3 GB on first use

# --- App ---
ENVIRONMENT=development                  # or: production
LOG_LEVEL=INFO
CORS_ORIGINS=http://localhost:3000,https://neethiai.com
```

---

## Running on Lightning AI (GPU)

Lightning AI has PyTorch + CUDA pre-installed. **Do NOT reinstall torch** — it will downgrade to CPU.

```bash
# 1. Verify GPU is available (must print True)
python -c "import torch; print(torch.cuda.is_available())"

# 2. Use the setup script (installs deps, verifies imports, starts server)
bash scripts/run_api.sh

# 3. If torch was accidentally downgraded to CPU
pip install torch --index-url https://download.pytorch.org/whl/cu121

# 4. First run — BGE-M3 downloads ~2.3 GB from HuggingFace automatically
python -c "from backend.rag.embeddings import BGEM3Embedder; BGEM3Embedder()"

# Note: nest_asyncio is NOT applied in main.py — CrewAI v1.9.x handles it internally.
# Start uvicorn with --loop asyncio to avoid uvloop conflict.
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --loop asyncio
```

---

## Data Ingestion

Source PDFs are not committed to git (too large). Download them separately — see [`docs/indian_legal_data_sources.md`](docs/indian_legal_data_sources.md). Then run:

```bash
# Stage 1 — Parse PDFs/JSONs → structured sections → PostgreSQL
python data/scripts/run_ingestion.py

# Stage 2 — BGE-M3 embed + Qdrant index (GPU recommended)
python data/scripts/run_indexing.py --mode setup        # Create Qdrant collections
python data/scripts/run_indexing.py --act ALL           # Index all acts
python data/scripts/run_indexing.py --mode transition   # Activate IPC→BNS mappings

# Stage 3 — Ingest Supreme Court judgments
python backend/preprocessing/sc_judgment_ingester.py

# Stage 4 — Domain-tag SC judgments (criminal/civil/constitutional etc.)
python scripts/tag_sc_judgment_domains.py
```

**Ingestion pipeline stages (pipeline.py v2.0.0):**

1. Load enrichment JSON (act_code, era, domain, keywords)
2. PDF text extraction — two-pass (direct text + OCR fallback)
3. Text cleaning (headers, footers, watermarks, page numbers)
4. Section boundary parsing (`act_parser.py`)
5. Confidence scoring — sections < 0.5 → `human_review_queue` only
6. PostgreSQL insert (sections + sub_sections tables)
7. Transition mappings (IPC→BNS, CrPC→BNSS — effective 2024-07-01)
8. Extraction audit records

---

## API Reference

Base URL: `http://localhost:8000/api/v1`

| Method | Endpoint | Description | Auth |
|---|---|---|---|
| POST | `/auth/register` | Register with role (`citizen`/`lawyer`/`legal_advisor`/`police`) | — |
| POST | `/auth/login` | JWT login → `{access_token, expires_in, user}` | — |
| GET | `/health` | API + Qdrant + Redis health check | — |
| POST | `/query/ask` | Legal query — role-aware crew + citation verified response | JWT |
| POST | `/query/ask/stream` | Streaming response (SSE) | JWT |
| POST | `/cases/search` | Semantic search across 37,965 SC judgments | JWT |
| POST | `/cases/analyze` | Deep IRAC case analysis | JWT |
| POST | `/documents/draft` | Generate legal document from template + fields | JWT |
| POST | `/documents/draft/{id}/pdf` | Export draft as PDF | JWT |
| GET | `/sections/acts` | List all indexed acts | JWT |
| GET | `/sections/acts/{id}/sections/{num}` | Get specific section text | JWT |
| POST | `/resources/nearby` | Find nearby lawyers / courts / DLSA (SerpAPI) | JWT |
| POST | `/translate/text` | Translate via Sarvam AI | JWT |
| POST | `/voice/tts` | Text-to-speech | JWT |
| POST | `/voice/stt` | Speech-to-text | JWT |
| POST | `/admin/ingest` | Ingest new legal documents | Admin |
| GET | `/admin/health` | Detailed system health + Qdrant collection stats | Admin |

**Response shape (`POST /query/ask`):**

```json
{
  "query_id": "uuid",
  "query": "original query text",
  "response": "formatted legal response",
  "verification_status": "VERIFIED | PARTIALLY_VERIFIED | UNVERIFIED",
  "confidence": "high | medium | low",
  "citations": [{"act_code": "BNS_2023", "section_number": "115", "verification": "VERIFIED"}],
  "precedents": [],
  "user_role": "citizen",
  "processing_time_ms": 99486,
  "cached": false,
  "disclaimer": "This is AI-assisted legal information..."
}
```

**Quick test (citizen end-to-end):**

```bash
# Register
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"full_name":"Rahul Sharma","email":"rahul@example.com","password":"Secret123","role":"citizen"}'

# Login → copy access_token
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"rahul@example.com","password":"Secret123"}'

# Query (paste token)
curl -X POST http://localhost:8000/api/v1/query/ask \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"query":"Someone slapped and threatened me in public. What law applies under BNS?","language":"en"}'
```

---

## Testing

```bash
# Run all tests
pytest backend/tests/ -v

# Specific suites
pytest backend/tests/test_retrieval.py -v           # RAG retrieval quality benchmarks
pytest backend/tests/test_full_pipeline.py -v       # Full pipeline (act_filter, era_filter, query_type)
pytest backend/tests/test_api_e2e.py -v             # End-to-end API (register → login → query)
pytest backend/tests/test_phase4_tools.py -v        # CrewAI tools unit tests
pytest backend/tests/test_phase5_agents.py -v       # Agent pipeline integration tests

# With HTML coverage report
pytest backend/tests/ --cov=backend --cov-report=html
open htmlcov/index.html
```

**Coverage targets:** 80% minimum for retrieval, citation verification, and document drafting paths.

---

## Legal Data Coverage

**Acts indexed with full section text:**

| Act | Code | Count | Era |
|---|---|---|---|
| Bharatiya Nyaya Sanhita 2023 | BNS_2023 | 358 | naveen_sanhitas |
| Bharatiya Nagarik Suraksha Sanhita 2023 | BNSS_2023 | 531 | naveen_sanhitas |
| Bharatiya Sakshya Adhiniyam 2023 | BSA_2023 | 170 | naveen_sanhitas |
| Indian Penal Code 1860 | IPC_1860 | 511 | colonial_codes |
| Code of Criminal Procedure 1973 | CrPC_1973 | 484 | colonial_codes |
| Indian Evidence Act 1872 | IEA_1872 | 167 | colonial_codes |
| Code of Civil Procedure 1908 | CPC_1908 | 387 | civil_statutes |
| Hindu Succession Act 1956 | HSA_1956 | 28 | civil_statutes |
| Hindu Marriage Act 1955 | HMA_1955 | — | civil_statutes |
| Transfer of Property Act 1882 | TPA_1882 | — | civil_statutes |
| Specific Relief Act 1963 | SRA_1963 | — | civil_statutes |
| Indian Contract Act 1872 | ICA_1872 | — | civil_statutes |
| Limitation Act 1963 | LA_1963 | — | civil_statutes |
| Consumer Protection Act 2019 | CPA_2019 | — | civil_statutes |
| Arbitration & Conciliation Act 1996 | ACA_1996 | — | civil_statutes |

**Supreme Court Judgments:** 37,965 indexed (1950–2024), domain-tagged across Criminal, Civil, Constitutional, Family, and Corporate law.

**Transition Mappings:** 1,440 IPC→BNS and CrPC→BNSS section mappings — effective date 2024-07-01.

---

## Key References

- **Architecture Plan**: [`plan.md`](plan.md)
- **Agent & Codebase Rules**: [`CLAUDE.md`](CLAUDE.md)
- **Embedding Model Selection**: [`docs/embedding_model_comparison.md`](docs/embedding_model_comparison.md)
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

*Built for the Indian legal ecosystem. Every response is source-cited, role-formatted, and double-verified before delivery.*
