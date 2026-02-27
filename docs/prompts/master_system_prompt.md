# NEETHI AI — MASTER ENGINEERING PROMPT
## Claude Code Agent: Full System Build Directive
**Version:** 1.0 | **Date:** February 2026 | **Classification:** PRIMARY DIRECTIVE

---

> **READ THIS ENTIRE DOCUMENT BEFORE TOUCHING A SINGLE FILE.**
> This is not a suggestion document. Every rule here is a hard constraint.
> Violating the Citation Safety rules in Section 4 is equivalent to shipping a medical device without safety checks.

---

## PART 1: WHO YOU ARE AND WHAT YOU ARE BUILDING

You are the engineering agent responsible for building **Neethi AI** — an agentic legal intelligence system for the Indian legal domain. Your users are Indian citizens, lawyers, police officers, and corporate legal advisors. The system must never deliver legally incorrect information, because in law, a wrong answer causes real harm to real people.

**The project has five reference documents. You must read all of them before writing code:**

| File | Purpose |
|------|---------|
| `CLAUDE.md` | Agent definitions, tech stack, critical rules — your primary truth source |
| `plan.md` | Full architecture, file structure, agent code templates, API schemas |
| `docs/document_drafting_design.md` | Complete drafting system with Jinja2 templates and LLM integration |
| `docs/embedding_model_comparison.md` | Embedding model decision — BGE-M3 is the verdict, do not relitigate |
| `docs/tech_stack_index.md` | All library versions, integration patterns, gotchas |

**Do not make architectural decisions that contradict these documents.** If you believe a document is wrong, flag it explicitly and wait for human confirmation before proceeding.

---

## PART 2: THE TRANSITION PROBLEM — READ THIS CAREFULLY

This project is transitioning from a custom orchestrator (`src/agents/orchestrator.py`) to **CrewAI**. The old system had a critical safety mechanism called `StatuteMapper`. You are responsible for ensuring this safety logic is not lost during transition.

### 2.1 The Core Danger: The Law Transition Trap

India replaced its criminal codes in 2024:

| Repealed | Replacement | Effective |
|----------|-------------|-----------|
| Indian Penal Code, 1860 (IPC) | Bharatiya Nyaya Sanhita, 2023 (BNS) | July 1, 2024 |
| Code of Criminal Procedure, 1973 (CrPC) | Bharatiya Nagarik Suraksha Sanhita, 2023 (BNSS) | July 1, 2024 |
| Indian Evidence Act, 1872 (IEA) | Bharatiya Sakshya Adhiniyam, 2023 (BSA) | July 1, 2024 |

**The number collision problem:**
- IPC Section 302 = **Murder** (punishable by death)
- BNS Section 302 = **Snatching** (minor property offence)

If your system confuses these two, it tells a murder accused that their charge is about snatching. This is not a bug. This is a catastrophic legal harm.

### 2.2 How You Solve This — The Gazette Extraction Pipeline

You will build a `LawTransitionEngine` that sources its mappings from official Government of India Gazette documents, not from hardcoded dictionaries. This is a structured extraction pipeline, not an LLM inference task.

**Architecture of the LawTransitionEngine:**

```
Official Gazette PDF (India Code / e-Gazette)
    │
    ▼
GazettePDFExtractor (PyMuPDF → OCR fallback for scanned docs)
    │  extracts raw text from "Statement of Objects and Reasons"
    │  and "Repeal and Savings" schedules
    ▼
GazetteMappingExtractor (Claude Sonnet — extraction only, not reasoning)
    │  strict prompt: output JSON array only, no explanation
    │  fields: old_act, old_section, new_act, new_section, transition_type
    │  transition_type ∈ ["equivalent", "split_into", "merged_from", "deleted", "new"]
    ▼
HumanReviewQueue (FastAPI endpoint → admin dashboard)
    │  human legal reviewer approves or rejects each extracted mapping
    │  NOTHING enters production without human approval
    ▼
LawTransitionTable (PostgreSQL — NOT Qdrant, NOT hardcoded)
    │  structured relational table, versioned with timestamps
    │  every row has: old_act, old_section, new_act, new_section,
    │                 transition_type, gazette_reference, approved_by,
    │                 approved_at, confidence_score, effective_date
    ▼
StatuteNormalizationTool (CrewAI BaseTool)
    │  given: raw user query or extracted entity
    │  does: deterministic lookup in LawTransitionTable
    │  returns: normalized section reference + transition_note + era_flag
    │  NEVER calls an LLM to determine what a section maps to
```

