# Embedding Model Comparison Study: Indian Legal Domain RAG System

**Date:** 2026-02-17
**System Context:** Agentic AI Legal System for India using Qdrant Vector Database
**Author:** AI/ML Engineering Team
**Status:** Research & Recommendation

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [System Context & Requirements](#2-system-context--requirements)
3. [Model Profiles](#3-model-profiles)
4. [Master Comparison Table](#4-master-comparison-table)
5. [Detailed Analysis by Criterion](#5-detailed-analysis-by-criterion)
6. [Answering the Six Strategic Questions](#6-answering-the-six-strategic-questions)
7. [GPU Cost Analysis for Lightning AI](#7-gpu-cost-analysis-for-lightning-ai)
8. [Hybrid Retrieval Strategy](#8-hybrid-retrieval-strategy)
9. [Tiered Architecture Design](#9-tiered-architecture-design)
10. [Final Verdict & Recommendations](#10-final-verdict--recommendations)
11. [Implementation Roadmap](#11-implementation-roadmap)
12. [Appendix: Benchmark Sources](#12-appendix-benchmark-sources)

---

## 1. Executive Summary

This study evaluates 12+ embedding models across 11 criteria for building an Indian Legal Domain RAG system. The evaluation accounts for the unique challenges of Indian legal text: extreme document lengths (judgments can exceed 50,000 words), mixed English-Hindi legal terminology, domain-specific vocabulary (sections, acts, precedents), and the diverse user base (lawyers, laypersons, police).

**Primary Recommendation:** **BGE-M3** as the primary embedding model, with **OpenAI text-embedding-3-large** as a low-ops fallback, and **BM25 via Qdrant's sparse vectors** for hybrid retrieval.

**Key Findings:**
- InLegalBERT is **not** a sentence embedding model out-of-the-box and requires significant fine-tuning effort; its 512-token limit is crippling for legal documents.
- BGE-M3 uniquely supports dense + sparse + ColBERT retrieval in a single model, with 8192 token context and 100+ language support.
- API-based models (OpenAI/Cohere) are viable for prototyping but become expensive at scale (>100K documents).
- No single model perfectly handles all Indian regional languages; a tiered approach is recommended.

---

## 2. System Context & Requirements

### 2.1 Document Characteristics

| Property | Typical Value |
|----------|---------------|
| Supreme Court Judgment | 5,000 - 80,000 words |
| High Court Judgment | 2,000 - 40,000 words |
| Act/Statute Section | 100 - 2,000 words |
| Bare Act (full) | 10,000 - 200,000 words |
| Legal Notice/FIR | 200 - 3,000 words |

### 2.2 Language Distribution (Estimated)

| Language | Corpus Share | Query Share |
|----------|-------------|-------------|
| English | 70% | 40% |
| Hindi | 15% | 30% |
| Hindi-English Code-Mixed | 10% | 20% |
| Regional (Tamil, Telugu, etc.) | 5% | 10% |

### 2.3 User Profiles & Query Patterns

| User Type | Query Style | Precision Need | Latency Tolerance |
|-----------|-------------|----------------|-------------------|
| Lawyer | Technical, citation-heavy | Very High | Medium (2-5s) |
| Legal Advisor | Semi-technical | High | Medium (2-5s) |
| Police/Officer | Procedural, section-based | High | Low (1-2s) |
| Layman Citizen | Natural language, Hindi-mix | Moderate | Low (1-2s) |

### 2.4 Infrastructure Constraints

- **No local GPU** available for inference
- **Lightning AI**: 15 free credits/month (1 credit ~= 1 hour of A10G GPU or equivalent)
- **Qdrant Cloud**: Vector database (supports dense, sparse, and multi-vectors)
- **Target Scale**: 500K - 2M document chunks initially, scaling to 10M+

---

## 3. Model Profiles

### 3.1 all-MiniLM-L6-v2

- **Developer:** Microsoft (via Sentence-Transformers)
- **Architecture:** MiniLM (distilled BERT), 6 layers
- **Parameters:** 22.7M
- **Dimensions:** 384
- **Max Tokens:** 256 (effective), 512 (with truncation)
- **Training:** 1B+ sentence pairs from diverse sources
- **Primary Use:** General-purpose sentence similarity
- **License:** Apache 2.0

### 3.2 InLegalBERT

- **Developer:** IIT Kharagpur (law-ai group)
- **Architecture:** BERT-base, 12 layers
- **Parameters:** ~110M
- **Dimensions:** 768 (hidden state, NOT sentence embedding)
- **Max Tokens:** 512
- **Training:** 5.4M Indian legal documents (~27 GB), fine-tuned from Legal-BERT-SC
- **Critical Note:** This is a **masked language model**, NOT a sentence embedding model. It requires fine-tuning with a sentence-transformers head or contrastive learning to produce useful embeddings.
- **License:** Open (research)

### 3.3 Legal-BERT (nlpaueb/legal-bert-base-uncased)

- **Developer:** Athens University of Economics and Business
- **Architecture:** BERT-base, 12 layers
- **Parameters:** ~110M
- **Dimensions:** 768 (hidden state)
- **Max Tokens:** 512
- **Training:** 12 GB of diverse English legal text (EU/UK/US legislation, court cases, contracts)
- **Critical Note:** Same as InLegalBERT -- this is an MLM, not a sentence encoder. Requires adaptation.
- **License:** Open (research)

### 3.4 BGE-large-en-v1.5

- **Developer:** BAAI (Beijing Academy of AI)
- **Architecture:** BERT-large based, 24 layers
- **Parameters:** ~335M
- **Dimensions:** 1024
- **Max Tokens:** 512
- **MTEB Average:** 64.23 (Rank #1 at time of release for open-source models)
- **Retrieval NDCG@10 (MTEB):** 54.29
- **License:** MIT

### 3.5 BGE-M3

- **Developer:** BAAI
- **Architecture:** XLM-RoBERTa-Large based
- **Parameters:** ~568M
- **Dimensions:** 1024 (dense), variable (sparse), per-token (ColBERT)
- **Max Tokens:** 8192
- **Languages:** 100+ (including Hindi, Tamil, Telugu, Kannada, Malayalam, Bengali, Marathi, Gujarati, Urdu)
- **Unique Feature:** Unified dense + sparse + ColBERT retrieval in one model
- **MIRACL Avg (multilingual retrieval):** Top performer
- **License:** MIT

### 3.6 E5-large-v2

- **Developer:** Microsoft (intfloat)
- **Architecture:** BERT-large based, 24 layers
- **Parameters:** ~335M
- **Dimensions:** 1024
- **Max Tokens:** 512
- **MTEB Average:** 62.25
- **Retrieval NDCG@10 (MTEB):** 50.56
- **Requires Prefix:** "query: " for queries, "passage: " for passages
- **License:** MIT

### 3.7 Multilingual-E5-Large

- **Developer:** Microsoft (intfloat)
- **Architecture:** XLM-RoBERTa-Large, 24 layers
- **Parameters:** ~560M
- **Dimensions:** 1024
- **Max Tokens:** 512
- **Languages:** 94-100 (includes Hindi, Bengali, Telugu, Tamil, Malayalam, Kannada, Marathi, Gujarati, Urdu, Punjabi)
- **Mr. TyDi MRR@10:** 70.5 (average across languages)
- **Telugu MRR@10:** 72.7, **Bengali MRR@10:** 73.2
- **Requires Prefix:** "query: " / "passage: "
- **License:** MIT

### 3.8 Jina Embeddings v3

- **Developer:** Jina AI
- **Architecture:** XLM-RoBERTa based with LoRA task adapters
- **Parameters:** ~572M
- **Dimensions:** Up to 1024 (supports Matryoshka -- truncatable to 256/512/768)
- **Max Tokens:** 8192
- **Languages:** 100+ (multilingual, including major Indian languages)
- **Unique Feature:** Task-specific LoRA adapters (retrieval.query, retrieval.passage, separation, classification, text-matching)
- **MTEB Average:** ~65.5 (competitive with top models)
- **License:** CC BY-NC 4.0 (non-commercial requires license purchase)
- **API Available:** Yes, via Jina AI API

### 3.9 Cohere embed-v3 (embed-english-v3.0 / embed-multilingual-v3.0)

- **Developer:** Cohere
- **Architecture:** Proprietary transformer
- **Parameters:** Undisclosed (estimated 1-2B)
- **Dimensions:** 1024 (supports compression to 256/384/512/768)
- **Max Tokens:** 512
- **Languages:** 100+ (multilingual variant)
- **Unique Feature:** Built-in input type parameter (search_query, search_document, classification, clustering); native int8/binary quantization
- **MTEB Retrieval NDCG@10:** ~56.8 (English v3)
- **Pricing:** $0.10 per 1M tokens
- **License:** Proprietary (API-only)

### 3.10 OpenAI text-embedding-3-small

- **Developer:** OpenAI
- **Architecture:** Proprietary
- **Parameters:** Undisclosed
- **Dimensions:** 1536 (supports Matryoshka truncation to 512/256)
- **Max Tokens:** 8191
- **Languages:** Multilingual (strongest in high-resource languages)
- **MTEB Average:** ~62.3
- **Retrieval NDCG@10:** ~51.7
- **Pricing:** $0.02 per 1M tokens
- **License:** Proprietary (API-only)

### 3.11 OpenAI text-embedding-3-large

- **Developer:** OpenAI
- **Architecture:** Proprietary
- **Parameters:** Undisclosed (estimated >1B)
- **Dimensions:** 3072 (supports Matryoshka truncation to 256/512/1024/1536)
- **Max Tokens:** 8191
- **Languages:** Multilingual
- **MTEB Average:** ~64.6
- **Retrieval NDCG@10:** ~55.4
- **Pricing:** $0.13 per 1M tokens
- **License:** Proprietary (API-only)

### 3.12 Indian Legal Domain Models on HuggingFace

After research, the following additional models were identified:

| Model | Developer | Notes |
|-------|-----------|-------|
| `law-ai/InLegalBERT` | IIT Kharagpur | MLM only, not sentence embeddings (covered above) |
| `law-ai/InCaseLawBERT` | IIT Kharagpur | Trained on Indian case law, same limitations as InLegalBERT |
| `nlpaueb/legal-bert-base-uncased` | AUEB | EU/UK legal, not India-specific |
| `pile-of-law/legalbert-large-1.7M-2` | Pile of Law | US legal, large variant |
| `Exploration-Lab/IL-TUR` | IIT Gandhinagar | Indian Legal Text Understanding & Reasoning benchmark (not an embedding model but useful for evaluation) |
| `nickil/indian-legal-sentence-transformer` | Community | Sentence-transformer fine-tuned on Indian legal text (limited validation) |
| `ai4bharat/indic-bert` | AI4Bharat | ALBERT-based, 12 Indian languages, but NOT optimized for embeddings or legal domain |

**Key Finding:** There is no production-ready, well-validated Indian legal sentence embedding model available. The closest options require fine-tuning InLegalBERT with sentence-transformers, or using general-purpose multilingual models.

---

## 4. Master Comparison Table

### 4.1 Core Specifications

| Model | Params | Dims | Max Tokens | Model Size (disk) | Open Source |
|-------|--------|------|------------|-------------------|-------------|
| all-MiniLM-L6-v2 | 22.7M | 384 | 256 | ~80 MB | Yes (Apache 2.0) |
| InLegalBERT | 110M | 768* | 512 | ~440 MB | Yes (Research) |
| Legal-BERT | 110M | 768* | 512 | ~440 MB | Yes (Research) |
| BGE-large-en-v1.5 | 335M | 1024 | 512 | ~1.3 GB | Yes (MIT) |
| **BGE-M3** | **568M** | **1024** | **8192** | **~2.3 GB** | **Yes (MIT)** |
| E5-large-v2 | 335M | 1024 | 512 | ~1.3 GB | Yes (MIT) |
| Multilingual-E5-Large | 560M | 1024 | 512 | ~2.2 GB | Yes (MIT) |
| Jina Embeddings v3 | 572M | 1024 | 8192 | ~2.3 GB | CC BY-NC 4.0** |
| Cohere embed-v3 | N/A | 1024 | 512 | API only | No (Proprietary) |
| OpenAI embed-3-small | N/A | 1536 | 8191 | API only | No (Proprietary) |
| OpenAI embed-3-large | N/A | 3072 | 8191 | API only | No (Proprietary) |

*\* InLegalBERT/Legal-BERT produce 768-dim hidden states, not optimized sentence embeddings.*
*\*\* Jina v3 requires a commercial license for production use.*

### 4.2 Performance & Capability Matrix

| Model | MTEB Avg | Retrieval NDCG@10 | Legal Domain Accuracy | Indian Lang Support | Sparse Vectors | Fine-tune Feasible |
|-------|----------|-------------------|----------------------|--------------------|-----------------|--------------------|
| all-MiniLM-L6-v2 | 56.26 | 41.95 | Low | None | No | Easy |
| InLegalBERT | N/A (MLM) | N/A (needs FT) | High (after FT) | None | No | Hard (needs ST head) |
| Legal-BERT | N/A (MLM) | N/A (needs FT) | Medium-High | None | No | Hard (needs ST head) |
| BGE-large-en-v1.5 | 64.23 | 54.29 | Medium | None | No | Moderate |
| **BGE-M3** | **~62.5** | **~53.8** | **Medium-High** | **Excellent** | **Yes (native)** | **Moderate** |
| E5-large-v2 | 62.25 | 50.56 | Medium | None | No | Moderate |
| Multilingual-E5-Large | ~61.5 | ~49.2 | Medium | Good | No | Moderate |
| Jina Embeddings v3 | ~65.5 | ~55.0 | Medium | Good | No | Yes (LoRA built-in) |
| Cohere embed-v3 | ~64.5 | ~56.8 | Medium | Good (multilingual) | No | No |
| OpenAI embed-3-small | ~62.3 | ~51.7 | Medium | Moderate | No | No |
| OpenAI embed-3-large | ~64.6 | ~55.4 | Medium-High | Moderate | No | No |

### 4.3 Infrastructure & Cost Matrix

| Model | CPU Inference | GPU VRAM (FP16) | Latency/Query (CPU) | Latency/Query (GPU) | Cost Model |
|-------|--------------|-----------------|---------------------|---------------------|------------|
| all-MiniLM-L6-v2 | Excellent | ~200 MB | ~15 ms | ~3 ms | Free |
| InLegalBERT | Good | ~500 MB | ~50 ms | ~8 ms | Free |
| Legal-BERT | Good | ~500 MB | ~50 ms | ~8 ms | Free |
| BGE-large-en-v1.5 | Moderate | ~700 MB | ~120 ms | ~12 ms | Free |
| **BGE-M3** | **Slow** | **~1.5 GB** | **~250 ms** | **~20 ms** | **Free** |
| E5-large-v2 | Moderate | ~700 MB | ~120 ms | ~12 ms | Free |
| Multilingual-E5-Large | Slow | ~1.4 GB | ~200 ms | ~18 ms | Free |
| Jina Embeddings v3 | Slow | ~1.5 GB | ~250 ms | ~20 ms | Free (non-commercial) / API |
| Cohere embed-v3 | N/A (API) | N/A | ~100-300 ms (network) | N/A | $0.10/1M tokens |
| OpenAI embed-3-small | N/A (API) | N/A | ~80-200 ms (network) | N/A | $0.02/1M tokens |
| OpenAI embed-3-large | N/A (API) | N/A | ~100-300 ms (network) | N/A | $0.13/1M tokens |

*Note: CPU latency assumes modern 8-core CPU with 32GB RAM. GPU latency assumes A10G (24GB VRAM). All latencies are per single query (not batch).*

### 4.4 Qdrant Compatibility Matrix

| Model | Dense Vector Support | Sparse Vector Support | Multi-Vector (ColBERT) | Named Vectors | Binary Quantization |
|-------|---------------------|----------------------|----------------------|---------------|-------------------|
| all-MiniLM-L6-v2 | Full | External (BM25) | No | Yes | Yes |
| InLegalBERT | Manual* | External (BM25) | No | Yes | Yes |
| BGE-large-en-v1.5 | Full | External (BM25) | No | Yes | Yes |
| **BGE-M3** | **Full** | **Native** | **Native** | **Yes** | **Yes** |
| E5-large-v2 | Full | External (BM25) | No | Yes | Yes |
| Multilingual-E5-Large | Full | External (BM25) | No | Yes | Yes |
| Jina Embeddings v3 | Full | External (BM25) | No | Yes | Yes |
| Cohere embed-v3 | Full | External (BM25) | No | Yes | Yes (native int8) |
| OpenAI embed-3-small | Full | External (BM25) | No | Yes | Yes |
| OpenAI embed-3-large | Full | External (BM25) | No | Yes | Yes |

*\* InLegalBERT requires custom pooling to extract dense vectors; not plug-and-play with Qdrant.*

All models produce vectors that Qdrant can store and index. However, BGE-M3 stands alone in natively producing both dense and sparse vectors, eliminating the need for a separate BM25/SPLADE pipeline.

---

## 5. Detailed Analysis by Criterion

### 5.1 Legal Domain Accuracy

Legal retrieval requires understanding:
- Statutory language ("notwithstanding anything contained in...")
- Case citations ("AIR 1973 SC 1461")
- Section references ("Section 302 read with Section 34 of IPC")
- Latin legal maxims ("res judicata", "stare decisis")
- Indian legal nomenclature ("FIR", "chargesheet", "cognizable offence")

**Ranking for Legal Domain Understanding:**

1. **InLegalBERT (after fine-tuning)** -- Trained on 5.4M Indian legal docs. Understands Indian legal vocabulary natively. However, requires substantial engineering to convert to a sentence embedder.
2. **BGE-M3** -- While general-purpose, its large capacity (568M params) and broad training data give it reasonable legal understanding. Its 8192 token context is critical for legal passages.
3. **OpenAI embed-3-large** -- Large capacity model with broad training including legal text. Benefits from OpenAI's massive training corpus.
4. **Jina Embeddings v3** -- Strong general retrieval with task-specific adapters.
5. **Cohere embed-v3** -- Good general retrieval, competitive benchmarks.
6. **BGE-large-en-v1.5** -- Strong English retrieval but 512 token limit hurts legal use.
7. **E5-large-v2** -- Similar to BGE-large but slightly lower retrieval scores.
8. **all-MiniLM-L6-v2** -- Too small to capture legal nuance. Significant quality loss on domain-specific queries.

**Important Note on Legal Benchmarks:**
There are no widely-accepted retrieval benchmarks for Indian legal text. The IL-TUR benchmark from IIT Gandhinagar covers classification/NLI tasks, not retrieval. The LegalBench (Stanford) and LexGLUE benchmarks are US/EU focused. For Indian legal retrieval, you will need to build a custom evaluation set (recommended: 200-500 query-document pairs annotated by legal experts).

### 5.2 Multilingual Support (Indian Languages)

| Model | Hindi | Tamil | Telugu | Malayalam | Kannada | Bengali | Code-Mixed |
|-------|-------|-------|--------|-----------|---------|---------|------------|
| all-MiniLM-L6-v2 | None | None | None | None | None | None | None |
| InLegalBERT | None | None | None | None | None | None | None |
| BGE-large-en-v1.5 | None | None | None | None | None | None | None |
| **BGE-M3** | **Strong** | **Moderate** | **Moderate** | **Moderate** | **Moderate** | **Strong** | **Moderate** |
| E5-large-v2 | None | None | None | None | None | None | None |
| **M-E5-Large** | **Strong** | **Moderate** | **Good** | **Moderate** | **Moderate** | **Good** | **Moderate** |
| Jina v3 | Good | Moderate | Moderate | Moderate | Moderate | Good | Moderate |
| Cohere v3 ML | Good | Good | Good | Moderate | Moderate | Good | Moderate |
| OpenAI 3-small | Moderate | Weak | Weak | Weak | Weak | Moderate | Weak |
| OpenAI 3-large | Good | Moderate | Moderate | Weak | Weak | Moderate | Moderate |

**Key Insight:** For Hindi and code-mixed Hindi-English queries (which represent ~50% of expected query volume), BGE-M3 and Multilingual-E5-Large are the strongest open-source options. Both are based on XLM-RoBERTa-Large which was explicitly trained on Indian languages. For Dravidian languages (Tamil, Telugu, Malayalam, Kannada), performance degrades for all models -- these are lower-resource languages.

**Code-Mixed Challenge:** Hindi-English code-mixing (e.g., "kya Section 498A mein bail milti hai?") is poorly handled by all models. BGE-M3 and Multilingual-E5-Large handle it best due to their multilingual training, but dedicated fine-tuning on code-mixed legal queries would significantly improve performance.

### 5.3 Max Token Length (Critical for Legal Documents)

This is one of the most decisive factors. Legal documents are long. Even after chunking, relevant passages often exceed 512 tokens.

| Model | Max Tokens | Effective for Legal Chunks? |
|-------|------------|---------------------------|
| all-MiniLM-L6-v2 | 256 | **Severely Limited** -- Will miss most legal context |
| InLegalBERT | 512 | **Limited** -- Acceptable for sections, poor for judgments |
| Legal-BERT | 512 | **Limited** |
| BGE-large-en-v1.5 | 512 | **Limited** |
| **BGE-M3** | **8192** | **Excellent** -- Can handle full legal paragraphs and sections |
| E5-large-v2 | 512 | **Limited** |
| Multilingual-E5-Large | 512 | **Limited** |
| **Jina v3** | **8192** | **Excellent** |
| Cohere embed-v3 | 512 | **Limited** |
| **OpenAI embed-3-small** | **8191** | **Excellent** |
| **OpenAI embed-3-large** | **8191** | **Excellent** |

**Recommendation:** For legal documents, models with 8K+ context (BGE-M3, Jina v3, OpenAI embed-3) are strongly preferred. With 512-token models, you must use aggressive chunking (typically 400-450 tokens with 50-100 token overlap), which increases storage, cost, and retrieval complexity.

### 5.4 Inference Speed & Compute Requirements

For a system with no local GPU and 15 Lightning AI credits/month:

**CPU-Only Feasibility (for real-time query embedding):**

| Model | CPU Inference Viable? | Tokens/sec (CPU) | Notes |
|-------|----------------------|-------------------|-------|
| all-MiniLM-L6-v2 | **Yes (excellent)** | ~3000 | Best CPU performance |
| InLegalBERT | Yes (good) | ~1200 | Standard BERT speed |
| BGE-large-en-v1.5 | Yes (acceptable) | ~500 | Noticeably slower |
| BGE-M3 | **Marginal** | ~200 | Slow on CPU, usable for single queries |
| Multilingual-E5-Large | **Marginal** | ~200 | Similar to BGE-M3 |
| Jina v3 | **Marginal** | ~200 | Similar to BGE-M3 |

**GPU Requirement for Batch Indexing:**

| Model | VRAM (FP16) | VRAM (FP32) | Batch Speed (A10G) |
|-------|------------|------------|---------------------|
| all-MiniLM-L6-v2 | ~200 MB | ~400 MB | ~5000 docs/sec |
| InLegalBERT | ~500 MB | ~1 GB | ~2000 docs/sec |
| BGE-large-en-v1.5 | ~700 MB | ~1.4 GB | ~1000 docs/sec |
| BGE-M3 | ~1.5 GB | ~3 GB | ~300 docs/sec |
| Multilingual-E5-Large | ~1.4 GB | ~2.8 GB | ~300 docs/sec |
| Jina v3 | ~1.5 GB | ~3 GB | ~300 docs/sec |

*All models fit comfortably on an A10G (24 GB VRAM). Even BGE-M3 uses only ~6% of available VRAM.*

---

## 6. Answering the Six Strategic Questions

### Question 1: Is InLegalBERT worth the extra GPU cost over all-MiniLM-L6-v2 for legal accuracy?

**Answer: No, not as a direct comparison. But the question itself reveals a false dichotomy.**

InLegalBERT is NOT a sentence embedding model. Comparing it to all-MiniLM-L6-v2 is comparing apples to oranges. To use InLegalBERT for retrieval, you would need to:

1. Add a sentence-transformers pooling head
2. Generate or acquire legal sentence-pair training data (positive/negative passage pairs)
3. Fine-tune with contrastive loss (MultipleNegativesRankingLoss or similar)
4. Validate on a custom Indian legal retrieval benchmark

**Estimated effort:** 2-4 weeks of engineering + 5-10 Lightning AI GPU hours for fine-tuning.

**The real comparison should be:**
- all-MiniLM-L6-v2 (zero effort, weak legal performance, 256 tokens)
- BGE-M3 (zero effort, good legal performance, 8192 tokens, multilingual)
- Fine-tuned InLegalBERT-ST (high effort, potentially best Indian legal performance, 512 tokens)

**Verdict:** Skip InLegalBERT initially. Start with BGE-M3. If retrieval quality is insufficient after evaluation, invest in fine-tuning InLegalBERT as a sentence transformer -- but only after you have built a proper evaluation dataset.

### Question 2: Which model gives the best legal relevance per dollar/compute?

**Cost-Effectiveness Analysis (per 1M document chunks embedded):**

| Model | Compute Cost | Quality (Est. Legal NDCG@10) | Quality per Dollar |
|-------|-------------|-----------------------------|--------------------|
| all-MiniLM-L6-v2 | ~$0.05 (CPU) | ~35% | 700 |
| BGE-M3 | ~$0.50 (GPU) | ~52% | 104 |
| OpenAI embed-3-small | ~$2.00 (API) | ~48% | 24 |
| OpenAI embed-3-large | ~$13.00 (API) | ~54% | 4.2 |
| Cohere embed-v3 | ~$10.00 (API) | ~55% | 5.5 |
| Jina v3 (self-hosted) | ~$0.50 (GPU) | ~53% | 106 |

*Quality estimates are hypothetical for Indian legal domain; actual numbers require benchmarking.*

**Winner: BGE-M3 (self-hosted)** offers the best quality-per-dollar ratio for the Indian legal domain, considering its multilingual support, long context, and native sparse vectors. Jina v3 is comparable but has commercial licensing costs.

For **query-time** (real-time inference), if running on CPU:
- **OpenAI embed-3-small** at $0.02/1M tokens is effectively free for query embedding (~$0.02/month for 1M queries).
- BGE-M3 on CPU adds ~200ms latency per query but costs nothing.

### Question 3: For hybrid retrieval (dense+sparse), what combination works best?

**Recommended Hybrid Architecture:**

```
Query --> [BGE-M3] --> Dense Vector (1024d) + Sparse Vector (native)
                         |                        |
                         v                        v
                    Qdrant Dense Index      Qdrant Sparse Index
                         |                        |
                         +--- Reciprocal Rank Fusion (RRF) ---+
                                        |
                                        v
                              Merged Candidate Set
                                        |
                                        v
                               Cross-Encoder Reranker
                                        |
                                        v
                                  Final Results
```

**Why BGE-M3 for Hybrid:**
1. **Single model, dual output:** BGE-M3 produces both dense and sparse vectors in one forward pass. No need for a separate BM25 index or SPLADE model.
2. **Qdrant native support:** Qdrant supports named vectors, so you can store both dense and sparse vectors in the same collection.
3. **Proven combination:** BGE-M3's paper shows that combining dense (weight 0.4) + sparse (weight 0.2) + ColBERT (weight 0.4) achieves the best results.

**Alternative if NOT using BGE-M3:**

```
Dense: Any embedding model (e.g., OpenAI embed-3-large)
Sparse: Qdrant's built-in BM25 or external SPLADE/Elastic
Fusion: RRF with alpha=0.7 (dense) and beta=0.3 (sparse)
```

**Legal-Specific Hybrid Rationale:**
- **Dense vectors** capture semantic meaning ("What are the grounds for divorce?" matches "dissolution of marriage under Section 13")
- **Sparse vectors** capture exact legal terms ("Section 498A IPC" must match exactly, not semantically)
- For legal retrieval, sparse matching is MORE important than in general domains because section numbers, act names, and citations are critical identifiers.

**Recommended weights for legal domain:** Dense 0.5, Sparse 0.35, ColBERT 0.15 (if using BGE-M3's triple mode).

### Question 4: Can we use a tiered approach - lightweight model for layman queries, heavy model for lawyer queries?

**Answer: Yes, and this is the recommended architecture.**

```
                    User Query
                        |
                        v
               Query Classifier
              /         |         \
             v          v          v
         [Layman]   [Officer]   [Lawyer]
             |          |          |
             v          v          v
      all-MiniLM    BGE-M3     BGE-M3 +
      + BM25        Hybrid     ColBERT Rerank
             |          |          |
             v          v          v
        Top-5       Top-10      Top-20
        Simple      Detailed    Full citation
        Answer      Answer      with precedents
```

**Tier 1: Layman / Quick Answers**
- **Model:** all-MiniLM-L6-v2 (CPU, <20ms latency)
- **Retrieval:** Dense-only, top-5 results
- **Use Case:** "Can a tenant be evicted?", "What is the punishment for theft?"
- **Why:** Speed matters; users expect instant answers. Legal precision is less critical.

**Tier 2: Officers / Procedural Queries**
- **Model:** BGE-M3 dense + sparse (CPU/GPU, <300ms latency)
- **Retrieval:** Hybrid, top-10 results
- **Use Case:** "Procedure for filing FIR under Section 154 CrPC", "Bail provisions for NDPS Act"
- **Why:** Need exact section matching (sparse) + semantic understanding (dense).

**Tier 3: Lawyers / Complex Legal Research**
- **Model:** BGE-M3 full (dense + sparse + ColBERT) or OpenAI embed-3-large
- **Retrieval:** Hybrid with cross-encoder reranking, top-20 results
- **Use Case:** "Supreme Court precedents on right to privacy post-Puttaswamy", "Interpretation of Section 14 of Hindu Succession Act after 2005 amendment"
- **Why:** Maximum recall and precision needed. Latency tolerance is higher.

**Implementation Note:** The query classifier can be a simple intent classifier (fine-tuned BERT-tiny on ~1000 labeled queries) or rule-based (presence of legal citations/section numbers triggers Tier 3, simple Hindi queries trigger Tier 1).

### Question 5: What about using API-based embeddings (Cohere/OpenAI) vs self-hosted?

**Decision Matrix:**

| Factor | API-Based (OpenAI/Cohere) | Self-Hosted (BGE-M3) |
|--------|--------------------------|---------------------|
| **Setup Time** | Minutes | Hours to days |
| **Maintenance** | Zero | Updates, monitoring needed |
| **Latency** | 80-300ms (network) | 20ms (GPU) / 200ms (CPU) |
| **Cost at 1M docs** | $2-13 (one-time index) | ~$0.50 (GPU time) |
| **Cost at 10M docs** | $20-130 (one-time index) | ~$5 (GPU time) |
| **Query cost (1M/month)** | $0.02-0.13/month | $0 (CPU) or ~$15/month (GPU) |
| **Data Privacy** | Data sent to third party | Full control |
| **Uptime/Reliability** | 99.9%+ SLA | You manage |
| **Fine-tuning** | Not possible | Full control |
| **Vendor Lock-in** | High (re-index to switch) | None |
| **Indian Language Quality** | Moderate | Good (BGE-M3) |

**Recommendation:**

1. **Prototyping Phase:** Use **OpenAI text-embedding-3-small** ($0.02/1M tokens). Cheapest, fastest to integrate, 8K context. Get the pipeline working.

2. **Production Phase:** Migrate to **self-hosted BGE-M3**. Reasons:
   - Indian legal data contains sensitive case information (client privilege, FIRs, etc.) -- sending to US APIs may violate data residency requirements.
   - The Indian government's Digital Personal Data Protection Act (DPDPA) 2023 imposes restrictions on cross-border data transfer.
   - Long-term cost is dramatically lower for self-hosted.
   - You retain the ability to fine-tune on Indian legal data.

3. **Fallback:** Keep OpenAI embed-3-large as a fallback for when self-hosted infrastructure is down or for burst capacity.

### Question 6: For Indian multilingual support, which model handles Hindi/regional languages best?

**Detailed Indian Language Performance Ranking:**

#### Hindi (highest priority - 30% of queries)

1. **BGE-M3** -- Best overall. XLM-RoBERTa backbone with strong Hindi representation. Handles Devanagari natively. 8K context means less information loss from chunking Hindi legal text.
2. **Multilingual-E5-Large** -- Very close to BGE-M3 on Hindi. Mr. TyDi Hindi results are strong. But limited to 512 tokens.
3. **Cohere embed-multilingual-v3** -- Good Hindi support, but API-only.
4. **Jina v3** -- Good Hindi, 8K context.
5. **OpenAI embed-3-large** -- Moderate Hindi. Worse than dedicated multilingual models.

#### Telugu/Tamil/Kannada/Malayalam (Dravidian languages)

1. **Multilingual-E5-Large** -- Telugu MRR@10 of 72.7 on Mr. TyDi is the highest reported score for any open model.
2. **BGE-M3** -- Close second. Broad multilingual training.
3. **Cohere embed-multilingual-v3** -- Reasonable Dravidian support.
4. **Jina v3** -- Moderate Dravidian support.
5. **OpenAI models** -- Weakest on Dravidian languages.

#### Hindi-English Code-Mixed (critical for real usage)

1. **BGE-M3** -- Best among existing models due to multilingual + English strength.
2. **Multilingual-E5-Large** -- Good but 512-token limit hurts.
3. **All others** -- Untested on code-mixed; likely weak.

**Recommendation for Indian multilingual:** BGE-M3 as the primary model. For critical Dravidian language queries, consider a dedicated pipeline using Multilingual-E5-Large (if you can accept the 512-token limit) or invest in fine-tuning BGE-M3 on Indian language legal pairs.

---

## 7. GPU Cost Analysis for Lightning AI

### 7.1 Lightning AI Credit System

| GPU Type | Credits/Hour | VRAM | Good For |
|----------|-------------|------|----------|
| A10G | ~1 credit | 24 GB | Inference + fine-tuning |
| T4 | ~0.5 credit | 16 GB | Inference only |
| A100 (40GB) | ~2 credits | 40 GB | Large-scale fine-tuning |
| L4 | ~0.75 credit | 24 GB | Inference + light fine-tuning |

**Monthly Budget:** 15 credits = ~15 hours of A10G GPU time.

### 7.2 Indexing Cost Estimation

Assumptions:
- 500K document chunks (initial corpus)
- Average chunk: 500 tokens
- BGE-M3 throughput on A10G: ~300 chunks/sec (batch size 32, FP16)

| Task | Chunks | Time (A10G) | Credits |
|------|--------|-------------|---------|
| Initial index (500K) | 500,000 | ~28 minutes | ~0.5 |
| Initial index (2M) | 2,000,000 | ~1.8 hours | ~2 |
| Monthly updates (~50K) | 50,000 | ~3 minutes | ~0.05 |
| Re-index (full, 2M) | 2,000,000 | ~1.8 hours | ~2 |

### 7.3 Fine-tuning Cost Estimation

| Task | Model | Data | Epochs | Time (A10G) | Credits |
|------|-------|------|--------|-------------|---------|
| Fine-tune BGE-M3 | 568M | 50K pairs | 3 | ~4 hours | ~4 |
| Fine-tune InLegalBERT-ST | 110M | 50K pairs | 5 | ~2 hours | ~2 |
| Fine-tune all-MiniLM | 22.7M | 50K pairs | 5 | ~30 min | ~0.5 |

### 7.4 Monthly Credit Budget Plan

| Activity | Credits/Month | Priority |
|----------|---------------|----------|
| Incremental indexing | 0.1 | Essential |
| Model experimentation | 2.0 | Phase 1 only |
| Fine-tuning (one-time) | 4.0 | Phase 2 |
| Re-indexing (quarterly) | 0.5 | Maintenance |
| Buffer/emergency | 8.4 | Reserve |
| **Total** | **15.0** | |

### 7.5 CPU-Only Operation Plan

For query-time inference (real-time), you can run BGE-M3 on CPU to save GPU credits entirely:

- **BGE-M3 on CPU (FP32):** ~200-300ms per query (acceptable for legal research)
- **BGE-M3 on CPU (ONNX quantized INT8):** ~80-150ms per query (good for production)
- **all-MiniLM-L6-v2 on CPU:** ~10-20ms per query (excellent for layman tier)

**Strategy:** Use Lightning AI GPU **only** for batch indexing and fine-tuning. Run all real-time inference on CPU (your application server). This maximizes the value of your 15 free credits.

---

## 8. Hybrid Retrieval Strategy

### 8.1 Recommended Architecture

```
+-------------------------------------------------------------------+
|                    QDRANT COLLECTION: indian_legal                 |
|                                                                   |
|  Named Vectors:                                                   |
|  +------------------+  +------------------+  +-----------------+  |
|  | "dense"          |  | "sparse"         |  | Payload         |  |
|  | dim: 1024        |  | (sparse vector)  |  | - doc_type      |  |
|  | index: HNSW      |  | index: sparse    |  | - court         |  |
|  | distance: Cosine  |  |                  |  | - year          |  |
|  +------------------+  +------------------+  | - language      |  |
|                                              | - act_name      |  |
|                                              | - section_no    |  |
|                                              +-----------------+  |
+-------------------------------------------------------------------+
```

### 8.2 Indexing Pipeline

```python
from FlagEmbedding import BGEM3FlagModel
from qdrant_client import QdrantClient, models

# Initialize
model = BGEM3FlagModel('BAAI/bge-m3', use_fp16=True)  # GPU for indexing
client = QdrantClient(url="your-qdrant-url", api_key="your-key")

# Create collection with named vectors
client.create_collection(
    collection_name="indian_legal",
    vectors_config={
        "dense": models.VectorParams(
            size=1024,
            distance=models.Distance.COSINE,
        ),
    },
    sparse_vectors_config={
        "sparse": models.SparseVectorParams(
            modifier=models.Modifier.IDF,  # BM25-like IDF weighting
        ),
    },
)

# Encode and upsert
for batch in document_batches:
    outputs = model.encode(
        batch["texts"],
        return_dense=True,
        return_sparse=True,
    )

    points = []
    for i, (dense, sparse) in enumerate(zip(
        outputs["dense_vecs"], outputs["lexical_weights"]
    )):
        sparse_indices = list(sparse.keys())
        sparse_values = list(sparse.values())

        points.append(models.PointStruct(
            id=batch["ids"][i],
            vector={
                "dense": dense.tolist(),
                "sparse": models.SparseVector(
                    indices=sparse_indices,
                    values=sparse_values,
                ),
            },
            payload=batch["metadata"][i],
        ))

    client.upsert(collection_name="indian_legal", points=points)
```

### 8.3 Query Pipeline

```python
# Query-time (can run on CPU)
model_cpu = BGEM3FlagModel('BAAI/bge-m3', use_fp16=False)  # CPU mode

def hybrid_search(query: str, top_k: int = 20, dense_weight: float = 0.6):
    # Encode query
    query_output = model_cpu.encode(
        [query], return_dense=True, return_sparse=True
    )
    dense_vec = query_output["dense_vecs"][0]
    sparse_dict = query_output["lexical_weights"][0]

    # Hybrid search with Qdrant
    results = client.query_points(
        collection_name="indian_legal",
        prefetch=[
            # Dense retrieval
            models.Prefetch(
                query=dense_vec.tolist(),
                using="dense",
                limit=top_k * 2,
            ),
            # Sparse retrieval
            models.Prefetch(
                query=models.SparseVector(
                    indices=list(sparse_dict.keys()),
                    values=list(sparse_dict.values()),
                ),
                using="sparse",
                limit=top_k * 2,
            ),
        ],
        # Reciprocal Rank Fusion
        query=models.FusionQuery(fusion=models.Fusion.RRF),
        limit=top_k,
    )

    return results
```

### 8.4 Why This Hybrid Approach Matters for Legal

**Example queries showing dense vs. sparse strengths:**

| Query | Dense Wins | Sparse Wins | Why |
|-------|-----------|-------------|-----|
| "What is the punishment for murder?" | Yes | Partial | Semantic understanding needed |
| "Section 302 IPC" | No | **Yes** | Exact term matching critical |
| "Right to privacy fundamental right" | Yes | Partial | Conceptual matching |
| "AIR 1973 SC 1461" | No | **Yes** | Citation is an exact identifier |
| "Bail conditions NDPS Act" | Both | Both | Both semantic + legal terms |
| "Can wife claim husband property after divorce" | **Yes** | No | Layman language, no legal terms |

The hybrid approach ensures both semantic understanding AND exact legal term matching.

---

## 9. Tiered Architecture Design

### 9.1 Full System Architecture

```
                         +------------------+
                         |   User Interface |
                         |  (Web/Mobile/API)|
                         +--------+---------+
                                  |
                                  v
                         +--------+---------+
                         | Query Preprocessor|
                         | - Language detect  |
                         | - Intent classify  |
                         | - Query expansion  |
                         +--------+---------+
                                  |
                    +-------------+-------------+
                    |             |             |
                    v             v             v
              +-----+---+  +----+----+  +------+------+
              | Tier 1   |  | Tier 2   |  | Tier 3      |
              | Layman   |  | Officer  |  | Lawyer      |
              +-----+---+  +----+----+  +------+------+
              |MiniLM   |  |BGE-M3   |  |BGE-M3       |
              |Dense Only|  |Hybrid   |  |Hybrid+ColBERT|
              |CPU,<50ms|  |CPU,<300ms|  |CPU/GPU,<500ms|
              |Top-5    |  |Top-10   |  |Top-20       |
              +---------+  +---------+  +-----+-------+
                    |             |             |
                    +-------------+-------------+
                                  |
                                  v
                         +--------+---------+
                         |  Response Agent   |
                         |  (LLM-based)      |
                         |  - Summarize      |
                         |  - Cite sources   |
                         |  - Format output  |
                         +------------------+
```

### 9.2 Embedding Model Deployment

| Component | Model | Deployment | Notes |
|-----------|-------|-----------|-------|
| Tier 1 Embedder | all-MiniLM-L6-v2 | Application server (CPU) | Always-on, ~80MB RAM |
| Tier 2/3 Embedder | BGE-M3 | Application server (CPU, ONNX) | Always-on, ~2.5GB RAM |
| Batch Indexer | BGE-M3 | Lightning AI (GPU) | On-demand, scheduled |
| Reranker | cross-encoder/ms-marco-MiniLM-L-12-v2 | Application server (CPU) | For Tier 3 only |

---

## 10. Final Verdict & Recommendations

### 10.1 Primary Model: BGE-M3

**BGE-M3 is the clear winner for this Indian Legal RAG system.**

| Criterion | BGE-M3 Score | Justification |
|-----------|-------------|---------------|
| Legal Domain Accuracy | 8/10 | Large model capacity captures legal semantics well |
| Indian Language Support | 9/10 | 100+ languages including all major Indian languages |
| Max Token Length | 10/10 | 8192 tokens -- handles legal passages without aggressive chunking |
| Hybrid Retrieval | 10/10 | **Only model with native dense + sparse + ColBERT** |
| Qdrant Compatibility | 10/10 | Perfect fit with Qdrant's named vectors and sparse support |
| Cost Efficiency | 9/10 | Free, MIT license, runs on modest GPU |
| GPU Requirement | 7/10 | ~1.5GB VRAM; slow on CPU but viable with ONNX |
| Fine-tune Feasibility | 8/10 | Standard sentence-transformers fine-tuning supported |
| **Overall** | **8.9/10** | |

### 10.2 Fallback Model: OpenAI text-embedding-3-large

**For when self-hosting is not feasible or as a rapid prototyping option.**

| Criterion | Score | Justification |
|-----------|-------|---------------|
| Legal Domain Accuracy | 8/10 | Large model with broad legal training |
| Indian Language Support | 6/10 | Moderate; weaker on Dravidian languages |
| Max Token Length | 10/10 | 8191 tokens |
| Hybrid Retrieval | 5/10 | Dense only; need external BM25 |
| Cost | 6/10 | $0.13/1M tokens; adds up at scale |
| Maintenance | 10/10 | Zero maintenance, highly reliable |
| **Overall** | **7.5/10** | |

### 10.3 Lightweight Tier Model: all-MiniLM-L6-v2

**For Tier 1 (layman queries) where speed matters more than precision.**

| Criterion | Score | Justification |
|-----------|-------|---------------|
| Speed | 10/10 | Fastest inference, excellent on CPU |
| Legal Accuracy | 4/10 | General-purpose, misses legal nuance |
| Size | 10/10 | 80MB, trivial to deploy |
| **Overall for Tier 1** | **8/10** | Perfect for simple, fast queries |

### 10.4 Future Investment: Fine-tuned InLegalBERT-ST

**Recommended as a Phase 2 project (after system is live).**

Build a sentence-transformer version of InLegalBERT fine-tuned on Indian legal retrieval pairs. This would be the highest-accuracy model for English Indian legal text, but requires:
- 2,000+ manually annotated query-passage pairs from Indian legal experts
- 4-8 GPU hours for fine-tuning
- Custom evaluation on Indian legal benchmarks

### 10.5 Models NOT Recommended

| Model | Reason for Rejection |
|-------|---------------------|
| **InLegalBERT (raw)** | Not a sentence embedder; 512 token limit; English only |
| **Legal-BERT (raw)** | Not India-specific; not a sentence embedder; 512 tokens |
| **BGE-large-en-v1.5** | English only; 512 tokens; BGE-M3 is strictly better |
| **E5-large-v2** | English only; 512 tokens; lower benchmarks than BGE-large |
| **Jina v3** | CC BY-NC 4.0 license problematic for commercial use; comparable to BGE-M3 but with licensing cost |
| **Cohere embed-v3** | 512 token limit is disqualifying; API-only; ongoing cost |
| **OpenAI embed-3-small** | Weaker multilingual; use embed-3-large if going API route |

### 10.6 Recommendation Summary

```
+---------------------------------------------------------------+
|                PRODUCTION ARCHITECTURE                        |
|                                                               |
|  PRIMARY:   BGE-M3 (self-hosted)                              |
|             - Dense + Sparse hybrid via Qdrant                |
|             - 8192 token context                              |
|             - Hindi + Indian language support                 |
|             - GPU for indexing, CPU/ONNX for queries          |
|                                                               |
|  TIER 1:    all-MiniLM-L6-v2 (CPU, layman queries)           |
|             - Fast, lightweight                               |
|             - Dense-only retrieval                            |
|                                                               |
|  FALLBACK:  OpenAI text-embedding-3-large (API)              |
|             - Zero-maintenance backup                         |
|             - Use during infrastructure issues                |
|             - Good for prototyping phase                      |
|                                                               |
|  FUTURE:    Fine-tuned InLegalBERT-ST (Phase 2)              |
|             - Highest accuracy for Indian English legal text  |
|             - Requires training data investment               |
+---------------------------------------------------------------+
```

---

## 11. Implementation Roadmap

### Phase 0: Prototype (Week 1-2)
- Use **OpenAI text-embedding-3-small** for rapid prototyping
- Set up Qdrant collection (dense vectors only)
- Build end-to-end pipeline: ingest -> chunk -> embed -> store -> retrieve -> generate
- Cost: ~$2-5 total for embedding 500K chunks

### Phase 1: Production MVP (Week 3-6)
- Deploy **BGE-M3** on Lightning AI for batch indexing
- Set up CPU inference server with ONNX-optimized BGE-M3
- Implement hybrid retrieval (dense + sparse) in Qdrant
- Deploy **all-MiniLM-L6-v2** for Tier 1 queries
- Build query classifier for tiered routing
- Estimated Lightning AI credits: ~3 credits

### Phase 2: Optimization (Week 7-12)
- Build Indian legal evaluation dataset (200+ query-passage pairs)
- Benchmark BGE-M3 vs. OpenAI vs. Cohere on your actual data
- Fine-tune BGE-M3 on Indian legal pairs (if needed)
- Explore InLegalBERT-ST fine-tuning
- Implement ColBERT reranking for Tier 3
- Implement cross-encoder reranker (ms-marco-MiniLM or similar)
- Estimated Lightning AI credits: ~8 credits

### Phase 3: Scale & Multilingual (Week 13+)
- Add dedicated Hindi query handling pipeline
- Fine-tune on Hindi-English code-mixed queries
- Add regional language support (Tamil, Telugu, etc.)
- Scale to 10M+ document chunks
- Implement quantization (binary/scalar) in Qdrant for cost reduction

---

## 12. Appendix: Benchmark Sources

### 12.1 MTEB Leaderboard References

The Massive Text Embedding Benchmark (MTEB) is the standard evaluation for embedding models, covering 56+ datasets across 8 tasks (retrieval, classification, clustering, STS, etc.).

- **MTEB Leaderboard:** https://huggingface.co/spaces/mteb/leaderboard
- **BGE-M3 Paper:** Chen et al., "M3-Embedding: Multi-Lingual, Multi-Functionality, Multi-Granularity Text Embeddings Through Self-Knowledge Distillation" (2024)
- **BGE-large-en-v1.5:** Xiao et al., "C-Pack: Packaged Resources To Advance General Chinese Embedding" (2023)
- **E5 Paper:** Wang et al., "Text Embeddings by Weakly-Supervised Contrastive Pre-training" (2022)
- **Multilingual E5:** Wang et al., "Multilingual E5 Text Embeddings: A Technical Report" (2024)
- **InLegalBERT:** Paul et al., "Pre-trained Language Models for the Indian Legal Domain" (2022), IIT Kharagpur

### 12.2 Indian Legal NLP Resources

- **IL-TUR Benchmark:** IIT Gandhinagar -- Indian Legal Text Understanding and Reasoning
- **Indian Legal NER:** Named entity recognition datasets for Indian legal text
- **SemEval Legal Tasks:** Various shared tasks on legal text processing
- **AI4Bharat:** Resources for Indian language NLP (IndicBERT, IndicTrans)

### 12.3 Legal Retrieval Benchmarks (International)

- **LegalBench:** Stanford -- 162 legal reasoning tasks
- **LexGLUE:** Legal General Language Understanding Evaluation (EU/US focused)
- **COLIEE:** Competition on Legal Information Extraction and Entailment (Japan/Canada)
- **AILA:** Artificial Intelligence for Legal Assistance (Indian, but NLI focused, not retrieval)

### 12.4 Qdrant Hybrid Search References

- **Qdrant Hybrid Search Docs:** https://qdrant.tech/documentation/concepts/hybrid-queries/
- **Qdrant Sparse Vectors:** https://qdrant.tech/articles/sparse-vectors/
- **Qdrant BGE-M3 Tutorial:** https://qdrant.tech/documentation/tutorials/hybrid-search-fastembed/

### 12.5 Key Notes on Benchmark Interpretation

1. **MTEB scores are NOT legal domain scores.** A model scoring 64 on MTEB may score 45 or 75 on Indian legal retrieval depending on the specific legal sub-task.
2. **No Indian legal retrieval benchmark exists.** Building one is a prerequisite for rigorous model selection. Until then, recommendations are based on model architecture, training data, and general benchmark performance.
3. **Multilingual benchmarks (MIRACL, Mr. TyDi) are the best available proxies** for Indian language performance, but they test Wikipedia-style retrieval, not legal retrieval.
4. **Real-world performance** depends heavily on chunking strategy, query preprocessing, and the specific legal sub-domain. Always validate with domain expert evaluation.

---

*This document should be revisited quarterly as new embedding models are released frequently. Key models to watch: BGE-M3 v2 (if released), Cohere embed-v4, any India-specific legal embedding models from IIT labs or AI4Bharat.*
