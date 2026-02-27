# Neethi AI - Indian Legal Domain Agentic AI System

## Project Overview

Neethi AI is an agentic AI system for the Indian Legal Domain serving lawyers, citizens, legal advisors, and police. It provides legally grounded, citation-backed, hallucination-free legal assistance through a multi-agent architecture.

**Core Principle: In legal, a wrong answer is worse than a no answer. Every response must be source-cited and double-verified.**

---

## Tech Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| AI Framework | CrewAI | Multi-agent orchestration |
| API Backend | FastAPI | REST API with SSE streaming |
| Vector Database | Qdrant | Hybrid (dense+sparse) RAG retrieval |
| Frontend | Next.js (React) | Role-based dashboard with SSR |
| Translation | Sarvam AI | Indian language support |
| Visual UI | Thesys API | Visual explanations for layman users |
| Search | SERP API | Nearby legal resource discovery |
| PDF Processing | PyMuPDF + pdfplumber | Legal document extraction |
| Document Generation | Jinja2 + WeasyPrint | Template-based legal doc drafting |
| Database | PostgreSQL (Supabase) | User data, sessions, drafts |
| Cache | Redis (Upstash) | Response caching, rate limiting |
| GPU Compute | Lightning AI | Embedding generation, model inference |

## LLM Provider Strategy

| Task | Primary Model | Fallback |
|------|--------------|----------|
| Query Classification | Groq (Llama 3.3 70B) | DeepSeek-Chat |
| Legal Reasoning (IRAC) | DeepSeek-R1 | Claude Sonnet |
| Response Formatting | Groq (Llama 3.3 70B) | DeepSeek-Chat |
| Citation Verification | DeepSeek-Chat | Claude Haiku |
| Document Drafting | Claude Sonnet | DeepSeek-R1 |
| Embeddings | See docs/embedding_model_comparison.md | - |

---

## Agent Team Architecture

### Development Agents (Claude Code Team)

These are the Claude Code agents that collaborate to build this system:

#### 1. Architect Agent
- **Role**: System design, architecture decisions, tech stack evaluation
- **Scope**: Overall system architecture, data flow design, API schema, database design
- **Files**: `plan.md`, `CLAUDE.md`, `docs/*.md`
- **Rules**:
  - Always consider scalability and cost implications
  - Document all architectural decisions with rationale
  - Evaluate trade-offs explicitly (speed vs accuracy, cost vs quality)

#### 2. Backend Agent
- **Role**: FastAPI development, API routing, middleware, auth
- **Scope**: `backend/api/`, `backend/main.py`, `backend/config/`, `backend/services/`
- **Rules**:
  - Follow FastAPI best practices (dependency injection, Pydantic models)
  - All endpoints must have proper error handling and validation
  - Use async/await for all I/O operations
  - Include OpenAPI docs for every endpoint
  - Rate limiting per user role

#### 3. RAG Agent
- **Role**: Vector database setup, embedding pipeline, retrieval, re-ranking
- **Scope**: `backend/rag/`, `backend/preprocessing/`, Qdrant configuration
- **Rules**:
  - Always use hybrid search (dense + sparse) for legal queries
  - Apply Reciprocal Rank Fusion (RRF) for merging results
  - Use cross-encoder re-ranking for final precision
  - Legal-aware chunking (respect section boundaries)
  - Every indexed document must have complete metadata payloads
  - Test retrieval quality with legal domain queries before deployment

#### 4. CrewAI Agent
- **Role**: Multi-agent system design, crew definitions, tool development
- **Scope**: `backend/agents/`
- **Rules**:
  - Each AI agent must have a clearly defined role and backstory
  - Use sequential process for crews (legal requires ordered reasoning)
  - All custom tools must handle errors gracefully
  - Citation Checker agent is MANDATORY in every crew pipeline
  - Never skip the verification step

#### 5. Frontend Agent
- **Role**: Next.js UI development, role-based dashboards
- **Scope**: `frontend/`
- **Rules**:
  - Role-aware UI (citizen sees different UI than lawyer)
  - Implement SSE streaming for real-time response display
  - Show verification status prominently on every response
  - Accessible design (WCAG 2.1 AA)
  - Mobile-responsive (many Indian users are mobile-first)