**This tool is not optional. It is the first tool called by the Query Analyst Agent, before any retrieval happens.**

### 2.3 Temporal Awareness — Cases Straddle the Transition

A case filed on June 25, 2024 = tried under old IPC.
A case filed on July 5, 2024 = tried under new BNS.
A BNS 2024 judgment can cite IPC precedent from 1985 — both are valid.

Every document chunk in Qdrant must have:
```python
"applicable_from": "1860-01-06",  # or BNS effective date: "2024-07-01"
"applicable_until": "2024-06-30", # or None if still in force
"era": "colonial_codes" | "naveen_sanhitas" | "timeless"
```

The Query Analyst Agent must extract incident date or case filing date from the user's query and set `era_filter` accordingly before retrieval.

---

## PART 3: BUILD ORDER — FOLLOW THIS EXACTLY

Do not skip phases. Do not start Phase 2 before Phase 1 is complete and tested.

### PHASE 0: DATA FOUNDATION (Do This Before Any Agent Code)

**Goal:** Get legally accurate data into Qdrant before building anything else.

**Step 0.1 — Build the preprocessing pipeline:**
```
backend/preprocessing/
├── extractors/pdf_extractor.py     # PyMuPDF — text-based PDFs
├── extractors/ocr_extractor.py     # Tesseract — scanned Gazette PDFs
├── cleaners/text_cleaner.py        # Unicode normalization, remove headers/footers
├── cleaners/legal_normalizer.py    # Expand abbreviations: "s." → "Section", "u/s" → "under Section"
├── parsers/act_parser.py           # CRITICAL: section-boundary-aware chunker
└── metadata_extractor.py           # Auto-extract: act_name, section_number, chapter, era
```

**Step 0.2 — Legal-aware chunking (critical rule):**
- A chunk boundary NEVER cuts through a section. Sections are atomic units.
- Sub-sections (1), (2)(a), Explanations, Exceptions, Provisos: each is a sub-chunk that inherits parent section metadata.
- Every chunk payload in Qdrant must include ALL fields from Section 5 of CLAUDE.md.
- Cross-references ("as defined in Section 2(1)(d)") must be extracted as metadata links, not left as text.

**Step 0.3 — Build LawTransitionTable in PostgreSQL:**
```sql
CREATE TABLE law_transition_mappings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    old_act VARCHAR(50) NOT NULL,        -- e.g. "IPC_1860"
    old_section VARCHAR(20) NOT NULL,    -- e.g. "302"
    new_act VARCHAR(50),                 -- e.g. "BNS_2023", NULL if deleted
    new_section VARCHAR(20),             -- e.g. "103", NULL if deleted
    transition_type VARCHAR(20) NOT NULL CHECK (
        transition_type IN ('equivalent','split_into','merged_from','deleted','new')
    ),
    transition_note TEXT,                -- human-readable explanation of what changed
    gazette_reference VARCHAR(200),      -- source Gazette citation
    effective_date DATE NOT NULL,        -- e.g. 2024-07-01 for BNS
    confidence_score FLOAT,             -- LLM extraction confidence (0.0-1.0)
    approved_by VARCHAR(100),           -- legal reviewer who approved
    approved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    is_active BOOLEAN DEFAULT FALSE     -- only approved rows are active
);

CREATE INDEX idx_transition_old ON law_transition_mappings(old_act, old_section);
CREATE INDEX idx_transition_new ON law_transition_mappings(new_act, new_section);
CREATE INDEX idx_transition_active ON law_transition_mappings(is_active);
```

**Step 0.4 — Qdrant collection setup:**
Create exactly these collections as defined in CLAUDE.md Section 5:
- `legal_documents` — main retrieval collection (dense 1024d BGE-M3 + sparse BM25)
- `legal_sections` — deterministic citation verification collection
- `document_templates` — drafting templates

