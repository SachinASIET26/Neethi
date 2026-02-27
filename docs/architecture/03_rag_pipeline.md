# RAG Pipeline Components

Retrieval-Augmented Generation architecture using Qdrant hybrid search.

## Retrieval Pipeline Components

```mermaid
graph TD
    subgraph INPUT["Query Input"]
        Q[User Legal Query]
        ROLE[User Role]
    end

    subgraph EXPANSION["Query Expansion"]
        QE[LLM Query Expander
        Groq Llama 3.3 70B
        Legal synonyms + alternate phrasings]
    end

    subgraph EMBED["Embedding Layer"]
        BGE[BGE-M3 Embedder
        FlagEmbedding 1.3.3
        GPU recommended]
        DENSE[Dense Vector 1024d]
        SPARSE[Sparse Vector BM25]
        BGE --> DENSE
        BGE --> SPARSE
    end

    subgraph SEARCH["Qdrant Hybrid Search"]
        DS[Dense Search\ncosine similarity]
        SS[Sparse Search\nBM25 keyword match]
        DENSE --> DS
        SPARSE --> SS
    end

    subgraph FUSION["Result Fusion"]
        RRF[Reciprocal Rank Fusion\nk=60\nMerges dense + sparse rankings]
        DS --> RRF
        SS --> RRF
    end

    subgraph RERANK["Re-ranking"]
        CE[CrossEncoder\nms-marco-MiniLM-L-6-v2\nsentence-transformers]
        RRF --> CE
    end

    subgraph FILTER["Role-Based Filtering"]
        RF[Metadata Filter\nuser_access_level\ncitizen / lawyer / advisor / police]
        CE --> RF
    end

    subgraph OUTPUT["Retrieved Chunks"]
        TOP[Top-K Document Chunks\nwith metadata + scores]
        RF --> TOP
    end

    Q --> QE
    QE --> BGE
    ROLE --> RF
```

---

## Qdrant Collections

```mermaid
graph LR
    subgraph COLLECTIONS["Qdrant Collections"]
        subgraph LD["legal_documents — Main Collection"]
            LD1[Dense Vector 1024d]
            LD2[Sparse Vector BM25]
            LD3["Payload: text, act_name, act_code,
                 section_number, court, case_name,
                 legal_domain, state, language,
                 user_access_level, source_url"]
        end

        subgraph LS["legal_sections — Verification Collection"]
            LS1[Section-level chunks]
            LS2["Payload: act_code, section_number,
                 section_title, full_text,
                 amendment_history, related_sections"]
        end

        subgraph DT["document_templates — Drafting Templates"]
            DT1[Template vectors]
            DT2["Payload: template_type, required_fields,
                 optional_fields, jurisdiction, language"]
        end
    end

    SEARCH[Hybrid Search] --> LD
    VERIFY[Citation Verifier] --> LS
    DRAFT[Document Drafter] --> DT
```

---

## Embedding Strategy

| Dimension | Type | Use |
|---|---|---|
| Dense 1024d | BGE-M3 | Semantic similarity |
| Sparse BM25 | BGE-M3 | Keyword exact match |
| Scalar INT8 | Quantization | Memory optimization |

**Why BGE-M3?**
- Single model pass generates both dense and sparse vectors
- Outperforms separate dense + BM25 pipeline on legal queries
- Handles multilingual text (Hindi, English, mixed)
- See `docs/embedding_model_comparison.md` for evaluation details