#### 6. Data Pipeline Agent
- **Role**: PDF preprocessing, data ingestion, scraping
- **Scope**: `backend/preprocessing/`, `data/`
- **Rules**:
  - Handle both text-based and scanned PDFs (OCR fallback)
  - Extract and preserve metadata (act name, section numbers, court, date)
  - Clean thoroughly: remove headers/footers, page numbers, watermarks
  - Validate extracted data before Qdrant ingestion
  - Batch processing with progress tracking

#### 7. Document Drafting Agent
- **Role**: Legal document template system, PDF generation
- **Scope**: `backend/document_drafting/`
- **Rules**:
  - Use hybrid approach: Jinja2 templates + LLM for legal language
  - All drafted documents must include a "DRAFT - NOT LEGAL ADVICE" disclaimer
  - Validate required fields before generation
  - Support bilingual output (English + user's preferred language)
  - Proper Indian legal document formatting

#### 8. QA & Testing Agent
- **Role**: Testing, quality assurance, legal accuracy validation
- **Scope**: `backend/tests/`, integration tests
- **Rules**:
  - Test citation accuracy: every section reference must be verifiable
  - Test hallucination detection: create adversarial test cases
  - Test role-based access: ensure citizens can't access lawyer-only features
  - Test multilingual: verify translations preserve legal meaning
  - Load testing: ensure system handles concurrent users

---

## AI System Agents (CrewAI Runtime Agents)

These are the AI agents that run in production to serve users:

### Agent 1: Query Analyst
- **Model**: Groq (Llama 3.3 70B) - fast classification
- **Purpose**: Classify, decompose, and expand user legal queries
- **Input**: Raw user query + user role
- **Output**: Classified query with legal domain, intent, entities, search parameters
- **Tools**: QueryClassifier, EntityExtractor, QueryExpander

### Agent 2: Retrieval Specialist
- **Model**: DeepSeek-Chat
- **Purpose**: Execute hybrid search and retrieve relevant legal documents
- **Input**: Classified query + search parameters
- **Output**: Top-K relevant document chunks with metadata and scores
- **Tools**: QdrantHybridSearch, MetadataFilter, CrossEncoderReranker

### Agent 3: Legal Reasoner
- **Model**: DeepSeek-R1 or Claude Sonnet (strong reasoning required)
- **Purpose**: Analyze retrieved documents using IRAC methodology
- **Input**: Retrieved document chunks + original query
- **Output**: Structured IRAC analysis with applicable sections, precedents, conclusion
- **Tools**: IRACAnalyzer, SectionExtractor, PrecedentMapper
- **Note**: Only activated for lawyer/advisor roles. Skipped for citizen simple queries.

### Agent 4: Citation Verifier
- **Model**: DeepSeek-Chat
- **Purpose**: Verify every citation, section reference, and factual claim
- **Input**: Generated response with citations
- **Output**: Verified response with confidence score and verification status
- **Tools**: SectionVerifier, CitationValidator, SourceCrossReference
- **CRITICAL RULE**: If a citation cannot be verified, REMOVE it. Never deliver unverified legal information.

### Agent 5: Response Formatter
- **Model**: Groq (Llama 3.3 70B) - fast formatting
- **Purpose**: Format response for the specific user role
- **Input**: Verified response + user role + preferred language
- **Output**: Formatted response with appropriate complexity level
- **Tools**: Simplifier, Formatter, ThesysVisual, SarvamTranslation

### Agent 6: Document Drafter
- **Model**: Claude Sonnet (high quality generation)
- **Purpose**: Generate legal document drafts from user-provided details
- **Input**: Document type + user-filled fields
- **Output**: Complete document draft in proper legal format
- **Tools**: TemplateEngine, PDFGenerator, FieldValidator

---

## Crew Configurations

### Layman Query Crew
```
Query Analyst → Retrieval Specialist → Response Formatter → Citation Verifier
```
- Sequential process
- Simplified output, step-by-step guidance
- Visual elements via Thesys API
- Multilingual support

### Lawyer Analysis Crew
```
Query Analyst → Retrieval Specialist → Legal Reasoner → Citation Verifier → Response Formatter
```
- Sequential process
- Full IRAC analysis
- Multiple case comparison
- Technical legal language

### Document Drafting Crew
```
Query Analyst → Document Drafter → Citation Verifier
```
- Sequential process
- Template-based generation
- Legal accuracy verification

### Corporate Advisor Crew
```
Query Analyst → Retrieval Specialist → Legal Reasoner → Citation Verifier → Response Formatter
```
- Focus on corporate, IT, compliance laws
- Risk assessment format

### Police Crew
```
Query Analyst → Retrieval Specialist → Citation Verifier → Response Formatter
```
- Focus on IPC, CrPC, criminal law
- Procedural guidance format

---

## Qdrant Collections

### `legal_documents` (Main Collection)
- **Vectors**: Dense (768d/1024d) + Sparse (BM25)
- **Payload Fields**: text, document_id, document_type, act_name, act_code, section_number, section_title, chapter, court, case_name, case_citation, judgment_date, judges, legal_domain, keywords, state, language, chunk_index, total_chunks, user_access_level, source_url
- **Indexes**: act_name, act_code, section_number, document_type, court, legal_domain, state, language, user_access_level, judgment_date (all keyword indexed)
- **Quantization**: Scalar INT8 for memory optimization

### `legal_sections` (Verification Collection)
- **Purpose**: Dedicated section-level storage for citation verification
- **Payload**: act_name, act_code, section_number, section_title, full_text, chapter, part, amendment_history, related_sections

### `document_templates` (Drafting Templates)
- **Purpose**: Store document templates and their schemas
- **Payload**: template_type, template_name, template_content, required_fields, optional_fields, jurisdiction, language

---

## Retrieval Pipeline

```
1. Query Expansion (LLM → legal synonyms)
2. Hybrid Search (Dense + Sparse in Qdrant)
3. Reciprocal Rank Fusion (RRF, k=60)
4. Cross-Encoder Re-ranking (ms-marco-MiniLM or legal-specific)
5. Role-based Filtering (user_access_level)
6. Citation Verification (every source checked)
```

---

## Critical Rules

### Legal Accuracy Rules
1. **NEVER** generate a section number that hasn't been retrieved from the database
2. **NEVER** cite a case that cannot be verified in the vector store
3. **ALWAYS** include source citations with every factual legal claim
4. **ALWAYS** run Citation Verifier before delivering any response
5. If confidence score < 0.5, return: *"I cannot provide a verified answer to this query. Please consult a qualified legal professional."*
6. Every response must display its verification status (Verified/Partially Verified/Unverified)

### Code Quality Rules
1. All Python code follows PEP 8 with type hints
2. All API endpoints have Pydantic request/response models
3. All database operations use async
4. Error handling: never expose internal errors to users
5. Logging: structured JSON logging for all agent actions
6. Tests: minimum 80% coverage for critical paths (retrieval, citation, drafting)

### Data Rules
1. No PII stored in vector database (strip before embedding)
2. All user data encrypted at rest
3. Query logs anonymized after 30 days
4. GDPR-like right to deletion implemented
5. Rate limiting enforced per user role

---

## API Base URL

```
Development: http://localhost:8000/api/v1
Production: https://api.neethiai.com/api/v1
```

## Key API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/auth/register` | User registration with role |
| POST | `/auth/login` | JWT authentication |
| POST | `/query/ask` | Main legal query (role-aware) |
| POST | `/query/ask/stream` | Streaming response (SSE) |
| POST | `/cases/search` | Search similar cases |
| POST | `/cases/analyze` | Deep IRAC case analysis |
| POST | `/documents/draft` | Generate document draft |
| POST | `/documents/draft/{id}/pdf` | Export draft as PDF |
| GET | `/sections/acts` | List all acts |
| GET | `/sections/acts/{id}/sections/{num}` | Get specific section |
| POST | `/resources/nearby` | Find nearby legal resources |
| POST | `/translate/text` | Translate response |
| POST | `/admin/ingest` | Ingest new legal documents |
| GET | `/admin/health` | System health check |

---

## File Structure

See `plan.md` Section 14 for complete project structure.

---

## References

- **Architecture Plan**: `plan.md`
- **Embedding Model Study**: `docs/embedding_model_comparison.md`
- **Tech Stack Index**: `docs/tech_stack_index.md`
- **Document Drafting Design**: `docs/document_drafting_design.md`
- **Qdrant Optimization Guide**: `qdrant-resource-optimization-guide.pdf`
- **Phase 1 Reports**: `Project Documents/Paralegal Agent V1.pdf`, `Project Documents/NeethiApp Final Report.pdf`