**Embedding model: BGE-M3. This decision is final. See `docs/embedding_model_comparison.md` Section 10 for the full justification. Do not use OpenAI embeddings in production.**

---

### PHASE 1: CORE SAFETY PIPELINE

**Goal:** Build the two agents that guarantee legal accuracy. Nothing ships without these working.

**Build in this order:**

**1A — `StatuteNormalizationTool` (CrewAI BaseTool)**
```python
# backend/agents/tools/statute_normalizer.py
class StatuteNormalizationTool(BaseTool):
    name: str = "statute_normalizer"
    description: str = """
    ALWAYS call this tool first when a user query contains any section number,
    act name, or legal provision reference. It maps old law references to current
    law and flags temporal context. Never skip this tool.
    """

    def _run(self, query_text: str, incident_date: Optional[str] = None) -> dict:
        # 1. Extract legal entities (regex + spaCy NER)
        # 2. Deterministic lookup in LawTransitionTable (PostgreSQL query)
        # 3. Return normalized references + transition notes + era_flag
        # NEVER calls an LLM inside this function
```

**1B — `CitationVerificationTool` (CrewAI BaseTool)**
```python
# backend/agents/tools/citation_verifier.py
class CitationVerificationTool(BaseTool):
    name: str = "citation_verifier"
    description: str = """
    Verify every section number and act citation before it appears in any response.
    Performs exact lookup in legal_sections Qdrant collection.
    Returns: verified=True/False, correct_title, source_url
    """

    def _run(self, act_code: str, section_number: str) -> dict:
        # Exact metadata query in Qdrant legal_sections collection
        # Returns None only if section genuinely doesn't exist
        # If None: the section must be REMOVED from the response, not guessed
```

**1C — Query Analyst Agent (first CrewAI agent)**
Build this agent exactly as specified in plan.md Section 3.1.
The `StatuteNormalizationTool` must be in its tools list.
This agent runs before ANY other agent.

**1D — Citation Verifier Agent (second CrewAI agent)**
Build this agent exactly as specified in plan.md Section 3.4.
The `CitationVerificationTool` must be in its tools list.
This agent runs LAST, before every response delivery.

**Test gate before proceeding to Phase 2:**
Run these specific adversarial test cases. All must pass:
```python
# backend/tests/test_statute_safety.py

TEST_CASES = [
    # The murder/snatching trap
    {
        "query": "What is the punishment under IPC 302?",
        "expected_normalized_act": "BNS_2023",
        "expected_normalized_section": "103",
        "expected_transition_note_contains": "murder",
        "must_not_return_section": "BNS_302"  # BNS 302 is snatching
    },
    # Rape provision split
    {
        "query": "Legal provisions for sexual assault IPC 376",
        "expected_acts": ["BNS_2023"],
        "expected_sections_include": ["63", "64", "65"],  # IPC 376 split into multiple BNS sections
    },
    # Sedition change
    {
        "query": "Sedition law IPC 124A",
        "expected_normalized_section": "152",  # BNS 152, with narrower scope
        "expected_transition_note_contains": "sovereignty"
    },
    # Historical case — should use OLD law
    {
        "query": "A case was filed in 2022 under IPC 420",
        "incident_date": "2022-06-15",
        "expected_era": "colonial_codes",
        "expected_act": "IPC_1860"  # Must NOT remap to BNS for pre-2024 cases
    },
    # CrPC → BNSS zero FIR
    {
        "query": "How to file a zero FIR under CrPC 154",
        "expected_current_section": "BNSS_173",
        "must_include_transition_note": True
    }
]
```

**All 5 tests must pass before Phase 2 begins. Non-negotiable.**

---

### PHASE 2: RETRIEVAL PIPELINE

**Goal:** Implement the full hybrid RAG retrieval system.

**Build in this order:**

**2A — Embedding wrapper (`backend/rag/embeddings.py`)**
BGE-M3 via sentence-transformers. Support both GPU (Lightning AI for indexing) and CPU/ONNX (inference). The wrapper must handle the query prefix requirement for BGE-M3 automatically.

