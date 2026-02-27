# Data Ingestion Pipeline

How raw legal documents are processed, enriched, and indexed into Qdrant.

## Pipeline Components

```mermaid
graph TD
    subgraph SOURCES["Data Sources"]
        PDF[Scanned / Text PDFs\nBNS, BNSS, BSA handbooks\nSC Judgments]
        JSON[Pre-structured JSON\nbns_complete.json\nbnss_complete.json\nbsa_complete.json]
    end

    subgraph EXTRACT["Extraction Layer"]
        PYMUPDF[PyMuPDF fitz\nCoordinate-based text extraction]
        PDFPLUMB[pdfplumber\nTable extraction fallback]
        OCR[pytesseract + Pillow\nScanned PDF OCR fallback]
        PDF --> PYMUPDF
        PYMUPDF --> PDFPLUMB
        PDFPLUMB --> OCR
        JSON --> PARSE
    end

    subgraph PARSE["Parsing Layer"]
        PARSE[Act Parser\nIdentify: sections, chapters,\nschedules, amendments]
        NORM[Statute Normalizer\nIPC → BNS section mapping\nLegacy law cross-references]
        PARSE --> NORM
    end

    subgraph CLEAN["Cleaning Layer"]
        CLEAN[Text Cleaner\nRemove: headers, footers,\npage numbers, watermarks]
        OCR --> CLEAN
        NORM --> CLEAN
    end

    subgraph CHUNK["Chunking Layer"]
        CHUNK[Legal-Aware Chunker\nRespect section boundaries\nNo cross-section splits]
        CLEAN --> CHUNK
    end

    subgraph ENRICH["Enrichment Layer"]
        ENRICH[JSON Enricher\nAdd metadata payload:\nact_name, act_code, section_number,\nlegal_domain, user_access_level,\nstate, language, source_url]
        CHUNK --> ENRICH
    end

    subgraph VALIDATE["Validation Layer"]
        VAL[Extraction Validator\nRequired field checks\nPII stripping\nData quality gates]
        ENRICH --> VAL
    end

    subgraph EMBED["Embedding Layer (GPU)"]
        BGE[BGE-M3 Embedder\nBatch processing\nDense 1024d + Sparse BM25]
        VAL --> BGE
    end

    subgraph INDEX["Indexing Layer"]
        IDX[Qdrant Indexer\nUpsert with full payload\nProgress tracking]
        TIDX[Transition Indexer\nIPC→BNS mapping activation\nLegacy section cross-links]
        BGE --> IDX
        BGE --> TIDX
    end

    subgraph STORE["Qdrant Collections"]
        COL1[(legal_documents)]
        COL2[(legal_sections)]
        IDX --> COL1
        IDX --> COL2
        TIDX --> COL1
    end
```

---

## Ingestion Scripts

| Script | Command | Purpose |
|---|---|---|
| `data/scripts/run_ingestion.py` | `python data/scripts/run_ingestion.py` | Full PDF/JSON pipeline |
| `data/scripts/run_indexing.py` | `python data/scripts/run_indexing.py --mode setup` | Create Qdrant collections |
| `data/scripts/run_indexing.py` | `python data/scripts/run_indexing.py --act ALL` | Embed and index all acts |
| `data/scripts/run_activation.py` | `python data/scripts/run_activation.py` | Activate IPC→BNS transitions |

---

## Data Quality Rules

- Strip all PII before embedding (no personal names in vectors)
- Validate every chunk has: `act_code`, `section_number`, `text`, `user_access_level`
- Cross-reference extracted sections against source JSON for accuracy
- Adversarial assertions test for hallucinated section numbers
- Batch size tuned for GPU VRAM: 16 chunks per BGE-M3 forward pass
