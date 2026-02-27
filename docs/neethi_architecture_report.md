# Neethi Legal AI — Architectural Analysis & Structured Implementation Plan
### A Ground-Truth Investigation Report: Data Sources, Vector Storage, and Multi-Agent Design

> **Document Type:** Architectural Decision Record + Forward Implementation Plan  
> **Project:** Neethi — Indian Legal AI Assistant  
> **Stack:** CrewAI · FastAPI · PostgreSQL (Supabase) · Qdrant (Free Tier)  
> **Date:** February 2026  
> **Status:** Phases 1–5 complete. SC Judgments ingestion pipeline pending.

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Current System State — What Is Already Working](#2-current-system-state)
3. [The Data Source Investigation](#3-the-data-source-investigation)
4. [Ground-Truth Findings: What the Vanga Dataset Actually Contains](#4-ground-truth-findings)
5. [The URL Problem — Full Resolution](#5-the-url-problem)
6. [Architectural Decision Record](#6-architectural-decision-record)
7. [Qdrant Architecture — Four Collections, Storage Math](#7-qdrant-architecture)
8. [PostgreSQL (Supabase) Architecture](#8-postgresql-supabase-architecture)
9. [SC Judgments Ingestion Pipeline — Step-by-Step Plan](#9-sc-judgments-ingestion-pipeline)
10. [CrewAI Multi-Agent Architecture — Complete Design](#10-crewai-multi-agent-architecture)
11. [Persona-Aware Retrieval — How Each Crew Uses SC Judgments](#11-persona-aware-retrieval)
12. [Live Update Strategy](#12-live-update-strategy)
13. [Known Issues and Risk Register](#13-known-issues-and-risk-register)
14. [Implementation Sequence Going Forward](#14-implementation-sequence-going-forward)

---

## 1. Executive Summary

This report documents the complete architectural investigation conducted to determine the best approach for ingesting Indian Supreme Court (SC) judgments into the Neethi legal AI system. The investigation covered two candidate datasets (Kaggle and AWS S3 Vanga), involved ground-truth verification of actual JSON metadata from the Vanga source, empirical testing of reconstructed document URLs, and evaluation of the Indian Kanoon API as an enrichment mechanism.

The key findings, each established through direct evidence rather than assumption, are as follows.

The **Vanga AWS S3 dataset (2010–2025, English)** is the correct data source. It provides official-origin PDFs, clean structured Parquet metadata with `disposal_nature`, `case_no`, petitioner/respondent names, and year — fields that directly enable persona-based payload filtering in Qdrant. Its multilingual support aligns with Neethi's Sarvam AI translation roadmap.

The **eCourts/JUDIS legacy URL scheme** (`jonew/judis/*.pdf`) is empirically confirmed broken — a live test returned HTTP 503 Service Unavailable. These links belong to a deprecated system and are unsuitable for any agentic workflow.

**Indian Kanoon** is the correct target for live document enrichment. Its HTML is clean, its URL structure is stable (`/doc/{tid}/`), and its terms explicitly permit RAG use with attribution. The `tid` identifier is the correct primary key for URL construction. URL resolution should happen **at ingestion time**, not at query time, to avoid runtime rate-limiting failures.

Without the Indian Kanoon API (which is the current state), the plan proceeds with Vanga PDF text extraction, paragraph-aware chunking, BGE-M3 embedding, and Qdrant upsert — using a fourth collection `sc_judgments` that reuses the entire existing hybrid search infrastructure. The `ik_url` field is stored as an empty string and can be back-filled in a future enrichment pass without re-embedding anything.

The system currently has **3,814 Qdrant points indexed** (BNS/BNSS/BSA), all four crew pipelines smoke-tested and passing, and a working hybrid search pipeline. The SC judgments collection is the next major addition.

---

## 2. Current System State

Understanding what is already built is essential context for the forward plan. The table below reflects the state confirmed across smoke test runs 1–14.

| Component | Status | Notes |
|---|---|---|
| Phase 3 Qdrant hybrid search pipeline | ✅ Working | 3,814 points across BNS/BNSS/BSA |
| BGE-M3 dense + sparse embedding | ✅ Working | 1024-dim dense, BM25 sparse via FastEmbed |
| RRF fusion (k=60) | ✅ Working | Dense + sparse merged |
| Cross-encoder reranker (ms-marco-MiniLM) | ✅ Working | Applied to top-20 candidates |
| StatuteNormalizationTool | ✅ Working | IPC→BNS with collision warnings |
| CitationVerificationTool | ✅ Working | Qdrant primary + Supabase fallback |
| QueryClassifierTool | ✅ Working | Groq→Mistral fallback |
| QdrantHybridSearchTool | ✅ Working | Focused keyword queries |
| Layman Crew (full pipeline) | ✅ PASSED | Run 5 |
| Lawyer Crew (full pipeline) | ✅ PASSED | Run 14, 85.2s, BNS 101+103+105 verified |
| Advisor Crew (full pipeline) | ✅ PASSED | Run 10, 78.9s, Mistral fallback |
| Police Crew (full pipeline) | ✅ PASSED | Run 12, 25.9s, BNS 304+309 verified |
| FastAPI REST API endpoints | ⏳ Not implemented | |
| Frontend (Next.js) | ⏳ Not started | |
| Sarvam AI translation | ⏳ Not integrated | |
| Document drafting crew | ⏳ Not implemented | |
| **SC Judgments collection** | ⏳ **Not started** | **Scope of this plan** |

---

## 3. The Data Source Investigation

### 3.1 The Two Candidates

Two datasets were evaluated for ingesting SC judgments.

**Option A — Kaggle (26K PDFs, 1950–2024)** offers pre-mapped Indian Kanoon URLs in its CSV metadata — its primary advantage. It covers approximately 98% of SC judgments on Indian Kanoon. However, it is a raw PDF dataset requiring full OCR and LLM-based structural extraction for metadata. Its data integrity is uneven, with empty PDFs and inconsistent identifiers. Crucially, it is a static snapshot with no update mechanism.

**Option B — AWS S3 Vanga (~35K Judgments, 1950–2025)** provides clean, structured Parquet and JSON metadata files alongside the PDFs. It has a CC BY 4.0 open license, includes regional Indian language judgments, and is downloadable year-by-year without requiring AWS authentication. The dataset is organized by year in tar archives, making selective ingestion of recent years straightforward.

### 3.2 Initial Assessment and the URL Problem

The primary argument in Kaggle's favour was its pre-mapped Indian Kanoon URLs. The primary argument in Vanga's favour was its structured metadata. Both Gemini analyses reviewed during this investigation correctly identified `disposal_nature` as a particularly valuable Vanga field for persona-based filtering.

However, one Gemini recommendation — to use Vanga metadata alone in Qdrant (without embedding PDF text) and fetch live document content from Indian Kanoon at query time — was identified as architecturally incorrect. Storing only metadata strings in Qdrant without the actual judgment text means the semantic search degrades to fuzzy metadata matching. The ratio decidendi, the legal analysis, the arguments considered — none of these would be embedded. A query like "precedent for anticipatory bail in domestic violence cases" would not reliably surface the right judgments because the similarity is between the query and the judgment's legal reasoning, not its case title. Qdrant's purpose is semantic retrieval of text content, not metadata filtering alone.

---

## 4. Ground-Truth Findings: What the Vanga Dataset Actually Contains

Rather than relying on documentation, the actual JSON records from the Vanga repository were examined. This revealed several discrepancies between what was described and what the data contains in practice.

### 4.1 The Actual JSON Record Structure

A real record from the Vanga dataset looks like this:

```json
{
  "slno": 1,
  "diary_no": "10169-2001",
  "Judgement_type": "J",
  "case_no": "C.A. No.-004292-004292 - 2002",
  "pet": "NATIONAL INSURANCE CO. LTD., CHANDIGARH",
  "res": "NICOLLETTA ROHTAGI",
  "pet_adv": "M. K. DUA",
  "res_adv": "SURYA KANT",
  "bench": "",
  "judgement_by": "",
  "judgment_dates": "17-02-1902",
  "temp_link": "jonew/judis/18613.pdf (English)"
}
```

### 4.2 Field-by-Field Reality Check

**`diary_no`** — The eCourts internal filing number. This is the best candidate for a deterministic UUID key. Format inconsistencies exist across years but it is workable.

**`case_no`** — The formal case number (e.g., `C.A.` = Civil Appeal, `Crl.A.` = Criminal Appeal, `W.P.` = Writ Petition, `S.L.P.` = Special Leave Petition). Useful for display. This is **not** an AIR or SCC citation.

**`pet` / `res`** — Petitioner and respondent names. Present, usable, and confirmed in the data.

**`bench` / `judgement_by`** — Both are **empty strings** in the actual data. Bench composition and the authoring judge are absent for a substantial portion of the corpus, particularly pre-2010. Claims that these fields are reliably populated are contradicted by the raw data.

**`judgment_dates`** — Contains a known **century-encoding bug** for records in approximately the 1994–2003 window. eCourts' legacy two-digit year storage caused wrap-around — a case filed in 2001 may show a judgment date of 1901. A correction pass (add 100 years where `judgment_dates < 1950 AND year > 1993`) is mandatory during ingestion.

**`temp_link`** — An internal eCourts path fragment, e.g., `"jonew/judis/18613.pdf (English)"`. This is the critical field. It is **not a public URL**.

**`disposal_nature`** — Present in the Parquet files. Confirmed as genuinely useful for persona-based filtering (e.g., Police crew filtering by "Bail Granted" or "Conviction").

### 4.3 The Parquet Schema (Athena DDL Equivalent)

The structured Parquet metadata accessible via AWS Athena exposes: `diary_no`, `title` (petitioner v. respondent case name), `judge` (frequently empty), `pdf_link` (internal path), `decision_date` (subject to century bug), `disposal_nature`, and `year` (partition key). No AIR/SCC citation field exists in this dataset.

---

## 5. The URL Problem — Full Resolution

### 5.1 The Reconstructed URL Formula

The dataset author documented a formula for reconstructing the eCourts URL from `temp_link`:

```
https://main.sci.gov.in/ + temp_link (with language string stripped)
```

For the example record: `temp_link = "jonew/judis/18613.pdf (English)"` → cleaned to `"jonew/judis/18613.pdf"` → URL becomes `https://main.sci.gov.in/jonew/judis/18613.pdf`.

### 5.2 Empirical Test Result

This URL was tested live. The response was:

> **HTTP 503 — The requested service is temporarily unavailable. It is either overloaded or under maintenance.**

This is not a transient failure. The `jonew/judis/` path belongs to **JUDIS — the Judgment Information System**, which is the Supreme Court's legacy database architecture from the early 2000s. The Supreme Court has since migrated to a newer Judgment Search Portal, leaving these legacy links in a permanently degraded state — frequently taken offline for maintenance, heavily rate-limited, and hostile to automated requests.

**Conclusion: The eCourts/JUDIS URL scheme cannot be used in any production pipeline, agentic or otherwise.**

### 5.3 The Correct URL Target: Indian Kanoon

Indian Kanoon uses a stable, clean URL format: `https://indiankanoon.org/doc/{tid}/` where `tid` is an internal integer assigned sequentially when their crawler indexes a document. There is no mathematical formula to derive a `tid` from a `diary_no` or `case_no` — they are completely decoupled systems.

The correct approach is a **one-time ingestion-time enrichment pass** using either the Indian Kanoon Search API or a DuckDuckGo `site:indiankanoon.org` query. For each judgment, you search using `title + year`, retrieve the first `/doc/{tid}/` result, and store `ik_url = https://indiankanoon.org/doc/{tid}/` as a static Qdrant payload field.

This enrichment must happen **at ingestion time**, not at query time. Running DuckDuckGo queries inside live agent sessions creates a runtime rate-limiting failure mode: with 10 concurrent users each triggering 3 judgment retrievals, you generate 30 near-parallel DuckDuckGo queries within seconds, exceeding the unofficial API's ~20–30 requests/minute limit. The agents silently receive `"Search failed due to error: Ratelimit"`, the LegalReasoner gets a payload with no URL, and citation verification has nothing to verify against.

Since the Indian Kanoon API is not currently available, `ik_url` is stored as an empty string during the current ingestion phase. Because all Qdrant point IDs are deterministic UUIDs derived from `diary_no`, a future enrichment pass can upsert only the `ik_url` field into existing points without re-embedding or re-processing any text.

---

## 6. Architectural Decision Record

The following decisions are finalized and the rationale is documented for future reference.

| Decision | Choice | Rationale |
|---|---|---|
| Primary judgment dataset | Vanga AWS S3 (2010–2025) | Official-origin PDFs, clean Parquet metadata, CC BY 4.0, year-by-year download, `disposal_nature` field |
| Year range for initial ingestion | 2010–2025, reverse chronological | Post-2010 judgments are born-digital, metadata is reliable, covers all recent BNS/BNSS jurisprudence |
| Vector database for judgments | Qdrant (new `sc_judgments` collection) | Reuses existing BGE-M3, RRF, and reranker infrastructure. No pgvector rewrite needed |
| eCourts JUDIS URLs | Rejected — empirically confirmed broken | HTTP 503 on live test. Permanently deprecated infrastructure |
| URL enrichment strategy | Indian Kanoon, ingestion-time, one-time pass | Avoids runtime failures; deterministic; back-fillable without re-embedding |
| Chunking strategy | Paragraph-aware, 400–500 tokens, 50-token overlap | Preserves semantic coherence of judicial reasoning blocks |
| Quantization | Scalar INT8 (4× compression) + OnDisk vectors | Keeps ~300MB total for sc_judgments within 4GB Qdrant free tier |
| Century-bug date correction | Mandatory preprocessing step | Records with `decision_date < 1950` and `year > 1993` corrected by +100 years |

---

## 7. Qdrant Architecture

### 7.1 Four Collections — Roles and Responsibilities

```
Qdrant Collections (Free Tier — 4GB Disk / 1GB RAM)
│
├── legal_sections          [EXISTS — 1,066 points]
│   Purpose: Full section text, one point per BNS/BNSS/BSA section
│   Used by: CitationVerificationTool (exact lookup), RetrievalSpecialist
│
├── legal_sub_sections      [EXISTS — 1,308 points]
│   Purpose: Sub-section clauses, one point per sub-clause
│   Used by: Deep statutory retrieval
│
├── law_transition_context  [EXISTS — 1,440 points]
│   Purpose: IPC→BNS, CrPC→BNSS, IEA→BSA transition mappings
│   Used by: StatuteNormalizationTool
│
└── sc_judgments            [NEW — target ~200,000 points]
    Purpose: Supreme Court judgment chunks, 2010–2025
    Used by: LawyerCrew, AdvisorCrew (precedent retrieval)
              LaymanCrew, PoliceCrew (top-1 supporting reference)
```

### 7.2 `sc_judgments` Collection Configuration

```python
client.create_collection(
    collection_name="sc_judgments",
    vectors_config={
        "dense": models.VectorParams(
            size=1024,
            distance=models.Distance.COSINE,
            on_disk=True,           # Protect 1GB RAM limit
        ),
    },
    sparse_vectors_config={
        "sparse": models.SparseVectorParams(
            modifier=models.Modifier.IDF,
        )
    },
    quantization_config=models.ScalarQuantization(
        scalar=models.ScalarQuantizationConfig(
            type=models.ScalarType.INT8,   # float32 → int8 = 4× compression
            quantile=0.99,
            always_ram=True,               # Quantized index in RAM for speed
        )
    ),
    hnsw_config=models.HnswConfigDiff(
        m=8,                               # Default is 16; m=8 saves ~40% disk
        ef_construct=100,                  # Lower than default 200; adequate for legal retrieval
        on_disk=True,                      # HNSW graph on disk, not RAM
    ),
)
```

### 7.3 `sc_judgments` Payload Schema

Every Qdrant point in `sc_judgments` carries the following payload:

```json
{
  "text": "<paragraph chunk text — the embedded content>",
  "chunk_index": 3,
  "total_chunks": 11,
  "section_type": "analysis",
  "case_name": "National Insurance Co. Ltd. v. Nicolletta Rohtagi",
  "case_no": "C.A. No.-004292-004292 - 2002",
  "diary_no": "10169-2001",
  "disposal_nature": "Dismissed",
  "year": 2002,
  "decision_date": "2002-02-17",
  "legal_domain": "civil",
  "ik_url": "",
  "language": "en"
}
```

The `section_type` heuristic assigns `"background"` to the first 2 chunks, `"analysis"` to middle chunks, and `"conclusion"` to the final 1–2 chunks. This approximation enables persona-based filtering without LLM structural classification.

### 7.4 Payload Indexes (Mandatory for O(1) Filtering)

Without payload indexes, every filter scan is O(n) across all 200,000 points. These indexes must be created before ingestion begins:

```python
for field, schema in [
    ("disposal_nature", models.PayloadSchemaType.KEYWORD),
    ("year",            models.PayloadSchemaType.INTEGER),
    ("section_type",    models.PayloadSchemaType.KEYWORD),
    ("legal_domain",    models.PayloadSchemaType.KEYWORD),
    ("language",        models.PayloadSchemaType.KEYWORD),
]:
    client.create_payload_index("sc_judgments", field, schema)
```

### 7.5 Storage Budget

| Collection | Points | Dense (INT8) | Sparse | Payload + HNSW | Total |
|---|---|---|---|---|---|
| legal_sections | 1,066 | ~1 MB | ~1 MB | ~5 MB | ~7 MB |
| legal_sub_sections | 1,308 | ~1.5 MB | ~1.5 MB | ~6 MB | ~9 MB |
| law_transition_context | 1,440 | ~1.5 MB | ~1.5 MB | ~6 MB | ~9 MB |
| sc_judgments | ~200,000 | ~200 MB | ~100 MB | ~200 MB | **~500 MB** |
| **Total** | | | | | **~525 MB** |

This leaves **~3.5 GB of headroom** within the 4GB disk limit for future High Court collections, document templates, or expansion to the full 35K dataset.

---

## 8. PostgreSQL (Supabase) Architecture

### 8.1 Existing Schema (Complete — Do Not Modify)

The Supabase database already contains 8 core tables that form the structural foundation of the system. These are stable and production-validated.

| Table | Purpose | Key Columns |
|---|---|---|
| `acts` | The 6 core Indian legal acts | `act_code`, `name`, `status`, `era`, `effective_date` |
| `chapters` | Chapter groupings within each act | `act_code`, `chapter_number`, `chapter_title` |
| `sections` | Individual sections with legal text | `section_number` (VARCHAR 20), `legal_text`, `is_offence`, `is_cognizable`, `is_bailable` |
| `sub_sections` | Numbered sub-clauses | `parent_section_number`, `sub_section_label`, `legal_text` |
| `law_transition_mappings` | IPC→BNS, CrPC→BNSS, IEA→BSA | `old_act`, `old_section`, `new_act`, `new_section`, `transition_type`, `is_active` |
| `cross_references` | Internal cross-references | `from_section`, `to_section`, `reference_type` |
| `extraction_audit` | Audit trail for every section processed | `section_id`, `confidence_score`, `source` |
| `human_review_queue` | Low-confidence sections flagged for review | `section_id`, `flagged_reason` |

All primary keys use UUID via `gen_random_uuid()`. The `punishment_max_years` sentinel for life imprisonment is `99999` (INTEGER, not string). The `law_transition_mappings.is_active` flag defaults FALSE and must be explicitly set TRUE — all 1,440 current mappings are active.

### 8.2 New Table Required: `ingested_judgments`

This table serves as the audit trail and deduplication registry for the SC judgments ingestion pipeline. Before processing any judgment, the pipeline checks this table. This prevents re-downloading PDFs, enables incremental updates, and logs URL enrichment status.

```sql
CREATE TABLE ingested_judgments (
    id              UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    diary_no        VARCHAR(50) NOT NULL,
    case_no         VARCHAR(200),
    case_name       TEXT,
    year            INTEGER NOT NULL,
    decision_date   DATE,
    disposal_nature VARCHAR(100),
    legal_domain    VARCHAR(50),
    qdrant_point_ids UUID[] NOT NULL DEFAULT '{}',  -- All chunk UUIDs for this judgment
    chunk_count     INTEGER DEFAULT 0,
    ik_url          TEXT DEFAULT '',                -- Empty until IK enrichment pass
    ik_tid          INTEGER,                        -- Indian Kanoon internal doc ID
    ik_resolved_at  TIMESTAMPTZ,                   -- NULL = not yet resolved
    ingested_at     TIMESTAMPTZ DEFAULT NOW(),
    pdf_hash        VARCHAR(64),                    -- SHA-256 of PDF for change detection
    ocr_required    BOOLEAN DEFAULT FALSE,
    UNIQUE(diary_no)                                -- Deduplication key
);

CREATE INDEX idx_ingested_year ON ingested_judgments(year);
CREATE INDEX idx_ingested_disposal ON ingested_judgments(disposal_nature);
CREATE INDEX idx_ingested_ik_resolved ON ingested_judgments(ik_resolved_at)
    WHERE ik_resolved_at IS NULL;  -- Partial index — efficiently finds un-enriched records
```

The `qdrant_point_ids` array stores all chunk UUIDs for a judgment, enabling targeted deletion or re-indexing if the source PDF changes. The partial index on `ik_resolved_at IS NULL` makes future enrichment passes efficient — they can query "give me all records that have no IK URL yet" in O(log n).

### 8.3 Connection Note

Supabase free-tier uses IPv6-only for direct connections. The **Session Pooler** must always be used:

```
Host: aws-1-ap-south-1.pooler.supabase.com
Port: 5432
Username: postgres.{PROJECT_REF}
```

---

## 9. SC Judgments Ingestion Pipeline — Step-by-Step Plan

The pipeline is a stream processor, not a batch processor. You process one year at a time, persist results to Qdrant and Supabase, then delete the raw PDFs before moving to the next year. You never need more than one year of raw data on disk simultaneously.

### Phase A — Data Acquisition (AWS S3, Year-by-Year)

Process in **reverse chronological order** — 2025 first, then 2024, working backwards. This ensures the most recent and legally relevant judgments are available earliest.

For each year `YYYY`, download two artifacts: the Parquet metadata file from `s3://indian-supreme-court-judgments/metadata/parquet/year={YYYY}/metadata.parquet` and the English PDF tarball from `s3://indian-supreme-court-judgments/data/tar/year={YYYY}/english/english.tar`. No AWS account is required for the open data registry. The AWS CLI command `aws s3 cp s3://... . --no-sign-request` handles this without authentication.

Extract the tar to a working directory, then process all PDFs within it before moving to the next year. The Parquet file for each year is typically 1–5 MB; the English tar for a recent year averages 2–4 GB.

### Phase B — Metadata Preprocessing (Parquet → Supabase Staging)

Load the Parquet using Pandas or Polars. For each row, apply the century-bug date correction: if the extracted year from `judgment_dates` is before 1950 but the `year` partition key is after 1993, add 100 years to the date. Infer `legal_domain` from `case_no` prefix: `C.A.` → `civil`, `Crl.A.` → `criminal`, `W.P.` → `constitutional`, `T.P.` → `civil`, `S.L.P.` → variable (infer from petition type).

Insert each row into `ingested_judgments`. If `diary_no` already exists (duplicate from a previous run), skip it — the `UNIQUE(diary_no)` constraint handles this idempotently.

### Phase C — PDF Text Extraction

For each PDF, first attempt PyMuPDF text extraction (`fitz.open()`). If the extracted text is less than 200 characters for a document with more than 2 pages, flag `ocr_required = TRUE` and fall back to the Tesseract OCR path. In the 2010–2025 range, OCR should be required for fewer than 5% of documents — most are born-digital. After extraction, apply standard cleaning: strip page headers/footers (matching patterns like `\d+\n` at page boundaries), remove the Supreme Court of India letterhead boilerplate that appears on every first page, and normalize Unicode characters.

### Phase D — Paragraph-Aware Chunking

Split the cleaned text on double-newline (`\n\n`) boundaries. Merge consecutive short paragraphs (under 100 tokens) with their following paragraph until the chunk reaches 400 tokens. If a single paragraph exceeds 500 tokens, split at the nearest sentence boundary before the 500-token mark with a 50-token overlap to the next chunk. Assign `section_type` heuristically: `"background"` for chunk indices 0–1, `"analysis"` for indices 2 through `total-2`, and `"conclusion"` for the final 1–2 chunks. This produces an average of 8–12 chunks per judgment.

### Phase E — Embedding and Qdrant Upsert

Generate the deterministic point UUID for each chunk using `uuid5(NAMESPACE_URL, f"{diary_no}__chunk{idx}")`. This means re-running the ingestion for any year is fully idempotent — existing points are overwritten with identical data, no duplicates accumulate.

Run BGE-M3 encoding in batches of 32 on a Lightning AI GPU session for the bulk ingestion run. For incremental daily updates (5–20 new judgments per day), CPU inference is acceptable. Upsert to the `sc_judgments` collection with the full payload schema described in Section 7.3.

After upsert, update `ingested_judgments` in Supabase with `chunk_count`, `qdrant_point_ids`, and `ingested_at`.

### Phase F — Future IK URL Enrichment (When API Available)

When Indian Kanoon API access is obtained, run a targeted enrichment pass over all `ingested_judgments` rows where `ik_resolved_at IS NULL`. For each, call `api.indiankanoon.org/search/?formInput={case_name} {year}`, extract `tid` from the JSON response, construct `ik_url = https://indiankanoon.org/doc/{tid}/`, and upsert only the `ik_url` field into the existing Qdrant points using their stored `qdrant_point_ids`. Update `ingested_judgments` with `ik_tid`, `ik_url`, and `ik_resolved_at = NOW()`.

This entire enrichment pass requires no re-embedding — it is purely a payload update operation.

---

## 10. CrewAI Multi-Agent Architecture — Complete Design

### 10.1 Agent Roster

The system has five active agents, each with a fixed LLM assignment and fallback chain.

**Agent 1 — Query Analyst**
Uses Groq Llama 3.3 70B (`get_fast_llm()`) with Mistral Small fallback. Tools: `QueryClassifierTool`, `StatuteNormalizationTool`. `max_iter = 3`. This is the first agent in every pipeline. It classifies the query by legal domain, intent, and entities. It detects old statute references (IPC, CrPC, IEA) and triggers normalization before retrieval. Its output includes `Suggested Act Filter`, `Suggested Era Filter`, `Complexity`, and a new field `requires_precedents` (boolean) that determines whether the RetrievalSpecialist should query `sc_judgments`.

**Agent 2 — Retrieval Specialist**
Uses Groq Llama 3.3 70B (`get_light_llm()`, 512 max_tokens) with Mistral Small fallback. Tools: `QdrantHybridSearchTool`, `StatuteNormalizationTool`. `max_iter = 5`. This agent executes hybrid search. When `requires_precedents = True`, it makes two sequential tool calls: first targeting `legal_sections` for statutory text, then targeting `sc_judgments` for precedents. It concatenates both result sets in its Final Answer for the downstream LegalReasoner.

**Agent 3 — Legal Reasoner**
Uses Groq Llama 3.3 70B (`get_reasoning_llm()`) with Mistral Large fallback. Tools: `IRACAnalyzerTool`. Active only in LawyerCrew and AdvisorCrew. Receives the merged statutory + precedent retrieval output and performs IRAC analysis. The IRACAnalyzerTool prompt must explicitly instruct the model to map retrieved SC judgments to the IRAC structure: identifying which precedents support each element of the Issue, Rule, and Analysis.

**Agent 4 — Citation Checker**
Uses Groq Llama 3.3 70B with Mistral Small fallback. Tools: `CitationVerificationTool`. Mandatory in every crew pipeline — this is non-negotiable. Verifies every section citation and case citation before delivery. For SC judgment citations, verification checks that the `diary_no` exists in `ingested_judgments` in Supabase (the Qdrant-equivalent of `legal_sections` for judgments). Unverified citations are removed silently; the confidence score is reduced.

**Agent 5 — Response Formatter**
Uses Mistral Small (`get_formatting_llm()`). No tools. Applies persona-specific formatting to the verified LegalReasoner output. The formatting rules are absolute and must not be altered by the LLM.

### 10.2 Five Crew Configurations

All crews use `Process.sequential`. No concurrent agent execution.

**LaymanCrew:**
```
QueryAnalyst → RetrievalSpecialist → CitationChecker → ResponseFormatter
```
`top_k = 3`. Output: plain language (8th-grade reading level), numbered steps, "What this means for you", "What to do next." SC judgment output: top-1 result case name and outcome only, formatted as "Courts have previously ruled: [case name] — [disposal_nature]."

**LawyerCrew:**
```
QueryAnalyst → RetrievalSpecialist → LegalReasoner → CitationChecker → ResponseFormatter
```
`top_k = 5`. Output: full IRAC structure, technical legal language, section references with full text, precedent citations with case name, diary number, year, and disposal outcome.

**AdvisorCrew:**
```
QueryAnalyst → RetrievalSpecialist → LegalReasoner → CitationChecker → ResponseFormatter
```
`top_k = 5`. Output: compliance focus, risk assessment format. SC judgment output filtered to `disposal_nature IN ("Dismissed", "Allowed")` and `year >= 2015` to surface only recent authoritative precedents.

**PoliceCrew:**
```
QueryAnalyst → RetrievalSpecialist → CitationChecker → ResponseFormatter
```
`top_k = 3`. Output: procedural guidance, cognizability/bailability, FIR and arrest procedure. SC judgment output filtered to `disposal_nature IN ("Bail Granted", "Bail Refused", "Conviction Upheld", "Acquittal")` for outcome-focused precedent citations.

**DocumentDraftingCrew:**
```
QueryAnalyst → DocumentDrafter → CitationChecker
```
Does not use `sc_judgments`. The document drafter uses Jinja2 templates for structural fields and an LLM call for `legal_sections.facts_in_legal_language` and `prayer_clause` only.

### 10.3 The `QdrantHybridSearchTool` Routing Extension

The existing tool requires one new parameter to support dual-collection retrieval without architectural changes to the crews themselves:

```python
# New parameter added to QdrantHybridSearchTool
collection: str = "legal_sections"   # Default unchanged — all existing tests still pass

# RetrievalSpecialist task description updated to:
# "If `requires_precedents` is True in the QueryAnalyst output:
#  1. Call QdrantHybridSearchTool with collection='legal_sections' and act_filter/era_filter
#  2. Call QdrantHybridSearchTool with collection='sc_judgments' and appropriate payload filters
#  Return BOTH result sets in your Final Answer, clearly labelled STATUTORY and PRECEDENT."
```

This change is backward-compatible. All existing smoke tests pass unchanged because they do not set `requires_precedents = True`. The new behavior activates only when the QueryAnalyst classifies the query as requiring precedent analysis.

### 10.4 Critical Safety Rules (Non-Negotiable)

These rules have been validated through 14 smoke test runs and must not be bypassed:

The most dangerous mapping error in the entire system is **IPC 302 ≠ BNS 302**. IPC 302 is Murder, which maps to BNS 103. BNS 302 is Religious Offences — a completely different category. The `StatuteNormalizationTool` collision warning for this pair must remain active at all times.

The `CitationVerificationTool` must run before delivery in every crew. If a citation cannot be verified, it is removed — never delivered with a disclaimer. An unverified legal citation is more dangerous than no citation.

The `StatuteNormalizationTool` must run before every Qdrant query. A user saying "Section 420" means IPC 420 (cheating), which maps to BNS 318(4). Without normalization, the retrieval targets the wrong act entirely.

The `NO_RELEVANT_DOCUMENTS_FOUND` guard must only fire when the tool response explicitly reports zero results. Agents must never self-judge result relevance — that is the LegalReasoner's job. This rule applies uniformly across all four crews after the Bug #9 regression fix.

---

## 11. Persona-Aware Retrieval — How Each Crew Uses SC Judgments

The `section_type` and `disposal_nature` payload fields enable persona-specific Qdrant filtering without separate collections. The following table shows the exact filter applied per persona.

| Persona | `section_type` Filter | `disposal_nature` Filter | `year` Filter | Output Format |
|---|---|---|---|---|
| Layman | `["conclusion"]` | Any | Any | Case name + 1-line outcome |
| Lawyer | `["analysis", "conclusion"]` | Any | Any | Full IRAC precedent block |
| Advisor | `["analysis", "conclusion"]` | `["Dismissed", "Allowed"]` | `>= 2015` | Risk-contextualized precedent |
| Police | `["conclusion"]` | `["Bail Granted", "Bail Refused", "Conviction Upheld", "Acquittal"]` | Any | Outcome + applicable BNS section |

The `section_type` filter for Lawyer and Advisor targets `"analysis"` and `"conclusion"` chunks — the ratio decidendi and the final order. This ensures the LegalReasoner receives legally substantive content rather than background narrative. The cross-encoder reranker then further prioritizes the most relevant chunks within these filtered results.

---

## 12. Live Update Strategy

New SC judgments are published daily on the Supreme Court's website and indexed by Indian Kanoon within 24–48 hours. The nightly update pipeline works as follows.

A scheduled task (GitHub Actions cron or a local cron job) polls the Indian Kanoon RSS feed at `https://indiankanoon.org/feeds/latest/` each night for new Supreme Court entries. For each new entry, it extracts the case metadata (title, year, diary number if available), downloads the corresponding Vanga-equivalent PDF from the SC website if accessible, or defers to the next day's Vanga tar archive when the new year's data becomes available.

Because all Qdrant point IDs are derived via `uuid5(NAMESPACE_URL, f"{diary_no}__chunk{idx}")`, running the ingestion pipeline for a judgment that is already indexed simply overwrites the existing points with identical data. There is no deduplication logic needed. The `ingested_judgments` table's `UNIQUE(diary_no)` constraint handles the Supabase side.

The nightly update volume is small — typically 5–20 new judgments per day. BGE-M3 inference on CPU is adequate for this volume and requires no Lightning AI GPU session.

---

## 13. Known Issues and Risk Register

### Active Bugs (Pre-existing, Not Introduced by SC Judgments Integration)

**Bug #8 — CitationChecker verifies only first citation.** The CitationChecker agent stops after one successful verification instead of iterating over all retrieved sections. Impact: medium — subsequent citations in multi-section responses may be unverified. Fix required before production deployment.

**Bug #18 — ResponseFormatter adds unverified citations from training knowledge.** The Mistral Small ResponseFormatter occasionally injects section citations that were never retrieved or verified by CitationChecker. The `CitationChecker` no-renumbering rule has been confirmed working for Run 10+, but the formatter's tendency to hallucinate additional sections has not been fully eliminated. Mitigation: explicit "ONLY cite sections present in the CitationChecker output" instruction in the ResponseFormatter task description.

### New Risks Introduced by SC Judgments Integration

**Risk: OCR quality variance.** Even within 2010–2025, a small percentage of PDFs may be scanned images. If PyMuPDF extracts fewer than 200 characters for a multi-page document, the fallback must engage Tesseract. Failure to detect this case results in embedding empty or garbage text, which pollutes semantic search results.

**Risk: `disposal_nature` inconsistency.** The Vanga dataset's `disposal_nature` field is scraped from eCourts display strings, which are not standardized. Values like "Dismissed", "Dismissed As Withdrawn", "Dismissed in Default", and "Dismissed (Merits)" all carry different legal meanings. A normalization mapping should be applied during ingestion to collapse these into canonical categories.

**Risk: Century-bug date correction edge cases.** The correction `year += 100 where year < 1950 and partition_year > 1993` may not cover all cases. Some records in the 2004–2010 range may have been incorrectly stored with pre-century dates in the original eCourts system. Date-based filtering results should be treated as approximate for any record before 2010.

---

## 14. Implementation Sequence Going Forward

The following sequence is ordered by dependency — each step must complete before the next begins. Steps are sized for execution under time constraints, with the most impactful deliverables front-loaded.

**Step 1 — Create `ingested_judgments` table in Supabase.** This is a prerequisite for all subsequent steps. It takes 15 minutes to write and run the migration.

**Step 2 — Create `sc_judgments` collection in Qdrant with quantization and payload indexes.** Run the collection creation script and verify the collection appears in the Qdrant dashboard. 30 minutes including verification.

**Step 3 — Download 2020–2025 Parquet metadata files from Vanga AWS S3.** This is the lightest download (~30 MB total). Use it to validate the Parquet schema matches expectations and to populate `ingested_judgments` with metadata for the target year range before any PDFs are processed.

**Step 4 — Download and process 2024–2025 English tarballs.** Start with the most recent two years (~4–8 GB). Run the full pipeline: extract PDFs → PyMuPDF text extraction → paragraph chunking → BGE-M3 embedding (Lightning AI GPU session) → Qdrant upsert. Verify a sample retrieval query returns judgment chunks before proceeding to older years.

**Step 5 — Extend `QdrantHybridSearchTool` with `collection` parameter.** One-line change. Run existing smoke tests to confirm all four crews still pass with the default `collection='legal_sections'` behavior.

**Step 6 — Update RetrievalSpecialist task descriptions** for Lawyer and Advisor crews to include the dual-collection retrieval instruction when `requires_precedents = True`.

**Step 7 — Run end-to-end smoke tests** with a lawyer query that requires precedent analysis. Confirm the LegalReasoner receives both statutory and precedent chunks and that the CitationChecker successfully validates the judgment citation against `ingested_judgments`.

**Step 8 — Process 2018–2023 in batches**, continuing in reverse chronological order. This brings the corpus to approximately 15,000–20,000 judgments — sufficient for a complete and convincing demonstration.

**Step 9 (Future) — Indian Kanoon enrichment pass** when API access is obtained. Populate `ik_url` in all existing Qdrant points and `ingested_judgments` records. This step requires no re-embedding and can run as an overnight batch job.

---

## Appendix A — Storage Responsibility Matrix

A clear rule for what lives where, for every class of data in the system:

| Data Class | Storage | Reason |
|---|---|---|
| Law transition mappings (IPC→BNS) | PostgreSQL (Supabase) | Deterministic fact, exact lookup, never semantic |
| Section metadata (act, number, chapter) | PostgreSQL + Qdrant payload | Structured filtering at retrieval time |
| Full statutory text (BNS/BNSS/BSA) | Qdrant `legal_sections` | Semantic retrieval required |
| Judgment chunk text (SC 2010–2025) | Qdrant `sc_judgments` | Semantic retrieval required |
| Judgment metadata (diary_no, disposal, URL) | Supabase `ingested_judgments` + Qdrant payload | Audit trail in Supabase, filtering in Qdrant |
| User data, sessions, document drafts | PostgreSQL (Supabase) | Relational, transactional, PII-sensitive |
| Document templates | Qdrant `document_templates` | Semantic matching to user need |

---

## Appendix B — Empirically Confirmed Facts (Do Not Re-investigate)

These facts were established through direct testing or ground-truth source examination during this investigation. They should not be re-opened without new evidence.

`https://main.sci.gov.in/jonew/judis/18613.pdf` returns **HTTP 503**. The JUDIS system is deprecated and unreliable. Do not use eCourts URLs in any pipeline component.

The Vanga `bench` and `judgement_by` fields are **empty strings** in real data for the majority of records, particularly pre-2010. Do not build features that depend on these fields being populated.

The Vanga dataset contains **no AIR or SCC citation field**. Any claim that a standard legal citation is available in the Vanga metadata is incorrect. The `case_no` field contains eCourts internal case numbers (e.g., `C.A. No.-004292-004292 - 2002`), not published reporter citations.

The `diary_no` field combined with `case_no` is the correct basis for a deterministic UUID key, not `citation`.

Indian Kanoon `tid` values have **no mathematical relationship** to eCourts `diary_no` values. The only reliable resolution path is via the Indian Kanoon search API or a DuckDuckGo `site:indiankanoon.org` query.

---

*End of Report — Neethi Legal AI Architectural Analysis v1.0*  
*Generated from architectural investigation session, February 2026*