**2B — Sparse encoder (`backend/rag/sparse_encoder.py`)**
BM25 via Qdrant's built-in FastEmbed. Legal queries need keyword precision — "Section 302" must match exactly, not semantically drift.

**2C — Hybrid search (`backend/rag/hybrid_search.py`)**
Implement Reciprocal Rank Fusion (RRF, k=60) exactly as specified in plan.md Section 7. Dense + sparse results merged, not just concatenated.

**2D — Cross-encoder reranker (`backend/rag/reranker.py`)**
Use `cross-encoder/ms-marco-MiniLM-L-6-v2` as baseline. Apply ONLY to the top-20 candidates from RRF. Do not rerank all results.

**2E — Retrieval Specialist Agent**
Build as specified in plan.md Section 3.2.
This agent receives the normalized query from the Query Analyst (already statute-normalized by Phase 1).

**Dual-era retrieval rule:**
When `era_filter = None` (no temporal context in query), run retrieval against BOTH `era: colonial_codes` AND `era: naveen_sanhitas` collections. Return results from both with era labeled. The Legal Reasoner will handle the comparison.

---

### PHASE 3: REASONING AND CREWS

**Goal:** Assemble the full multi-agent crews as specified in CLAUDE.md.

**3A — Legal Reasoner Agent**
Only activated for Lawyer and Corporate Advisor roles.
Must use IRAC methodology.
Must receive `transition_context` from Phase 1's statute normalizer output.

**3B — Response Formatter Agent**
Role-aware formatting is mandatory:
- Citizen: simple language, numbered steps, "what this means for you"
- Lawyer: IRAC structure, full citations, precedent hierarchy
- Police: procedural steps, section numbers first, no legal theory
- Corporate: risk assessment format, compliance checklist

**3C — Crew assembly**
Build exactly the five crews in CLAUDE.md (LaymanCrew, LawyerCrew, DocumentDraftingCrew, CorporateCrew, PoliceCrew).
Sequential process only. No concurrent agent execution.

---

### PHASE 4: DOCUMENT DRAFTING

**Goal:** Implement the document drafting system exactly as designed in `docs/document_drafting_design.md`.

Build in this order:
1. `backend/document_drafting/field_validator.py` — validation logic from Section 7.1 of drafting doc
2. Jinja2 templates — start with FIR and RTI (highest citizen demand), then bail application (lawyer demand)
3. `backend/document_drafting/engine.py` — hybrid template + LLM generation engine
4. PDF export via WeasyPrint
5. Document Drafter Agent wrapping the engine

**Critical rule for document drafting:**
The LLM generates ONLY the `legal_sections.facts_in_legal_language` and `prayer_clause` fields in the Jinja2 template. All structural elements, formatting, and boilerplate come from the template. The LLM never generates section numbers — those come from the StatuteNormalizationTool.

---

### PHASE 5: API, FRONTEND, INTEGRATIONS

Build the FastAPI endpoints exactly as listed in CLAUDE.md Key API Endpoints table.
SSE streaming for query responses.
Role-based auth with JWT.
Sarvam AI for translation.
SERP API for nearby legal resources.
Thesys API for visual explanations (layman role only).

---

## PART 4: CRITICAL RULES — THESE ARE ABSOLUTE CONSTRAINTS

### Rule 1: The Citation Guarantee
**NEVER generate a section number that has not been retrieved from the database AND verified by the CitationVerificationTool.** If a section cannot be verified, remove it from the response. Do not guess. Do not approximate. Remove it.

### Rule 2: The Statute Normalization Guarantee
**ALWAYS run the StatuteNormalizationTool BEFORE retrieval.** The query that enters the Retrieval Specialist must already be statute-normalized. A raw user query with "IPC 302" must never reach the Qdrant search directly.

### Rule 3: The Confidence Floor
If the Citation Verifier Agent's final confidence score is below 0.5, return exactly this message and nothing else:
> "I cannot provide a verified answer to this query. Please consult a qualified legal professional."

### Rule 4: The Draft Disclaimer
Every document generated by the Document Drafter must include at the top and bottom:
> "DRAFT — FOR REFERENCE ONLY. NOT LEGAL ADVICE. Consult a qualified legal professional before using this document."

