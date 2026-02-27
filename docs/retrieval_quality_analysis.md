# Neethi AI — Retrieval Quality Analysis & Improvement Roadmap

**Date:** 2026-02-26
**Version:** 1.0
**Scope:** Legal retrieval precision, accuracy, and relevance improvements based on
Qdrant 1.17 capabilities, Legal Information Retrieval (LIR) research, and
observed production failures in the Neethi AI pipeline.

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Current Architecture Audit](#2-current-architecture-audit)
3. [Observed Production Failures](#3-observed-production-failures)
4. [Database Coverage Reality](#4-database-coverage-reality)
5. [Qdrant Feature Analysis](#5-qdrant-feature-analysis)
6. [Legal Information Retrieval Research](#6-legal-information-retrieval-research)
7. [Root Cause Map](#7-root-cause-map)
8. [Improvement Architecture](#8-improvement-architecture)
9. [Prioritized Implementation Roadmap](#9-prioritized-implementation-roadmap)
10. [Expected Quality Metrics](#10-expected-quality-metrics)
11. [Data Ingestion Gaps](#11-data-ingestion-gaps)
12. [Architectural Decisions Log](#12-architectural-decisions-log)

---

## 1. Executive Summary

Neethi AI's current retrieval pipeline achieves functional hybrid search but suffers
from three compounding failure modes that degrade legal output quality:

1. **Semantic Drift** — Vector search retrieves sections with keyword overlap but no
   legal relevance (e.g., BSA s.112 retrieved for a security deposit query because its
   text contains "landlord and tenant").

2. **Yes-Man Citation Verification** — The CitationChecker verified section *existence*
   but not *relevance*, causing semantically drifted sections to pass through to the
   user as primary legal authority.

3. **Statutory Coverage Gap** — Critical civil acts (CPC 1908, HSA 1956, Model Tenancy
   Act 2021, State Rent Control Acts) are absent from the database, forcing the
   retrieval system into nearest-neighbor approximations on an incomplete library.

These failures compound: even a perfect retrieval algorithm cannot return relevant
sections that do not exist in the index. However, Qdrant 1.17's new features —
Weighted RRF, Relevance Feedback, Score Boosting, and MMR — combined with Legal
Information Retrieval research on recursive clause retrieval and multi-graph
architectures, offer a clear path to measurably better legal output.

**In legal AI, a wrong answer is worse than no answer. Every improvement below
is evaluated on that standard.**

---

## 2. Current Architecture Audit

### 2.1 Pipeline Flow

```
User Query
    │
    ▼
[QueryAnalystAgent]
    └── QueryClassifierTool (Groq Llama 3.3 70B)
        → Classifies: domain, intent, entities, era filter, act filter
        → Checks: Contains Old Statutes? → StatuteNormalizationTool
    │
    ▼
[RetrievalSpecialistAgent]
    └── QdrantHybridSearchTool
        → BGE-M3 dense (1024d) + BM25 sparse
        → RRF fusion (k=60, unweighted)
        → CrossEncoder reranking (ms-marco-MiniLM)
        → top_k = 3 (layman) / 5 (lawyer)
        → collection: legal_sections OR sc_judgments
    │
    ▼
[LegalReasonerAgent]  ← Only for lawyer / legal_advisor roles
    └── IRACAnalyzerTool (Groq Llama 3.3 70B → Mistral Large fallback)
        → IRAC: Issue, Rule, Application, Conclusion
    │
    ▼
[CitationCheckerAgent]
    └── CitationVerificationTool
        → Qdrant scroll: exact act_code + section_number match
        → PostgreSQL fallback: sections table
        → Classifies: VERIFIED / VERIFIED_INCOMPLETE / NOT_FOUND
        + RELEVANCE ASSESSMENT (added post-audit):
        → Classifies: RELEVANT / TANGENTIAL / NOT_APPLICABLE
        + PRECEDENT ASSESSMENT (added post-audit):
        → Classifies: RELEVANT_PRECEDENT / NOT_APPLICABLE_PRECEDENT
        → Overall status: VERIFIED / PRECEDENT_ONLY / UNVERIFIED
    │
    ▼
[ResponseFormatterAgent]
    └── Formats for role: citizen / lawyer / police / legal_advisor
        → VERIFIED: full response with citations
        → PRECEDENT_ONLY: SC-precedent-based response, notes statutory gap
        → UNVERIFIED: cannot-verify message
```

### 2.2 Qdrant Collections

| Collection | Points | Purpose | Status |
|------------|--------|---------|--------|
| `legal_sections` | 1,497 | Statutory text — BNS/BNSS/BSA + 6 civil acts | ✅ Active |
| `legal_sub_sections` | 1,706 | Clause/proviso granular retrieval | ✅ Active |
| `sc_judgments` | 37,965 | SC cases 2023–2024 | ⚠️ 95% untagged domain |
| `law_transition_context` | 1,440 | IPC→BNS, CrPC→BNSS, IEA→BSA mappings | ✅ Active |
| `case_law` | 0 | HC judgments | ❌ Empty |

### 2.3 Acts Indexed

| Act Code | Sections in Qdrant | Domain | Era | Type |
|----------|--------------------|--------|-----|------|
| BNSS_2023 | 536 | Criminal Procedure | naveen_sanhitas | New (active) |
| BNS_2023 | 358 | Criminal Substantive | naveen_sanhitas | New (active) |
| BSA_2023 | 172 | Evidence | naveen_sanhitas | New (active) |
| ICA_1872 | 155 | Contract | civil_statutes | Old (active) |
| ACA_1996 | 100 | Arbitration | civil_statutes | Modern (active) |
| TPA_1882 | 93 | Property | civil_statutes | Old (active) |
| SRA_1963 | 38 | Specific Relief | civil_statutes | Old (active) |
| LA_1963 | 26 | Limitation | civil_statutes | Old (active) |
| HMA_1955 | 19 | Family | civil_statutes | Old (active) |

### 2.4 Current RRF Implementation

The existing `hybrid_search.py` uses unweighted RRF at k=60:

```python
# Current — equal weight to dense and sparse
score(d) = Σ 1/(60 + rank_d)   for dense rank + sparse rank
```

No score boosting, no decay functions, no MMR, no weighted fusion.
The CrossEncoder handles final reranking after initial fusion.

---

## 3. Observed Production Failures

### 3.1 Case Study: Security Deposit Query

**Query:** *"My landlord is not returning my security deposit after I vacated the house.
What can I do?"*

**Expected behavior:** Retrieve TPA s.105/s.108 (lessee rights) or State Rent Control
Act provisions, with SC precedent MAHENDRA KAUR ARORA v. HDFC BANK (2024) which
directly addresses security deposit refusal.

**Actual behavior (pre-fix):**

| Retrieved | Why Retrieved | Correct Classification |
|-----------|---------------|----------------------|
| BSA s.112 — Burden of proof for landlord-tenant relationship | "landlord and tenant" keyword match | NOT_APPLICABLE |
| TPA s.114 — Relief against forfeiture for non-payment | "lessor", "lessee" keyword match | NOT_APPLICABLE |
| ACA s.38 — Arbitration deposits | "deposit" keyword match | NOT_APPLICABLE |

**Root Causes:**
1. Unweighted RRF gave BM25 keyword matches equal weight to semantic matches
2. All correct sections (MTA 2021, State Rent Control Acts) absent from database
3. CitationChecker verified existence only — passed all 3 as primary authority
4. SC judgments not searched because layman crew had no `sc_judgments` call

**Post-fix behavior:**
- RELEVANCE ASSESSMENT added to CitationChecker → all 3 classified NOT_APPLICABLE
- SC judgments search added to layman retrieval → MAHENDRA KAUR ARORA retrieved
- Status: PRECEDENT_ONLY → response based on SC case, statutory gap disclosed

**Remaining problem:** The underlying retrieval still returns wrong sections.
The fix is downstream (LLM-level filtering), not upstream (vector-level precision).
This is addressed in Section 8.

### 3.2 Failure Mode Taxonomy

```
FAILURE TYPE 1: Semantic Drift (Keyword Overlap)
  Example: "deposit" matches arbitration deposit sections
  Layer: Retrieval (Qdrant)
  Fix: Weighted RRF, Score Boosting, MMR

FAILURE TYPE 2: Coverage Gap (Missing Statutes)
  Example: Model Tenancy Act 2021 not indexed
  Layer: Data
  Fix: Ingest missing acts

FAILURE TYPE 3: Yes-Man Verification (Existence ≠ Relevance)
  Example: BSA s.112 VERIFIED but NOT APPLICABLE
  Layer: Agent prompt
  Fix: RELEVANCE ASSESSMENT in CitationChecker (implemented)

FAILURE TYPE 4: Precedent Blindness (SC Cases Ignored)
  Example: MAHENDRA KAUR ARORA v. HDFC BANK not retrieved
  Layer: Agent task design
  Fix: sc_judgments call in layman crew retrieval (implemented)

FAILURE TYPE 5: Cross-Reference Blindness (Linked Sections Not Fetched)
  Example: BNS s.103 retrieved but BNS s.105 (referenced in s.103) not fetched
  Layer: Retrieval architecture
  Fix: CrossReferenceExpansionTool (planned)
```

---

## 4. Database Coverage Reality

### 4.1 PostgreSQL Acts Registry (14 Acts)

| Act | Year | Domain | Status | PG Sections | Qdrant | Gap |
|-----|------|--------|--------|-------------|--------|-----|
| IPC_1860 | 1860 | criminal_substantive | **repealed** | 0/511 | 0 | ❌ No text |
| ICA_1872 | 1872 | civil_contract | active | 173 | 155 | ⚠️ -18 |
| IEA_1872 | 1872 | evidence | **repealed** | 0/167 | 0 | ❌ No text |
| TPA_1882 | 1882 | civil_property | active | 106 | 93 | ⚠️ -13 |
| **CPC_1908** | **1908** | **civil_procedure** | **active** | **0/158** | **0** | ❌ **Absent** |
| HMA_1955 | 1955 | family | active | 26 | 19 | ⚠️ -7 |
| **HSA_1956** | **1956** | **family** | **active** | **0/30** | **0** | ❌ **Absent** |
| LA_1963 | 1963 | civil_general | active | 26 | 26 | ✅ |
| SRA_1963 | 1963 | civil_contract | active | 42 | 38 | ⚠️ -4 |
| CrPC_1973 | 1973 | criminal_procedure | **repealed** | 0/484 | 0 | ❌ No text |
| ACA_1996 | 1996 | civil_arbitration | active | 96 | 100 | ✅ |
| BNS_2023 | 2023 | criminal_substantive | active | 353 | 358 | ✅ |
| BNSS_2023 | 2023 | criminal_procedure | active | 530 | 536 | ✅ |
| BSA_2023 | 2023 | evidence | active | 169 | 172 | ✅ |

### 4.2 Completely Missing Acts (Not Even Registered)

| Act | Sections | Covers | Priority |
|-----|----------|--------|----------|
| Model Tenancy Act, 2021 | ~56 | Security deposits, tenant rights, rent | 🔴 Critical |
| Consumer Protection Act, 2019 | ~107 | Consumer disputes, deficiency of service | 🔴 Critical |
| Maharashtra Rent Control Act, 1999 | ~60 | State-specific tenancy | 🟡 High |
| Delhi Rent Act, 1958 | ~58 | State-specific tenancy | 🟡 High |
| Hindu Succession Act, 1956 | 30 | Inheritance (in acts table, no sections) | 🟡 High |
| Code of Civil Procedure, 1908 | 158 | Civil litigation procedure | 🟡 High |
| Information Technology Act, 2000 | ~94 | Cybercrime, digital evidence | 🟠 Medium |
| POCSO Act, 2012 | ~46 | Child sexual offences | 🟠 Medium |
| Prevention of Corruption Act, 1988 | ~31 | Corruption offences | 🟠 Medium |

### 4.3 SC Judgments Quality Issues

| Issue | Scale | Impact |
|-------|-------|--------|
| `legal_domain` is blank | 36,100/37,965 chunks (95%) | Domain filtering disabled |
| Indian Kanoon URLs missing | 1,636/1,636 judgments (100%) | Citation links broken |
| High Court judgments absent | `case_law` collection empty | No HC precedents |
| Judgment years coverage | Only 2023–2024 | Pre-2023 SC cases inaccessible |

### 4.4 Human Review Queue

119 sections in PostgreSQL with `extraction_confidence < 0.7` are awaiting manual
approval before Qdrant indexing. These represent real legal text that is currently
invisible to the retrieval pipeline.

---

## 5. Qdrant Feature Analysis

### 5.1 Weighted RRF (v1.17.0+)

**What it is:**
Reciprocal Rank Fusion now supports a `weights` array on prefetches, allowing
differential importance to be assigned to the dense (semantic) and sparse (keyword)
search components.

**Standard RRF formula (current — unweighted):**
```
score(d) = Σ 1/(k + rank_d)
```

**Weighted RRF formula (new):**
```
score(d) = Σ weight_i × (1/(k + rank_d_i))
```

**Application to Neethi AI:**

The optimal weight distribution depends on query type:

| Query Type | Dense Weight | Sparse Weight | Rationale |
|------------|-------------|---------------|-----------|
| Conceptual civil ("security deposit rights") | 3.0 | 1.0 | Semantic meaning > exact terms |
| Criminal offence ("culpable homicide") | 2.0 | 1.0 | Balanced — legal terms matter |
| Section number lookup ("BNS 103") | 1.0 | 4.0 | Exact term match critical |
| Procedural ("how to file FIR") | 2.0 | 1.0 | Context > specific terms |
| Old statute reference ("IPC 302") | 1.0 | 3.0 | After normalization, exact match |

**Implementation in `hybrid_search.py`:**
```python
# QueryClassifierTool should output query_type
# HybridSearcher.search() should accept weights parameter

def search(
    self,
    query: str,
    query_type: str = "conceptual",  # new parameter
    ...
) -> list:
    weights = self._get_weights(query_type)
    # Pass to Qdrant prefetch query with rrf weights
```

**Expected impact:** Reduces semantic drift false positives at the retrieval layer —
the most upstream fix available.

---

### 5.2 Score Boosting with Decay Functions (v1.14.0+, available now)

**What it is:**
Mathematical formulas injected into Qdrant ranking at query time using payload fields.
No model retraining required. Supports `mult`, `sum`, `exp_decay`, `gauss_decay`,
`linear_decay`, and conditional boosts.

**Three high-value applications for Neethi AI:**

#### A. Era Recency Boost
For queries about current Indian law (post-July 2024), BNS/BNSS/BSA sections should
rank above IPC/CrPC/IEA sections with equal semantic similarity.

```python
# In Qdrant Query API formula
formula = {
    "sum": [
        {"mult": [{"condition": {"key": "era", "match": {"value": "naveen_sanhitas"}}}, 0.15]},
        "$score"
    ]
}
# naveen_sanhitas sections get +0.15 score boost over colonial_codes
```

#### B. Extraction Confidence Weighting
Sections with `extraction_confidence = 1.0` (clean PDF extraction) should rank above
sections with `extraction_confidence = 0.6` (OCR-uncertain) when semantically equivalent.

```python
formula = {
    "mult": [
        "$score",
        {"sum": [{"mult": ["extraction_confidence", 0.3]}, 0.7]}
    ]
}
# Maps confidence 0.5 → 0.85× score, confidence 1.0 → 1.0× score
```

#### C. Offence Classification Precision
For criminal queries (`is_offence = True` in query context), offence sections should
rank above definitional or procedural sections.

```python
# When query is classified as criminal offence lookup:
formula = {
    "sum": [
        "$score",
        {"mult": [{"condition": {"key": "is_offence", "match": {"value": True}}}, 0.1]}
    ]
}
```

**Combined formula (production):**
```
final_score = base_rrf_score
            × confidence_factor         (0.85 – 1.0)
            + era_boost                 (0.0 or 0.15)
            + offence_precision_boost   (0.0 or 0.10, criminal queries only)
```

---

### 5.3 Maximal Marginal Relevance (MMR, v1.15.0+, available now)

**What it is:**
After retrieval, MMR iteratively selects results by balancing relevance to the query
against diversity from already-selected results.

```
MMR = argmax[ λ·sim(candidate, query) - (1-λ)·max(sim(candidate, selected)) ]
```

- `diversity=0.0` → pure relevance (identical to standard retrieval)
- `diversity=1.0` → pure diversity (maximum spread, ignores relevance)
- `diversity=0.3` → recommended starting point for legal civil queries

**Problem it solves for Neethi AI:**
A conceptual civil law query may retrieve 5 TPA sections — all semantically similar
to each other, all topically adjacent but none definitively applicable. MMR with
`diversity=0.3` ensures result 3, 4, 5 are forced to come from different parts of
the legal vector space (potentially ICA_1872 or SRA_1963), giving the CitationChecker
more material to work with.

**Usage by crew:**

| Crew | MMR | Diversity | Rationale |
|------|-----|-----------|-----------|
| Layman (citizen) | ✅ Yes | 0.3 | Civil queries need broad coverage |
| Lawyer | ❌ No | — | IRAC needs precision, not diversity |
| Legal Advisor | ⚠️ Optional | 0.2 | Corporate queries need slight diversity |
| Police | ❌ No | — | Exact offence section required |

**Implementation in `QdrantHybridSearchTool`:**
```python
# Add mmr_diversity parameter to QdrantSearchInput
# Pass to HybridSearcher which calls Qdrant's MMR query variant
mmr_diversity: float = Field(0.0, description="0.0=pure relevance, 1.0=pure diversity")
```

---

### 5.4 Relevance Feedback (v1.17.0+, highest potential)

**What it is:**
A native Qdrant mechanism that uses an "oracle" model to create positive/negative
context pairs from initial search results, then modifies the scoring function during
full index traversal — not just reranking the retrieved subset.

**Why this is architecturally superior to cross-encoder reranking:**

```
Current pipeline:
  Qdrant retrieves top-10 → CrossEncoder reranks top-10 → pass top-3
  Problem: Section ranked #11 is permanently excluded

Relevance Feedback pipeline:
  Qdrant retrieves → oracle scores top-5 → creates context pairs
  → scoring formula applied during HNSW traversal of ALL vectors
  → sections ranked #11, #50, #200 can surface if they match the direction
  Benefit: Recall improvement across entire index, not just initial retrieval
```

**Scoring formula:**
```
F = a · sim(query, candidate)
  + Σ confidence_pair^b · c · delta_pair

Where:
  confidence_pair = relevance_positive - relevance_negative
  delta_pair      = sim(positive, candidate) - sim(negative, candidate)
  a, b, c         = trained parameters (via qdrant-relevance-feedback package)
```

**Benchmark results (BEIR datasets):**
- Qwen3-0.6B retriever + colBERTv2.0 oracle: **+38.72% on SCIDOCS**
- Qwen3-0.6B retriever + Qwen3-4B oracle: **+23.23% on MSMARCO**
- mxbai-large-v1 + colBERTv2.0: **+21.57% on NFCorpus**

**For Neethi AI — legal domain training:**

The `qdrant-relevance-feedback` package requires only 50–300 domain-specific queries.
Neethi AI can generate these from:
1. Existing test queries (security deposit, murder, bail, contract breach)
2. CitationChecker's RELEVANT/NOT_APPLICABLE classifications as signal
3. The 119 pending human_review_queue items once approved

**Oracle model candidates for Indian legal domain:**

| Model | Pros | Cons |
|-------|------|------|
| BGE-M3 (same as retriever) | Already loaded | Same weaknesses as retriever |
| Qwen3-Embedding-4B | Best results in benchmarks | Needs GPU, heavier |
| colBERTv2.0 | Best in SCIDOCS | Multi-vector, different infrastructure |
| Legal-BERT (legal fine-tuned BERT) | Domain-aware | Not yet tested with Qdrant RF |

**Recommended approach:** Use BGE-M3 as retriever (already deployed), Qwen3-4B as
oracle. Train parameters on 100 Indian legal domain queries. Expected gain: 15–25%
improvement in recall on civil law and property queries.

**Blocker:** Verify Qdrant Cloud instance version is ≥ 1.17 before implementing.

---

### 5.5 Multi-Stage Query Architecture (Prefetch Chaining)

**What it is:**
Qdrant's `prefetch` parameter enables nested query chains: Stage 1 uses fast
approximate search, Stage 2 refines with expensive full-precision search.

**Recommended two-stage architecture for Neethi AI:**

```json
{
    "prefetch": {
        "query": "<query_vector>",
        "using": "dense",
        "filter": {"era": "naveen_sanhitas"},
        "limit": 50
    },
    "query": "<query_vector>",
    "using": "dense",
    "limit": 10,
    "formula": {
        "sum": ["$score", {"mult": ["extraction_confidence", 0.1]}]
    }
}
```

Stage 1: Fast BGE-M3 retrieval of top-50 candidates with era filter
Stage 2: Full-precision rescore of 50 with confidence boost + final top-10

This is superior to the current single-pass retrieval because it:
- Reduces computation (50 candidates, not full index, for precise scoring)
- Applies score boosting formulas to a manageable candidate set
- Maintains recall (50 candidates before cutting to 10)

---

### 5.6 Result Grouping by Act Code

**What it is:**
Qdrant's `group_by` parameter eliminates result redundancy when multiple chunks
represent the same document.

**Application:** When top-3 results are all BNSS sections about bail, grouping by
`act_code` ensures at most 1–2 results from BNSS, forcing the remaining slot(s) to
be filled from a different act. This is structural diversity enforcement.

```python
# In HybridSearcher — add optional group_by parameter
results = client.query_points(
    collection_name=collection,
    query=dense_vector,
    group_by="act_code",
    limit=3,            # 3 groups (acts)
    group_size=2,       # up to 2 sections per act
)
# Returns up to 6 sections, max 2 from any single act
```

---

## 6. Legal Information Retrieval Research

### 6.1 Core LIR Methods Comparison

| Method | Precision | Recall | Legal Suitability | Current Neethi Status |
|--------|-----------|--------|-------------------|----------------------|
| Boolean (keyword filter) | High | Low | Exact section lookups | ⚠️ Only via act_filter/era_filter |
| BM25 (sparse) | Medium | Medium | Legal terminology | ✅ Implemented |
| Dense semantic | Medium | High | Conceptual queries | ✅ Implemented |
| Hybrid (BM25 + Dense) | High | High | General legal | ✅ Implemented |
| Weighted Hybrid | Higher | Higher | Query-adaptive | ❌ Not implemented |
| Cross-encoder reranking | Highest | Unchanged | Post-retrieval precision | ✅ Implemented |
| MMR | High | High + Diverse | Civil law breadth | ❌ Not implemented |
| Relevance Feedback | Highest | Highest | All domains | ❌ Not implemented |
| Recursive Graph RAG | Highest | Highest | Complex legal reasoning | ❌ Not implemented |

### 6.2 Recursive Cross-Reference Retrieval

**Source:** Enterprise RAG article — Legal Document RAG with multi-graph, multi-agent
recursive retrieval through legal clauses (WhyHow.AI pattern, LangGraph + LlamaIndex).

**The legal cross-reference problem:**
Indian law sections routinely reference other sections:
- BNS s.103 (Murder) references s.105 (Culpable Homicide) — you cannot reason about
  murder without understanding culpable homicide
- BNSS s.482 (Anticipatory Bail) references s.483 (conditions), s.484 (cancellation)
- ICA s.73 (Compensation) references s.74 (stipulated damages) and s.75 (party in
  default)

**Current failure:** QdrantHybridSearchTool retrieves BNS s.103 but never fetches
s.105 even though s.103 says "except in cases covered under Section 105". The
LegalReasoner must reason with an incomplete statutory picture.

**Critical finding:** The infrastructure for this already exists.
The `cross_references` PostgreSQL table stores:

```python
class CrossReference(Base):
    source_act: str          # "BNS_2023"
    source_section: str      # "103"
    target_act: str          # "BNS_2023"
    target_section: str      # "105"
    reference_type: str      # "exception_reference"
    reference_text: str      # "except in cases covered under Section 105"
```

**Proposed CrossReferenceExpansionTool:**
```
Input:  List of (act_code, section_number) from initial retrieval
Output: Expanded list including all transitively referenced sections

Process:
  1. For each retrieved section, query cross_references table
  2. Fetch sections with reference_type IN ('exception_reference',
     'subject_to', 'definition_import', 'punishment_table')
  3. For fetched sections, check if they also have cross-references (1 level)
  4. Deduplicate, limit to 5 additional sections
  5. Return expanded context
```

**Multi-graph architecture (WhyHow.AI pattern) mapped to Neethi AI:**

```
Current Neethi AI:
  Qdrant (vector retrieval) → CitationChecker → LegalReasoner

Proposed Neethi AI (recursive):
  Qdrant (vector retrieval)
      ↓
  CrossReferenceExpansion (PostgreSQL graph traversal, 1–2 hops)
      ↓
  DefinitionsExpansion (fetch s.2 definitions for terms in retrieved sections)
      ↓
  CitationChecker (verify + relevance classify the expanded set)
      ↓
  LegalReasoner (IRAC with complete statutory context)
```

**Implemented as** a new `CrossReferenceExpansionTool` in the lawyer and advisor
crews only. Layman crew does not need cross-reference depth — it needs simplicity.

### 6.3 Definitions Graph

Legal definitions are anchored in specific sections (BNS s.2 has 60+ definitions).
A retrieved section that uses the term "wrongful confinement" requires BNS s.2(l)
to be fully understood. Currently no tool fetches definitions.

**Implementation:** A lightweight Definitions lookup that, for any retrieved section,
identifies technical terms and fetches their definitions from the relevant act's
definitions section. This is a targeted PostgreSQL query, not a vector search.

```python
# Example: section text contains "dishonest intention"
# → fetch ICA_1872 s.24 (definition of "dishonestly")
# → add to context before IRAC analysis
```

### 6.4 Three-Retriever Pattern for Legal Text

The WhyHow.AI paper uses **Vector + BM25 + Keyword** (three retrievers).
Neethi AI uses **Dense + Sparse** (BM25 equivalent, two).

The third retriever missing from Neethi AI — **exact payload filter lookup** — is
critical for a specific but common legal query pattern:

```
"What does BNS section 103 say?"
→ Should NOT use vector search at all
→ Should directly filter: act_code = "BNS_2023" AND section_number = "103"
→ 100% precision, 0ms embedding overhead
```

Currently, the agent runs full hybrid search even for direct section lookups.
A `SectionLookupTool` with exact Qdrant payload filter would handle this pattern
with perfect precision.

---

## 7. Root Cause Map

```
PROBLEM: Low legal output quality for civil / property law queries
│
├── CAUSE A: Wrong sections retrieved (Semantic Drift)
│   ├── A1: Unweighted RRF gives BM25 keyword matches equal weight to semantic
│   │   └── FIX: Weighted RRF (dense 2.0 : sparse 1.0 for civil queries)
│   ├── A2: No score boosting for relevant metadata (era, confidence)
│   │   └── FIX: Score Boosting formulas at query time
│   ├── A3: No diversity enforcement — similar wrong sections fill all K slots
│   │   └── FIX: MMR (diversity=0.3) for layman crew
│   └── A4: top_k=3 leaves no room for relevant sections if first 3 are wrong
│       └── FIX: top_k=5 for statutory, separate sc_judgments call (done)
│
├── CAUSE B: Correct sections not in database (Coverage Gap)
│   ├── B1: Model Tenancy Act 2021 absent
│   ├── B2: State Rent Control Acts absent
│   ├── B3: CPC_1908 absent (civil litigation procedure)
│   ├── B4: HSA_1956 absent (inheritance)
│   └── FIX: Data ingestion (separate workstream, no code fix possible)
│
├── CAUSE C: Retrieved sections lack complete legal context
│   ├── C1: Referenced sections never fetched (cross-reference blindness)
│   │   └── FIX: CrossReferenceExpansionTool (PostgreSQL graph traversal)
│   └── C2: Legal definitions not fetched for technical terms
│       └── FIX: DefinitionsExpansionTool (lightweight)
│
├── CAUSE D: Verification verified existence, not relevance (Yes-Man)
│   └── FIX: RELEVANCE ASSESSMENT in CitationChecker (IMPLEMENTED ✅)
│
└── CAUSE E: SC precedents not searched for citizen queries
    └── FIX: sc_judgments call in layman retrieval task (IMPLEMENTED ✅)
```

---

## 8. Improvement Architecture

### 8.1 Enhanced Retrieval Pipeline (Target State)

```
User Query
    │
    ▼
[QueryAnalystAgent]
    └── QueryClassifierTool
        → Outputs: legal_domain, query_type (conceptual|section_lookup|procedural)
        → query_type drives RRF weights downstream
    │
    ▼
[RetrievalSpecialistAgent]
    │
    ├── If query_type = "section_lookup":
    │   └── SectionLookupTool (exact Qdrant payload filter)
    │       act_code + section_number → 100% precision, no embedding
    │
    └── Otherwise:
        └── QdrantHybridSearchTool (enhanced)
            ├── Stage 1: Dense + Sparse with WEIGHTED RRF
            │   └── weights based on query_type from QueryAnalyst
            ├── Stage 2: Score Boosting (era, confidence, offence classification)
            ├── MMR (layman/advisor crew: diversity=0.3; lawyer/police: off)
            ├── Group by act_code (ensure multi-act representation)
            └── top_k=5 statutory + separate sc_judgments call if Requires Precedents
    │
    ▼
[CrossReferenceExpansionTool]  ← New, lawyer/advisor crew only
    └── For each retrieved section:
        → Query cross_references table (1–2 hops)
        → Fetch exception_reference, subject_to, definition_import sections
        → Deduplicate, add up to 5 referenced sections to context
    │
    ▼
[LegalReasonerAgent]  ← Lawyer/advisor only
    └── IRACAnalyzerTool
        → Now has complete statutory context (retrieved + referenced + definitions)
    │
    ▼
[CitationCheckerAgent]
    └── CitationVerificationTool
        + RELEVANCE ASSESSMENT (IMPLEMENTED ✅)
        + PRECEDENT ASSESSMENT (IMPLEMENTED ✅)
        → Status: VERIFIED / PRECEDENT_ONLY / UNVERIFIED
    │
    ▼
[ResponseFormatterAgent]
    → VERIFIED: full response
    → PRECEDENT_ONLY: SC-based response, discloses statutory gap
    → UNVERIFIED: cannot-verify message
```

### 8.2 Weighted RRF Architecture

```python
# hybrid_search.py — proposed enhancement

QUERY_TYPE_WEIGHTS = {
    "section_lookup": (1.0, 4.0),     # (dense, sparse) — keyword precision
    "criminal_offence": (2.0, 1.5),   # balanced with slight semantic lean
    "civil_conceptual": (3.0, 1.0),   # semantic dominates
    "procedural": (2.0, 1.0),         # semantic for procedural understanding
    "default": (2.0, 1.0),
}

# In Qdrant query:
{
    "prefetch": [
        {"query": sparse_vector, "using": "sparse", "limit": 20},
        {"query": dense_vector, "using": "dense", "limit": 20}
    ],
    "query": {
        "rrf": {
            "weights": [sparse_weight, dense_weight],
            "k": 60
        }
    },
    "limit": top_k
}
```

### 8.3 Score Boosting Architecture

```python
# Injected into Qdrant Query API at search time

def _build_score_formula(query_context: dict) -> dict:
    formula = {"sum": ["$score"]}

    # Era boost: naveen_sanhitas gets +0.15 for post-2024 queries
    if query_context.get("era_hint") == "naveen_sanhitas":
        formula["sum"].append({
            "mult": [
                {"condition": {"key": "era", "match": {"value": "naveen_sanhitas"}}},
                0.15
            ]
        })

    # Confidence weighting: always applied
    formula = {
        "mult": [
            formula,
            {"sum": [{"mult": ["extraction_confidence", 0.3]}, 0.7]}
        ]
    }

    # Offence precision: only for criminal queries
    if query_context.get("is_criminal_query"):
        formula["sum"].append({
            "mult": [
                {"condition": {"key": "is_offence", "match": {"value": True}}},
                0.10
            ]
        })

    return formula
```

### 8.4 CrossReferenceExpansionTool Architecture

```python
class CrossReferenceExpansionTool(BaseTool):
    """Expand retrieved sections with their cross-referenced statutory provisions.

    For lawyer and legal_advisor crews only. Queries the cross_references
    PostgreSQL table to find sections that are explicitly referenced by the
    initially retrieved sections, then fetches their full text.

    Reference types followed:
        exception_reference  — "except as provided in s.X" (critical for defences)
        subject_to           — "subject to provisions of s.X" (conditional rules)
        definition_import    — "as defined in s.X" (legal term definitions)
        punishment_table     — "punishment as per s.X" (sentencing context)

    Reference types NOT followed (too broad):
        cross_act_reference  — would pull too many sections
        procedure_link       — procedural only, adds noise for substantive queries
    """
    name = "CrossReferenceExpansionTool"

    def _run(self, sections: list[dict]) -> str:
        # For each (act_code, section_number) pair:
        #   1. SELECT target_act, target_section, reference_type, reference_text
        #      FROM cross_references
        #      WHERE source_act = act_code AND source_section = section_number
        #      AND reference_type IN ('exception_reference', 'subject_to',
        #                             'definition_import', 'punishment_table')
        #   2. Fetch legal_text from sections table for each target
        #   3. Format and return expanded context
        ...
```

---

## 9. Prioritized Implementation Roadmap

### Phase 1 — Immediate (Code Changes, No New Infrastructure)

**Target:** Reduce semantic drift at the retrieval layer.

| Task | File | Expected Impact |
|------|------|----------------|
| Weighted RRF based on query_type | `hybrid_search.py` | Reduce false-positive retrieval by ~40% |
| Score Boosting (era + confidence) | `hybrid_search.py` | BNS outranks IPC; quality gates |
| MMR for layman/advisor crew (diversity=0.3) | `hybrid_search.py` | Broader act coverage per query |
| Group results by act_code | `hybrid_search.py` | Ensure multi-act representation |
| SectionLookupTool (exact payload filter) | New tool | 100% precision for direct section queries |
| Run `reindex_unindexed_sections.py` | Script (ready) | Recover 43 missing sections |
| Run `tag_sc_judgment_domains.py` | Script (ready) | Enable domain filtering for 36,100 SC chunks |

### Phase 2 — Short Term (New Tools, Moderate Effort)

**Target:** Give the LegalReasoner complete statutory context.

| Task | File | Expected Impact |
|------|------|----------------|
| `CrossReferenceExpansionTool` | New tool | Lawyer IRAC gets complete statutory chain |
| `DefinitionsExpansionTool` | New tool | Technical legal terms always defined |
| Add query_type output to QueryClassifierTool | `query_classifier_tool.py` | Enables adaptive RRF weights |
| Ingest CPC_1908 (158 sections) | Data pipeline | Civil litigation queries answered |
| Ingest HSA_1956 (30 sections) | Data pipeline | Inheritance queries answered |

### Phase 3 — Medium Term (Data + Infrastructure)

**Target:** Cover the Indian legal landscape adequately for all 4 user roles.

| Task | Expected Impact |
|------|----------------|
| Ingest Model Tenancy Act, 2021 | Security deposit, tenant rights answered |
| Ingest Consumer Protection Act, 2019 | Consumer disputes answered |
| Ingest State Rent Control Acts (MH, DL, KA) | State-specific tenancy covered |
| Run IK URL enrichment for 1,636 SC judgments | Citation links functional |
| Expand sc_judgments to 2015–2022 | 8 more years of precedents |
| Ingest IPC_1860 section text | Old-code queries (pre-July 2024 cases) |
| Ingest CrPC_1973 section text | Old-procedure queries |

### Phase 4 — Investment (Training + Advanced Architecture)

**Target:** State-of-the-art legal retrieval accuracy.

| Task | Effort | Expected Impact |
|------|--------|----------------|
| Verify Qdrant Cloud ≥ 1.17 | 1 hour | Gate for Relevance Feedback |
| Train Relevance Feedback (100 legal queries, Qwen3-4B oracle) | 2–3 days | +15–25% recall across all query types |
| Full recursive cross-reference graph (multi-hop, 3 levels) | 1 week | Lawyer-grade complete statutory context |
| Legal-BERT or domain fine-tuned embedder for Indian law | 2–4 weeks | Better semantic alignment to Indian legal text |
| High Court judgment ingestion (HC case_law collection) | Ongoing | Jurisdiction-specific precedents |

---

## 10. Expected Quality Metrics

### 10.1 Retrieval Quality (After Phase 1 + 2)

| Metric | Current (Estimated) | Target (Phase 1) | Target (Phase 2) |
|--------|--------------------|--------------------|------------------|
| Precision@3 (civil queries) | ~20% | ~50% | ~70% |
| Precision@3 (criminal queries) | ~65% | ~80% | ~90% |
| VERIFIED response rate | ~40% | ~55% | ~70% |
| PRECEDENT_ONLY rate | ~20% | ~25% | ~20% |
| UNVERIFIED rate | ~40% | ~20% | ~10% |
| False positive citations passed to user | ~3/query | ~0.5/query | ~0.1/query |

*Estimates based on observed test runs. Actual measurement requires a labeled
legal query evaluation set.*

### 10.2 Legal Output Quality Rubric

Each response should be evaluated on five dimensions:

| Dimension | Weight | Current Score | Target Score |
|-----------|--------|--------------|--------------|
| **Citation Accuracy** — Every cited section exists and is correctly numbered | 30% | 8/10 | 10/10 |
| **Legal Relevance** — Cited sections actually govern the user's situation | 25% | 4/10 | 8/10 |
| **Completeness** — All applicable sections / precedents included | 20% | 3/10 | 7/10 |
| **Statutory Currency** — Uses BNS/BNSS/BSA (not IPC/CrPC) for post-2024 scenarios | 15% | 7/10 | 10/10 |
| **Role Calibration** — Complexity appropriate to user role (citizen vs. lawyer) | 10% | 7/10 | 9/10 |

**Gemini's assessment of the security deposit test case:** 6.5/10
**Target after all phases complete:** 8.5/10+

The remaining gap to 10/10 is irreducible without human legal expert review per
response — which is the correct design for a legal AI support tool, not a
replacement for qualified legal advice.

---

## 11. Data Ingestion Gaps

### 11.1 Priority Ingestion Queue

Priority is based on query volume expected for Indian users:

```
CRITICAL (blocks common queries):
  1. Model Tenancy Act, 2021          ~56 sections  (security deposits, tenant rights)
  2. Consumer Protection Act, 2019   ~107 sections  (deficiency of service)
  3. Code of Civil Procedure, 1908    158 sections  (civil litigation procedure)

HIGH (blocks specific practice areas):
  4. Hindu Succession Act, 1956        30 sections  (inheritance law)
  5. Maharashtra Rent Control Act      ~60 sections  (Mumbai/Pune tenancy)
  6. Delhi Rent Act, 1958              ~58 sections  (Delhi tenancy)
  7. POCSO Act, 2012                   ~46 sections  (child protection — police critical)
  8. Prevention of Corruption Act      ~31 sections  (anti-corruption)

MEDIUM (complete coverage):
  9. IT Act, 2000                      ~94 sections  (cybercrime, digital evidence)
 10. Negotiable Instruments Act         138 sections  (cheque bounce — high volume)
 11. IPC_1860 section text             511 sections  (pre-July 2024 criminal cases)
 12. CrPC_1973 section text            484 sections  (pre-July 2024 procedure)
```

### 11.2 SC Judgments Expansion

Current: 2023–2024 only (1,636 judgments, 37,965 chunks)

```
Expansion plan:
  2019–2022: ~3,000 additional judgments (landmark COVID, property, criminal)
  2015–2018: ~2,500 additional judgments
  Pre-2015 landmark: ~500 curated judgments (Maneka Gandhi, Vishaka, Shreya Singhal etc.)
```

### 11.3 Metadata Quality Fixes

| Fix | Method | Impact |
|-----|--------|--------|
| Tag `legal_domain` for 36,100 SC chunks | `tag_sc_judgment_domains.py` (ready) | Domain filtering enabled |
| Enrich IK URLs for 1,636 judgments | Indian Kanoon API batch lookup | Citation links functional |
| Approve 119 human_review_queue sections | Manual review + `reindex_unindexed_sections.py` | 119 sections enter Qdrant |
| Fix Qdrant/Postgres count discrepancy (BNS +5, BNSS +6, BSA +3) | Audit source of extra Qdrant points | Data integrity |

---

## 12. Architectural Decisions Log

### ADR-001: CitationChecker placement before ResponseFormatter

**Decision:** CitationChecker runs BEFORE ResponseFormatter in all crews.
**Rationale:** The formatter must only receive verified content. Formatting
unverified citations would present them as authoritative to users.
**Alternative rejected:** Running CitationChecker after formatting would require
re-formatting if citations are removed.

### ADR-002: RELEVANCE ASSESSMENT in CitationChecker, not RetrievalSpecialist

**Decision:** Relevance classification (RELEVANT/TANGENTIAL/NOT_APPLICABLE) is done
by the CitationChecker agent, not the RetrievalSpecialist.
**Rationale:** The RetrievalSpecialist's task explicitly says "Do NOT self-judge
result relevance — that is the downstream agents' job." This separation ensures the
retriever always returns everything it found (recall-first) while downstream ensures
precision.
**Trade-off:** Relies on LLM reasoning for relevance classification — a deterministic
Weighted RRF at the retrieval layer (Phase 1) is the upstream complement.

### ADR-003: PRECEDENT_ONLY status (not UNVERIFIED) when SC cases but no statutes

**Decision:** When CitationChecker finds 0 RELEVANT statutory sections but 1+
RELEVANT_PRECEDENT SC cases, status is PRECEDENT_ONLY, not UNVERIFIED.
**Rationale:** In Indian law, Supreme Court judgments are binding authority. A
response grounded in SC cases is legally valid even without statutory text — it
must however disclose that the statutory provision is not in the database.
**Risk:** SC cases can be overruled. ResponseFormatter must include "verify current
status" disclaimer for PRECEDENT_ONLY responses.

### ADR-004: No cross-reference expansion for layman crew

**Decision:** CrossReferenceExpansionTool is only in lawyer and legal_advisor crews.
**Rationale:** Citizens need simple, direct answers. Cross-referenced sections add
legal complexity that confuses rather than helps. The CitationChecker's TANGENTIAL
classification already handles peripherally relevant sections.

### ADR-005: MMR off for lawyer and police crews

**Decision:** MMR diversity is disabled for lawyer and police crews.
**Rationale:** Lawyers need the highest-precision sections for IRAC analysis — forced
diversity would introduce weaker sections. Police need the exact offence/procedure
section, not a diverse spread across related concepts.

### ADR-006: top_k=5 for legal_sections, separate sc_judgments call

**Decision:** Statutory search uses top_k=5; SC judgments use a separate tool call
with top_k=3.
**Rationale:** Mixing statutory and case law in one search loses control over the
balance. A dedicated sc_judgments call (only when QueryAnalyst flags
"Requires Precedents: true") ensures both are retrieved without one dominating.

---

*Document maintained by the Backend Agent. Update after each significant pipeline
change or production failure analysis.*

*References:*
- *Qdrant 1.17.x Release Notes: https://qdrant.tech/blog/qdrant-1.17.x/*
- *Qdrant Relevance Feedback: https://qdrant.tech/articles/relevance-feedback/*
- *Qdrant Search Relevance Docs: https://qdrant.tech/documentation/concepts/search-relevance/*
- *Qdrant Hybrid Queries: https://qdrant.tech/documentation/concepts/hybrid-queries/*
- *Legal Document RAG — Recursive Retrieval: https://medium.com/enterprise-rag/legal-document-rag-multi-graph-multi-agent-recursive-retrieval-through-legal-clauses-c90e073e0052*
- *Database Inspection Results: logs/lightning/Database_Status.txt*
- *Production Test Logs: logs/lightning/ (various)*