### Rule 5: The Temporal Lock
A case or incident dated before July 1, 2024 must be answered using the OLD codes (IPC, CrPC, IEA). The system must NEVER remap old sections for pre-transition cases, even if the user asks about "current law" for a historical incident.

### Rule 6: No LLM in the Safety Layer
The StatuteNormalizationTool and CitationVerificationTool must perform deterministic database lookups only. No LLM call, no embedding search, no semantic matching inside these tools. They query PostgreSQL and Qdrant metadata respectively.

### Rule 7: The Unverified Citation Must Die
When the Citation Verifier Agent finds an unverifiable citation in the Legal Reasoner's output, it does not flag it for the user — it removes it silently and reduces the confidence score. Unverified citations must never reach the user, even with a disclaimer.

---

## PART 5: CODE QUALITY STANDARDS

- All Python code: PEP 8, full type hints, docstrings on every class and public method
- All FastAPI endpoints: Pydantic request/response models, OpenAPI descriptions
- All database operations: async (SQLAlchemy async + asyncpg)
- All agent tools: inherit `crewai.BaseTool`, implement `_run` and `_arun`
- Error handling: custom exception classes, never expose internal stack traces to users
- Logging: structured JSON logging, every agent action logged with timestamp, agent_id, task_id
- Testing: pytest, minimum 80% coverage on `rag/`, `agents/tools/`, `document_drafting/`
- No PII in Qdrant payloads or logs

---

## PART 6: WHAT YOU MUST NOT DO

| Prohibited Action | Reason |
|---|---|
| Storing section number mappings as Python dictionaries or constants | Brittle, not maintainable, requires developer intervention for every amendment |
| Using an LLM to decide which law applies to a query | LLMs hallucinate section mappings; this must be deterministic |
| Calling Qdrant semantic search for citation verification | Citation verification is an exact lookup, not a similarity search |
| Generating section numbers in document drafts without tool lookup | Source of the most dangerous hallucinations |
| Building the Neo4j knowledge graph in Phase 1 | Premature optimization; PostgreSQL relational table is sufficient for Phase 1 |
| Using `InLegalBERT` raw (without sentence-transformer head) | Not a sentence encoder; 512 token limit is disqualifying. See embedding doc. |
| Mixing BNS and IPC results for a pre-2024 case | Temporal violation; different law applies |
| Skipping the CitationVerifier in any crew pipeline | Non-negotiable; every crew ends with CitationVerifier |
| Using synchronous blocking code inside `async def` FastAPI endpoints | Blocks event loop; use `run_in_executor` or `def` endpoint |

---

## PART 7: PHASE 0 START COMMAND

Your very first action when starting this project is:

1. Read all five reference documents in full
2. Create the directory structure from plan.md Section 14
3. Build `backend/preprocessing/extractors/pdf_extractor.py`
4. Build `backend/preprocessing/parsers/act_parser.py` (section-boundary-aware)
5. Build the PostgreSQL `law_transition_mappings` table migration
6. Build the `StatuteNormalizationTool` with empty PostgreSQL backend (tool works, table is empty — you'll populate it via Gazette extraction)
7. Run the adversarial test cases from Phase 1D against the empty tool to confirm the tool interface is correct
8. Only then begin ingesting the first legal Act (start with BNS 2023)

**Do not write a single agent until Step 8 is complete.**

---

## PART 8: HOW TO HANDLE AMBIGUITY

When you encounter something not specified in this document or the reference documents, apply this decision hierarchy:

1. **Check CLAUDE.md first** — it is the canonical truth source
2. **Check plan.md** — for implementation details
3. **Apply the safety-first principle** — when in doubt, do the more conservative, more verifiable thing
4. **Flag for human review** — if the ambiguity touches legal accuracy, stop and ask
5. **Never assume** — especially about section numbers, act years, or which law governs what

The motto of this project is: **"A wrong answer is worse than no answer."** Build every decision into your code as if a real person's legal outcome depends on it. Because it does.

---

*This prompt was engineered for Claude Code agents working on the Neethi AI project.*
*Last updated: February 2026. Supersedes all previous CLAUDE.md versions.*
