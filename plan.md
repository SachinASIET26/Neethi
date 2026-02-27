# Neethi AI - Indian Legal Domain Agentic AI System
## Comprehensive Architecture Plan

> **Project**: Neethi AI - Agentic Legal Intelligence Platform for India
> **Version**: 2.0 (Phase 2 - Production Architecture)
> **Date**: February 2026
> **Stack**: CrewAI + FastAPI + Qdrant + Next.js/React

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Core Architecture](#2-core-architecture)
3. [Multi-Agent Team Design (CrewAI)](#3-multi-agent-team-design)
4. [FastAPI Routing Schema](#4-fastapi-routing-schema)
5. [Qdrant Vector Database Architecture](#5-qdrant-vector-database-architecture)
6. [PDF Preprocessing Pipeline](#6-pdf-preprocessing-pipeline)
7. [Retrieval & Ranking Pipeline](#7-retrieval--ranking-pipeline)
8. [Document Drafting System](#8-document-drafting-system)
9. [User Role-Based Access System](#9-user-role-based-access-system)
10. [Source Citation & Verification System](#10-source-citation--verification-system)
11. [Multilingual Support](#11-multilingual-support)
12. [Frontend Architecture](#12-frontend-architecture)
13. [Deployment Architecture](#13-deployment-architecture)
14. [Project Structure](#14-project-structure)

---

## 1. System Overview

### 1.1 Vision
An agentic AI system that democratizes access to Indian legal knowledge across all user segments - from layman citizens to practicing lawyers - with **legally grounded, citation-backed, hallucination-free** responses.

### 1.2 Core Principles
1. **"No answer is better than a wrong answer"** - Every response must be source-cited and double-checked
2. **Role-based intelligence** - Different depth and complexity per user type
3. **Hybrid retrieval** - Dense + Sparse vectors for maximum recall and precision
4. **Reciprocal Rank Fusion (RRF)** - Ensure retrieved chunks are grounded to the actual query
5. **Multi-agent orchestration** - Specialized agents for specialized tasks
6. **Multilingual first** - Hindi + English + Regional languages via Sarvam AI

### 1.3 User Segments

| User Type | Access Level | Response Style | Key Features |
|-----------|-------------|----------------|--------------|
| **Citizen/Layman** | Basic legal info, guidance | Simple, jargon-free, step-by-step | Document drafting, multilingual, nearby resources |
| **Lawyer** | Full case analysis, precedents | Technical, structured (IRAC format) | Case comparison, section extraction, judgment analysis |
| **Legal Advisor (Corporate)** | Corporate/IT/Compliance laws | Professional, compliance-focused | Regulatory mapping, risk assessment |
| **Police** | Criminal law, procedures | Procedural, section-focused | IPC/CrPC sections, FIR assistance |

---

## 2. Core Architecture

### 2.1 High-Level System Architecture

```
                                    ┌─────────────────────────┐
                                    │    Next.js Frontend     │
                                    │  (Role-based Dashboard) │
                                    └────────────┬────────────┘
                                                 │ HTTPS/WSS
                                                 ▼
                              ┌──────────────────────────────────┐
                              │         API Gateway Layer        │
                              │    (FastAPI + Auth Middleware)    │
                              │   Rate Limiting | JWT Auth       │
                              └──────────────────┬───────────────┘
                                                 │
                    ┌────────────────────────────┼────────────────────────────┐
                    ▼                            ▼                            ▼
          ┌─────────────────┐        ┌───────────────────┐        ┌──────────────────┐
          │  Query Router   │        │  Document Drafter  │        │  Resource Locator │
          │  (Role-Aware)   │        │    (Template+LLM)  │        │   (SERP API)     │
          └────────┬────────┘        └───────────────────┘        └──────────────────┘
                   │
                   ▼
    ┌──────────────────────────────┐
    │     CrewAI Orchestrator      │
    │   (Agent Team Management)    │
    └──────────────┬───────────────┘
                   │
    ┌──────────────┼──────────────────────────────────────┐
    ▼              ▼              ▼              ▼        ▼
┌────────┐  ┌──────────┐  ┌──────────┐  ┌────────┐  ┌────────────┐
│Query   │  │Retrieval │  │Legal     │  │Citation│  │Response    │
│Analyst │  │Specialist│  │Reasoner  │  │Checker │  │Formatter   │
│Agent   │  │Agent     │  │Agent     │  │Agent   │  │Agent       │
└────────┘  └────┬─────┘  └──────────┘  └────────┘  └────────────┘
                 │
         ┌───────┼───────┐
         ▼       ▼       ▼
    ┌────────┐┌──────┐┌──────┐
    │Qdrant  ││Sparse││Re-   │
    │Dense   ││Index ││Ranker│
    │Vectors ││(BM25)││      │
    └────────┘└──────┘└──────┘
```

### 2.2 Data Flow

```
User Query → Auth/Role Detection → Query Router
  → [Layman Path]  → Simplifier Agent → Retrieval → Simple Response + Guidance
  → [Lawyer Path]  → Legal Analyst Agent → Deep Retrieval → IRAC Analysis → Structured Report
  → [Advisor Path] → Compliance Agent → Corporate Law Retrieval → Risk Assessment
  → [Police Path]  → Section Finder Agent → IPC/CrPC Retrieval → Procedural Guide

All Paths → Citation Checker → Source Verification → Response Formatter → User
```

---

## 3. Multi-Agent Team Design (CrewAI)

### 3.1 Agent Definitions

#### Agent 1: Query Analyst Agent
```python
query_analyst = Agent(
    role="Legal Query Analyst",
    goal="Understand, classify, and decompose user queries into actionable legal search parameters",
    backstory="""You are an expert legal query analyst who understands Indian law terminology
    and can translate layman questions into precise legal concepts. You determine the relevant
    area of law (civil, criminal, corporate, constitutional, family, property, etc.), identify
    key legal entities, and formulate optimal search queries.""",
    tools=[query_classifier_tool, entity_extractor_tool, query_expansion_tool],
    llm=llm_config,  # DeepSeek-R1 or Claude for reasoning
    verbose=True,
    memory=True
)
```
**Responsibilities**:
- Classify query by legal domain (IPC, CrPC, CPC, Constitution, Family Law, Property Law, Corporate Law, IT Act, etc.)
- Detect user intent (information seeking, document drafting, case analysis, section lookup)
- Extract legal entities (section numbers, act names, court names, party names)
- Expand query with legal synonyms and related terms
- Determine required depth based on user role

#### Agent 2: Retrieval Specialist Agent
```python
retrieval_specialist = Agent(
    role="Legal Document Retrieval Specialist",
    goal="Retrieve the most relevant legal documents, sections, and case precedents from the vector database",
    backstory="""You are a master legal researcher with deep knowledge of Indian legal databases.
    You use hybrid search (dense + sparse) with reciprocal rank fusion to find the most relevant
    legal documents. You understand legal document structure and can filter by jurisdiction,
    court hierarchy, date relevance, and case type.""",
    tools=[qdrant_dense_search, qdrant_sparse_search, hybrid_search_tool, metadata_filter_tool],
    llm=llm_config,
    verbose=True,
    memory=True
)
```
**Responsibilities**:
- Execute hybrid search (dense embeddings + BM25 sparse)
- Apply Reciprocal Rank Fusion (RRF) to merge results
- Filter by metadata (court, date, jurisdiction, act)
- Re-rank results using cross-encoder
- Return top-K chunks with source metadata
- Handle multi-document retrieval for case comparison

#### Agent 3: Legal Reasoner Agent
```python
legal_reasoner = Agent(
    role="Legal Reasoning & Analysis Expert",
    goal="Analyze retrieved legal documents and provide structured legal reasoning using IRAC methodology",
    backstory="""You are a senior legal analyst specializing in Indian law. Given retrieved legal
    documents and case judgments, you extract facts, identify applicable rules/sections, apply
    legal reasoning, and draw conclusions. You follow the IRAC (Issue, Rule, Application, Conclusion)
    framework for structured analysis. You identify precedents, distinguish cases, and note
    conflicting judgments.""",
    tools=[irac_analyzer_tool, section_extractor_tool, precedent_mapper_tool],
    llm=reasoning_llm,  # Stronger model for reasoning (Claude/GPT-4/DeepSeek-R1)
    verbose=True,
    memory=True
)
```
**Responsibilities**:
- IRAC analysis (Issue, Rule, Application, Conclusion)
- Extract applicable sections and subsections
- Identify precedents and their relevance
- Compare multiple case judgments
- Summarize court verdicts
- Flag conflicting judgments across courts
- Determine hierarchy of precedents (SC > HC > District)

#### Agent 4: Citation Verification Agent
```python
citation_checker = Agent(
    role="Legal Citation & Accuracy Verifier",
    goal="Verify every legal citation, section reference, and factual claim in the response before delivery",
    backstory="""You are a meticulous legal fact-checker. Your job is to ensure ZERO hallucinations.
    Every section number must exist in the cited act. Every case reference must be real. Every
    legal principle must be accurately stated. You cross-reference claims against the source
    documents. If something cannot be verified, you flag it for removal rather than letting
    incorrect information reach the user.""",
    tools=[section_verifier_tool, citation_validator_tool, source_cross_reference_tool],
    llm=llm_config,
    verbose=True,
    memory=True
)
```
**Responsibilities**:
- Verify every section number against actual acts in the database
- Cross-reference case citations with source documents
- Check if legal principles are accurately stated
- Flag unverifiable claims for removal
- Add source citations with exact document references
- Ensure no hallucinated section numbers or case names
- **CRITICAL**: If verification fails, return "Information could not be verified" rather than potentially wrong info

#### Agent 5: Response Formatter Agent
```python
response_formatter = Agent(
    role="Legal Response Formatter & Simplifier",
    goal="Format the verified legal response according to the user's role and comprehension level",
    backstory="""You are an expert legal communicator who adapts complex legal information to
    the audience. For laypeople, you use simple language with step-by-step guidance. For lawyers,
    you provide structured technical analysis. You ensure every response includes source citations
    and actionable next steps.""",
    tools=[simplifier_tool, formatter_tool, thesys_visual_tool, translation_tool],
    llm=llm_config,
    verbose=True,
    memory=True
)
```
**Responsibilities**:
- Adapt language complexity to user role
- For Layman: Simple language, step-by-step guidance, visual elements (Thesys)
- For Lawyer: IRAC format, structured tables, section references
- For Advisor: Compliance checklist, risk matrix
- For Police: Procedural steps, applicable sections
- Add multilingual translation via Sarvam AI
- Include "What to do next" actionable steps
- Attach source citations in standardized format

#### Agent 6: Document Drafting Agent
```python
document_drafter = Agent(
    role="Legal Document Drafting Specialist",
    goal="Generate accurate first-copy drafts of legal documents based on user-provided details",
    backstory="""You are an expert legal document drafter familiar with Indian legal document
    formats. You draft FIRs, RTI applications, complaint letters, legal notices, affidavits,
    and other standard legal documents. You use proper legal language, correct formatting,
    and ensure all mandatory fields are filled.""",
    tools=[template_engine_tool, pdf_generator_tool, field_validator_tool],
    llm=llm_config,
    verbose=True,
    memory=True
)
```

### 3.2 Crew Configurations

#### Crew 1: Layman Query Crew (Sequential)
```python
layman_crew = Crew(
    agents=[query_analyst, retrieval_specialist, response_formatter, citation_checker],
    tasks=[
        Task(description="Analyze and classify the user query", agent=query_analyst),
        Task(description="Retrieve relevant legal information", agent=retrieval_specialist),
        Task(description="Format response in simple, accessible language with visual aids", agent=response_formatter),
        Task(description="Verify all citations and legal references", agent=citation_checker),
    ],
    process=Process.sequential,
    memory=True,
    verbose=True
)
```

#### Crew 2: Lawyer Analysis Crew (Sequential)
```python
lawyer_crew = Crew(
    agents=[query_analyst, retrieval_specialist, legal_reasoner, citation_checker, response_formatter],
    tasks=[
        Task(description="Analyze the legal query and identify case parameters", agent=query_analyst),
        Task(description="Retrieve similar cases, applicable sections, and precedents", agent=retrieval_specialist),
        Task(description="Perform IRAC analysis on retrieved documents", agent=legal_reasoner),
        Task(description="Verify all citations, sections, and legal claims", agent=citation_checker),
        Task(description="Format as structured legal analysis report", agent=response_formatter),
    ],
    process=Process.sequential,
    memory=True,
    verbose=True
)
```

#### Crew 3: Document Drafting Crew (Sequential)
```python
drafting_crew = Crew(
    agents=[query_analyst, document_drafter, citation_checker],
    tasks=[
        Task(description="Analyze document type and extract required fields", agent=query_analyst),
        Task(description="Draft the legal document using templates and LLM", agent=document_drafter),
        Task(description="Verify legal accuracy of drafted document", agent=citation_checker),
    ],
    process=Process.sequential,
    memory=True,
    verbose=True
)
```

#### Crew 4: Corporate Advisor Crew (Sequential)
```python
advisor_crew = Crew(
    agents=[query_analyst, retrieval_specialist, legal_reasoner, citation_checker, response_formatter],
    tasks=[
        Task(description="Analyze corporate/compliance query", agent=query_analyst),
        Task(description="Retrieve applicable corporate laws and regulations", agent=retrieval_specialist),
        Task(description="Analyze compliance requirements and risks", agent=legal_reasoner),
        Task(description="Verify all regulatory references", agent=citation_checker),
        Task(description="Format as compliance advisory report", agent=response_formatter),
    ],
    process=Process.sequential,
    memory=True,
    verbose=True
)
```

### 3.3 Custom CrewAI Tools

```python
# Tool 1: Qdrant Hybrid Search Tool
class QdrantHybridSearchTool(BaseTool):
    name: str = "Legal Document Search"
    description: str = "Search Indian legal documents using hybrid (dense+sparse) retrieval with metadata filtering"

    def _run(self, query: str, filters: dict = None, top_k: int = 10) -> str:
        # Dense search with embedding model
        dense_results = qdrant_client.search(
            collection_name="legal_documents",
            query_vector=("dense", embed_model.encode(query)),
            limit=top_k * 2,
            query_filter=build_filter(filters) if filters else None,
        )
        # Sparse search with BM25
        sparse_results = qdrant_client.search(
            collection_name="legal_documents",
            query_vector=("sparse", sparse_encoder.encode(query)),
            limit=top_k * 2,
            query_filter=build_filter(filters) if filters else None,
        )
        # Reciprocal Rank Fusion
        fused = reciprocal_rank_fusion(dense_results, sparse_results, k=60)
        # Re-rank with cross-encoder
        reranked = cross_encoder_rerank(query, fused[:top_k * 2])
        return format_results(reranked[:top_k])

# Tool 2: Section Verifier Tool
class SectionVerifierTool(BaseTool):
    name: str = "Legal Section Verifier"
    description: str = "Verify if a cited section number exists in the specified act"

    def _run(self, act_name: str, section_number: str) -> str:
        result = qdrant_client.scroll(
            collection_name="legal_sections",
            scroll_filter=Filter(must=[
                FieldCondition(key="act_name", match=MatchValue(value=act_name)),
                FieldCondition(key="section_number", match=MatchValue(value=section_number)),
            ]),
            limit=1
        )
        if result[0]:
            return f"VERIFIED: Section {section_number} of {act_name} exists. Content: {result[0][0].payload['text'][:500]}"
        return f"NOT FOUND: Section {section_number} of {act_name} could not be verified in the database."

# Tool 3: Query Classification Tool
class QueryClassifierTool(BaseTool):
    name: str = "Legal Query Classifier"
    description: str = "Classify a legal query by domain, intent, and complexity"

    def _run(self, query: str) -> str:
        classification = llm.invoke(CLASSIFICATION_PROMPT.format(query=query))
        return classification

# Tool 4: SERP Resource Locator Tool
class ResourceLocatorTool(BaseTool):
    name: str = "Legal Resource Locator"
    description: str = "Find nearby lawyers, legal aid centers, courts, and police stations"

    def _run(self, location: str, resource_type: str) -> str:
        results = serp_api.search(f"{resource_type} near {location} India")
        return format_serp_results(results)

# Tool 5: Sarvam Translation Tool
class SarvamTranslationTool(BaseTool):
    name: str = "Indian Language Translator"
    description: str = "Translate legal responses to Indian regional languages using Sarvam AI"

    def _run(self, text: str, target_language: str) -> str:
        translated = sarvam_client.translate(
            text=text,
            source_language="en",
            target_language=target_language
        )
        return translated
```

---

## 4. FastAPI Routing Schema

### 4.1 API Structure

```
/api/v1/
├── /auth/
│   ├── POST   /register          # User registration
│   ├── POST   /login             # JWT login
│   ├── POST   /refresh           # Token refresh
│   └── GET    /me                # Current user profile
│
├── /query/
│   ├── POST   /ask               # Main query endpoint (role-aware)
│   ├── POST   /ask/stream        # Streaming response (SSE)
│   ├── GET    /history           # Query history
│   └── GET    /history/{id}     # Specific query detail
│
├── /cases/
│   ├── POST   /search            # Search similar cases
│   ├── GET    /{case_id}         # Get case details
│   ├── POST   /compare           # Compare multiple cases
│   └── POST   /analyze           # Deep IRAC analysis
│
├── /documents/
│   ├── GET    /templates         # List available templates
│   ├── GET    /templates/{type}  # Get template schema
│   ├── POST   /draft             # Generate document draft
│   ├── PUT    /draft/{id}        # Update draft
│   ├── GET    /draft/{id}        # Get draft
│   ├── POST   /draft/{id}/pdf    # Export draft as PDF
│   └── GET    /drafts            # List user's drafts
│
├── /sections/
│   ├── GET    /acts              # List all acts
│   ├── GET    /acts/{act_id}     # Get act details
│   ├── GET    /acts/{act_id}/sections          # List sections
│   ├── GET    /acts/{act_id}/sections/{num}    # Get specific section
│   └── POST   /search            # Search sections by keyword
│
├── /resources/
│   ├── POST   /nearby            # Find nearby legal resources
│   ├── GET    /lawyers           # Search lawyers
│   └── GET    /legal-aid         # Legal aid centers
│
├── /translate/
│   ├── POST   /text              # Translate response text
│   ├── GET    /languages         # Supported languages
│   └── POST   /voice             # Voice input (STT)
│
├── /admin/
│   ├── POST   /ingest            # Ingest new legal documents
│   ├── GET    /collections       # Qdrant collection stats
│   ├── POST   /reindex           # Reindex collection
│   └── GET    /health            # System health check
│
└── /feedback/
    ├── POST   /report            # Report incorrect response
    └── POST   /rate              # Rate response quality
```

### 4.2 Core API Models (Pydantic Schemas)

```python
# ============ Auth Models ============
class UserRegister(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    full_name: str
    role: UserRole  # CITIZEN, LAWYER, ADVISOR, POLICE
    phone: Optional[str]
    preferred_language: str = "en"
    jurisdiction: Optional[str]  # State/District

class UserRole(str, Enum):
    CITIZEN = "citizen"
    LAWYER = "lawyer"
    LEGAL_ADVISOR = "legal_advisor"
    POLICE = "police"
    ADMIN = "admin"

# ============ Query Models ============
class LegalQuery(BaseModel):
    query: str = Field(..., min_length=5, max_length=5000)
    language: str = "en"
    context: Optional[str] = None  # Additional context
    filters: Optional[QueryFilters] = None

class QueryFilters(BaseModel):
    legal_domain: Optional[str] = None  # criminal, civil, corporate, etc.
    court: Optional[str] = None  # supreme_court, high_court, district
    state: Optional[str] = None
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    act_name: Optional[str] = None

class LegalResponse(BaseModel):
    query_id: str
    answer: str
    sources: List[SourceCitation]
    applicable_sections: List[SectionReference]
    confidence_score: float  # 0-1
    verification_status: VerificationStatus  # VERIFIED, PARTIALLY_VERIFIED, UNVERIFIED
    suggested_actions: List[str]
    related_queries: List[str]
    response_metadata: ResponseMetadata

class SourceCitation(BaseModel):
    document_id: str
    title: str
    source_type: str  # act, case_judgment, notification, circular
    act_name: Optional[str]
    section: Optional[str]
    court: Optional[str]
    date: Optional[str]
    relevance_score: float
    excerpt: str  # Relevant excerpt from source
    url: Optional[str]  # Link to original document if available

class VerificationStatus(str, Enum):
    VERIFIED = "verified"              # All citations cross-checked
    PARTIALLY_VERIFIED = "partially"   # Some citations verified
    UNVERIFIED = "unverified"          # Could not verify - flagged

# ============ Case Analysis Models ============
class CaseAnalysisRequest(BaseModel):
    case_description: str
    legal_domain: str
    jurisdiction: Optional[str]
    specific_questions: Optional[List[str]]

class CaseAnalysisResponse(BaseModel):
    case_id: str
    irac_analysis: IRACAnalysis
    applicable_sections: List[SectionReference]
    similar_cases: List[SimilarCase]
    precedents: List[Precedent]
    summary: str
    sources: List[SourceCitation]
    verification_status: VerificationStatus

class IRACAnalysis(BaseModel):
    issue: str          # Legal issue identified
    rule: str           # Applicable legal rules/sections
    application: str    # How rules apply to the case
    conclusion: str     # Legal conclusion/recommendation

class SimilarCase(BaseModel):
    case_name: str
    citation: str
    court: str
    date: str
    similarity_score: float
    key_facts: str
    verdict: str
    distinguishing_factors: Optional[str]

# ============ Document Drafting Models ============
class DraftRequest(BaseModel):
    document_type: DocumentType
    fields: Dict[str, Any]  # Dynamic fields based on template
    language: str = "en"

class DocumentType(str, Enum):
    FIR = "fir"
    RTI = "rti_application"
    COMPLAINT_LETTER = "complaint_letter"
    LEGAL_NOTICE = "legal_notice"
    AFFIDAVIT = "affidavit"
    POWER_OF_ATTORNEY = "power_of_attorney"
    BAIL_APPLICATION = "bail_application"
    WRITTEN_STATEMENT = "written_statement"
    DEMAND_NOTICE = "demand_notice"
    RENT_AGREEMENT = "rent_agreement"

class DraftResponse(BaseModel):
    draft_id: str
    document_type: DocumentType
    content: str  # Rendered document content
    status: str  # "draft", "reviewed", "finalized"
    created_at: datetime
    metadata: Dict[str, Any]

# ============ Resource Locator Models ============
class ResourceSearchRequest(BaseModel):
    location: str  # City or coordinates
    resource_type: ResourceType
    specialization: Optional[str]
    radius_km: int = 10

class ResourceType(str, Enum):
    LAWYER = "lawyer"
    LEGAL_AID_CENTER = "legal_aid_center"
    COURT = "court"
    POLICE_STATION = "police_station"
    NGO = "ngo"
    NOTARY = "notary"
```

### 4.3 FastAPI Application Structure

```python
# main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="Neethi AI - Legal Intelligence API",
    version="2.0.0",
    description="Agentic AI-powered Indian Legal Domain API"
)

# Middleware
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"])
app.add_middleware(RateLimitMiddleware, requests_per_minute=30)

# Routers
app.include_router(auth_router, prefix="/api/v1/auth", tags=["Authentication"])
app.include_router(query_router, prefix="/api/v1/query", tags=["Legal Queries"])
app.include_router(cases_router, prefix="/api/v1/cases", tags=["Case Analysis"])
app.include_router(documents_router, prefix="/api/v1/documents", tags=["Document Drafting"])
app.include_router(sections_router, prefix="/api/v1/sections", tags=["Legal Sections"])
app.include_router(resources_router, prefix="/api/v1/resources", tags=["Resource Locator"])
app.include_router(translate_router, prefix="/api/v1/translate", tags=["Translation"])
app.include_router(admin_router, prefix="/api/v1/admin", tags=["Admin"])
app.include_router(feedback_router, prefix="/api/v1/feedback", tags=["Feedback"])

# SSE Streaming endpoint
@app.post("/api/v1/query/ask/stream")
async def stream_legal_query(query: LegalQuery, user: User = Depends(get_current_user)):
    """Stream legal response using Server-Sent Events for real-time UI updates"""
    async def event_generator():
        async for chunk in crew_orchestrator.stream_response(query, user.role):
            yield {"event": "chunk", "data": json.dumps({"text": chunk.text, "stage": chunk.stage})}
        yield {"event": "done", "data": json.dumps({"status": "complete"})}
    return EventSourceResponse(event_generator())
```

---

## 5. Qdrant Vector Database Architecture

### 5.1 Collection Design

```
Qdrant Collections:
├── legal_documents          # Main collection - All legal text chunks
│   ├── Dense Vector: "dense" (768d or 1024d - based on embedding model)
│   ├── Sparse Vector: "sparse" (BM25/SPLADE)
│   └── Payload:
│       ├── text: str                  # Chunk text
│       ├── document_id: str           # Parent document ID
│       ├── document_type: str         # act, case_judgment, notification, circular, amendment
│       ├── act_name: str              # e.g., "Indian Penal Code"
│       ├── act_code: str              # e.g., "IPC", "CrPC", "CPC"
│       ├── section_number: str        # e.g., "302", "420"
│       ├── section_title: str         # e.g., "Punishment for murder"
│       ├── chapter: str               # Chapter in the act
│       ├── court: str                 # supreme_court, high_court_{state}, district
│       ├── case_name: str             # e.g., "State of Maharashtra v. XYZ"
│       ├── case_citation: str         # e.g., "AIR 2020 SC 1234"
│       ├── judgment_date: str         # ISO date
│       ├── judges: list[str]          # Bench composition
│       ├── legal_domain: str          # criminal, civil, corporate, family, property, constitutional
│       ├── keywords: list[str]        # Auto-extracted keywords
│       ├── state: str                 # Jurisdiction state
│       ├── language: str              # en, hi, ta, te, etc.
│       ├── chunk_index: int           # Position in document
│       ├── total_chunks: int          # Total chunks in document
│       ├── user_access_level: str     # citizen, lawyer, advisor, police, all
│       └── source_url: str            # Original source URL
│
├── legal_sections           # Dedicated section-level collection for verification
│   ├── Dense Vector: "dense"
│   └── Payload:
│       ├── act_name: str
│       ├── act_code: str
│       ├── section_number: str
│       ├── section_title: str
│       ├── full_text: str
│       ├── chapter: str
│       ├── part: str
│       ├── amendment_history: list[str]
│       └── related_sections: list[str]
│
└── document_templates       # Templates for document drafting
    ├── Dense Vector: "dense"
    └── Payload:
        ├── template_type: str
        ├── template_name: str
        ├── template_content: str
        ├── required_fields: list[str]
        ├── optional_fields: list[str]
        ├── jurisdiction: str
        └── language: str
```

### 5.2 Collection Configuration

```python
from qdrant_client import QdrantClient
from qdrant_client.models import (
    VectorParams, SparseVectorParams, Distance,
    HnswConfigDiff, OptimizersConfigDiff,
    PayloadSchemaType, TextIndexParams, TokenizerType
)

client = QdrantClient(url="http://localhost:6333")

# Main legal documents collection
client.create_collection(
    collection_name="legal_documents",
    vectors_config={
        "dense": VectorParams(
            size=768,  # Depends on embedding model choice
            distance=Distance.COSINE,
            hnsw_config=HnswConfigDiff(
                m=32,              # Higher for better recall (legal accuracy critical)
                ef_construct=256,  # Higher for better index quality
            ),
            quantization_config=ScalarQuantization(
                scalar=ScalarQuantizationConfig(
                    type=ScalarType.INT8,
                    quantile=0.99,
                    always_ram=True,  # Keep quantized vectors in RAM
                ),
            ),
        ),
    },
    sparse_vectors_config={
        "sparse": SparseVectorParams(
            modifier=Modifier.IDF,  # TF-IDF weighting for BM25-like scoring
        ),
    },
    optimizers_config=OptimizersConfigDiff(
        indexing_threshold=20000,  # Index after 20k points
    ),
)

# Create payload indexes for fast filtering
for field, schema_type in [
    ("act_name", PayloadSchemaType.KEYWORD),
    ("act_code", PayloadSchemaType.KEYWORD),
    ("section_number", PayloadSchemaType.KEYWORD),
    ("document_type", PayloadSchemaType.KEYWORD),
    ("court", PayloadSchemaType.KEYWORD),
    ("legal_domain", PayloadSchemaType.KEYWORD),
    ("state", PayloadSchemaType.KEYWORD),
    ("language", PayloadSchemaType.KEYWORD),
    ("user_access_level", PayloadSchemaType.KEYWORD),
    ("judgment_date", PayloadSchemaType.DATETIME),
]:
    client.create_payload_index(
        collection_name="legal_documents",
        field_name=field,
        field_schema=schema_type,
    )

# Full-text index on text field for keyword search fallback
client.create_payload_index(
    collection_name="legal_documents",
    field_name="text",
    field_schema=TextIndexParams(
        type="text",
        tokenizer=TokenizerType.WORD,
        min_token_len=2,
        max_token_len=20,
        lowercase=True,
    ),
)
```

### 5.3 Hybrid Search Implementation

```python
from qdrant_client.models import (
    SearchRequest, NamedVector, NamedSparseVector,
    Filter, FieldCondition, MatchValue, Prefetch, FusionQuery, Fusion
)

async def hybrid_legal_search(
    query: str,
    filters: Optional[QueryFilters] = None,
    top_k: int = 10,
    user_role: str = "citizen"
) -> List[SearchResult]:
    """
    Hybrid search with Reciprocal Rank Fusion (RRF)
    Uses Qdrant's native prefetch + fusion for optimal performance
    """

    # Build filter conditions
    filter_conditions = []
    if filters:
        if filters.legal_domain:
            filter_conditions.append(
                FieldCondition(key="legal_domain", match=MatchValue(value=filters.legal_domain))
            )
        if filters.court:
            filter_conditions.append(
                FieldCondition(key="court", match=MatchValue(value=filters.court))
            )
        if filters.act_name:
            filter_conditions.append(
                FieldCondition(key="act_name", match=MatchValue(value=filters.act_name))
            )
        if filters.state:
            filter_conditions.append(
                FieldCondition(key="state", match=MatchValue(value=filters.state))
            )

    qdrant_filter = Filter(must=filter_conditions) if filter_conditions else None

    # Encode query
    dense_vector = embedding_model.encode(query)
    sparse_vector = sparse_encoder.encode(query)  # BM25 or SPLADE

    # Hybrid search with RRF using Qdrant's native query API
    results = client.query_points(
        collection_name="legal_documents",
        prefetch=[
            # Dense retrieval
            Prefetch(
                query=dense_vector,
                using="dense",
                limit=top_k * 3,
                filter=qdrant_filter,
            ),
            # Sparse retrieval
            Prefetch(
                query=sparse_vector,
                using="sparse",
                limit=top_k * 3,
                filter=qdrant_filter,
            ),
        ],
        query=FusionQuery(fusion=Fusion.RRF),  # Reciprocal Rank Fusion
        limit=top_k * 2,  # Get more for re-ranking
    )

    # Re-rank with cross-encoder for maximum precision
    reranked = cross_encoder_rerank(
        query=query,
        documents=[r.payload["text"] for r in results.points],
        point_ids=[r.id for r in results.points],
        top_k=top_k
    )

    return reranked


def cross_encoder_rerank(query: str, documents: List[str], point_ids: List[str], top_k: int) -> List[dict]:
    """Re-rank using a cross-encoder for maximum relevance precision"""
    from sentence_transformers import CrossEncoder

    model = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-12-v2")  # or legal-specific
    pairs = [(query, doc) for doc in documents]
    scores = model.predict(pairs)

    ranked = sorted(zip(point_ids, documents, scores), key=lambda x: x[2], reverse=True)
    return [{"id": pid, "text": doc, "score": score} for pid, doc, score in ranked[:top_k]]
```

---

## 6. PDF Preprocessing Pipeline

### 6.1 Pipeline Architecture

```
Legal PDF → Text Extraction → Cleaning → Structure Detection → Chunking → Embedding → Qdrant
                                              │
                                    ┌─────────┼─────────┐
                                    ▼         ▼         ▼
                               Act/Section  Case     Notification
                               Parser      Judgment   Parser
                                           Parser
```

### 6.2 Implementation

```python
# preprocessing/pipeline.py

class LegalPDFPipeline:
    """End-to-end pipeline for processing Indian legal PDFs into Qdrant"""

    def __init__(self, qdrant_client, embedding_model, sparse_encoder):
        self.client = qdrant_client
        self.embed_model = embedding_model
        self.sparse_encoder = sparse_encoder
        self.cleaners = [
            HeaderFooterRemover(),
            PageNumberRemover(),
            WatermarkRemover(),
            UnicodeNormalizer(),
            WhitespaceNormalizer(),
            LegalAbbreviationExpander(),
        ]
        self.parsers = {
            "act": ActSectionParser(),
            "judgment": CaseJudgmentParser(),
            "notification": NotificationParser(),
        }

    async def process_pdf(self, pdf_path: str, doc_type: str, metadata: dict) -> int:
        """Process a single legal PDF and ingest into Qdrant"""

        # Step 1: Extract text
        raw_text = self.extract_text(pdf_path)

        # Step 2: Clean text
        cleaned_text = self.clean_text(raw_text)

        # Step 3: Detect structure and parse
        parser = self.parsers.get(doc_type, self.parsers["act"])
        structured_sections = parser.parse(cleaned_text)

        # Step 4: Chunk with overlap
        chunks = self.chunk_sections(structured_sections, chunk_size=512, overlap=64)

        # Step 5: Generate embeddings (batch)
        dense_vectors = self.embed_model.encode([c.text for c in chunks], batch_size=32)
        sparse_vectors = [self.sparse_encoder.encode(c.text) for c in chunks]

        # Step 6: Prepare points with payloads
        points = []
        for i, (chunk, dense_vec, sparse_vec) in enumerate(zip(chunks, dense_vectors, sparse_vectors)):
            point = PointStruct(
                id=str(uuid4()),
                vector={
                    "dense": dense_vec.tolist(),
                    "sparse": sparse_vec,
                },
                payload={
                    "text": chunk.text,
                    "document_id": metadata.get("document_id", str(uuid4())),
                    "document_type": doc_type,
                    "act_name": chunk.metadata.get("act_name", metadata.get("act_name", "")),
                    "act_code": chunk.metadata.get("act_code", metadata.get("act_code", "")),
                    "section_number": chunk.metadata.get("section_number", ""),
                    "section_title": chunk.metadata.get("section_title", ""),
                    "chapter": chunk.metadata.get("chapter", ""),
                    "court": metadata.get("court", ""),
                    "case_name": metadata.get("case_name", ""),
                    "case_citation": metadata.get("case_citation", ""),
                    "judgment_date": metadata.get("judgment_date", ""),
                    "judges": metadata.get("judges", []),
                    "legal_domain": metadata.get("legal_domain", "general"),
                    "keywords": chunk.metadata.get("keywords", []),
                    "state": metadata.get("state", ""),
                    "language": metadata.get("language", "en"),
                    "chunk_index": i,
                    "total_chunks": len(chunks),
                    "user_access_level": metadata.get("access_level", "all"),
                    "source_url": metadata.get("source_url", ""),
                }
            )
            points.append(point)

        # Step 7: Batch upsert to Qdrant
        BATCH_SIZE = 100
        for batch_start in range(0, len(points), BATCH_SIZE):
            batch = points[batch_start:batch_start + BATCH_SIZE]
            self.client.upsert(
                collection_name="legal_documents",
                points=batch,
            )

        return len(points)

    def extract_text(self, pdf_path: str) -> str:
        """Extract text from PDF using PyMuPDF with fallback to OCR"""
        import fitz
        doc = fitz.open(pdf_path)
        text_parts = []
        for page in doc:
            text = page.get_text("text")
            if len(text.strip()) < 50:  # Likely scanned page
                # Fallback to OCR (Tesseract or EasyOCR)
                text = self.ocr_page(page)
            text_parts.append(text)
        return "\n\n".join(text_parts)

    def clean_text(self, text: str) -> str:
        """Apply all cleaners sequentially"""
        for cleaner in self.cleaners:
            text = cleaner.clean(text)
        return text

    def chunk_sections(self, sections, chunk_size=512, overlap=64):
        """
        Legal-aware chunking:
        - Respect section boundaries
        - If section > chunk_size, split with overlap
        - Preserve section metadata in each chunk
        """
        chunks = []
        for section in sections:
            text = section.text
            if len(text.split()) <= chunk_size:
                chunks.append(Chunk(text=text, metadata=section.metadata))
            else:
                # Split long sections with overlap
                words = text.split()
                for start in range(0, len(words), chunk_size - overlap):
                    chunk_words = words[start:start + chunk_size]
                    chunk_text = " ".join(chunk_words)
                    chunks.append(Chunk(text=chunk_text, metadata=section.metadata))
        return chunks


class ActSectionParser:
    """Parse Indian legal acts into structured sections"""

    SECTION_PATTERN = re.compile(
        r'(?:Section|Sec\.?)\s+(\d+[A-Za-z]*)\s*[.:\-—]\s*(.*?)(?=(?:Section|Sec\.?)\s+\d|$)',
        re.DOTALL | re.IGNORECASE
    )
    CHAPTER_PATTERN = re.compile(
        r'(?:CHAPTER|Chapter)\s+([IVXLCDM]+|\d+)\s*[.:\-—]?\s*(.*?)(?=\n)',
        re.IGNORECASE
    )

    def parse(self, text: str) -> List[StructuredSection]:
        sections = []
        current_chapter = ""

        # Extract chapters
        chapters = {m.start(): (m.group(1), m.group(2).strip())
                    for m in self.CHAPTER_PATTERN.finditer(text)}

        # Extract sections
        for match in self.SECTION_PATTERN.finditer(text):
            section_num = match.group(1)
            section_text = match.group(2).strip()

            # Find which chapter this section belongs to
            for pos, (ch_num, ch_title) in sorted(chapters.items()):
                if pos < match.start():
                    current_chapter = f"Chapter {ch_num}: {ch_title}"

            sections.append(StructuredSection(
                text=f"Section {section_num}: {section_text}",
                metadata={
                    "section_number": section_num,
                    "section_title": section_text[:100],
                    "chapter": current_chapter,
                    "keywords": extract_legal_keywords(section_text),
                }
            ))

        return sections


class CaseJudgmentParser:
    """Parse Indian court judgments into structured sections"""

    def parse(self, text: str) -> List[StructuredSection]:
        sections = []

        # Extract key parts of judgment
        parts = {
            "header": self.extract_header(text),
            "facts": self.extract_facts(text),
            "issues": self.extract_issues(text),
            "arguments": self.extract_arguments(text),
            "analysis": self.extract_analysis(text),
            "verdict": self.extract_verdict(text),
            "order": self.extract_order(text),
        }

        for part_name, part_text in parts.items():
            if part_text:
                sections.append(StructuredSection(
                    text=part_text,
                    metadata={
                        "judgment_part": part_name,
                        "keywords": extract_legal_keywords(part_text),
                    }
                ))

        return sections
```

### 6.3 Legal Document Sources for Ingestion

| Source | Content | Format | URL Pattern |
|--------|---------|--------|-------------|
| India Code | All Central Acts | HTML/PDF | indiacode.nic.in |
| Indian Kanoon | Case Judgments | HTML | indiankanoon.org |
| Supreme Court of India | SC Judgments | PDF | sci.gov.in |
| National Informatics Centre | Bare Acts | PDF | legislative.gov.in |
| Ministry of Law | Notifications | PDF | lawmin.gov.in |
| State Legal Databases | State Acts | PDF/HTML | Various state portals |

---

## 7. Retrieval & Ranking Pipeline

### 7.1 Multi-Stage Retrieval

```
Stage 1: Query Expansion
  └─ LLM expands layman query to legal terms + synonyms

Stage 2: Hybrid Retrieval (Qdrant)
  ├─ Dense Search (embedding similarity) → top 30
  └─ Sparse Search (BM25 keyword matching) → top 30

Stage 3: Reciprocal Rank Fusion (RRF)
  └─ Merge dense + sparse results → top 20

Stage 4: Cross-Encoder Re-ranking
  └─ Re-score with cross-encoder model → top 10

Stage 5: Contextual Filtering
  └─ Filter by user role, jurisdiction, relevance threshold → top 5-7

Stage 6: Citation Verification
  └─ Verify each source exists and is accurately referenced
```

### 7.2 Reciprocal Rank Fusion Implementation

```python
def reciprocal_rank_fusion(
    result_lists: List[List[SearchResult]],
    k: int = 60,
    weights: Optional[List[float]] = None
) -> List[SearchResult]:
    """
    RRF merges multiple ranked lists into a single ranking.
    Score = sum(weight_i / (k + rank_i)) for each result across all lists

    For legal search:
    - Dense captures semantic similarity (meaning)
    - Sparse captures exact keyword matches (section numbers, act names)
    - Both are critical for legal accuracy
    """
    if weights is None:
        weights = [1.0] * len(result_lists)

    fused_scores = {}
    result_map = {}

    for list_idx, results in enumerate(result_lists):
        for rank, result in enumerate(results):
            doc_id = result.id
            if doc_id not in fused_scores:
                fused_scores[doc_id] = 0.0
                result_map[doc_id] = result
            fused_scores[doc_id] += weights[list_idx] / (k + rank + 1)

    # Sort by fused score
    sorted_results = sorted(fused_scores.items(), key=lambda x: x[1], reverse=True)

    return [result_map[doc_id] for doc_id, _ in sorted_results]
```

---

## 8. Document Drafting System

### 8.1 Architecture

```
User selects document type → Frontend shows dynamic form (fields from template schema)
  → User fills fields → Backend validates → LLM generates draft with template
  → Citation checker verifies legal references → Draft returned for review
  → User edits/approves → PDF generated with proper legal formatting
```

### 8.2 Template + LLM Hybrid Approach

```python
# document_drafting/engine.py

class DocumentDraftingEngine:
    """Hybrid template + LLM approach for legal document generation"""

    def __init__(self, llm, template_dir="templates/legal"):
        self.llm = llm
        self.env = Environment(loader=FileSystemLoader(template_dir))
        self.templates = self.load_template_schemas()

    async def generate_draft(self, doc_type: str, fields: dict, language: str = "en") -> str:
        """
        1. Load Jinja2 template for document structure
        2. Use LLM to fill in legal language sections
        3. Merge template + LLM output
        4. Validate and format
        """
        template_schema = self.templates[doc_type]

        # Validate required fields
        missing = [f for f in template_schema["required_fields"] if f not in fields]
        if missing:
            raise ValueError(f"Missing required fields: {missing}")

        # Generate legal language sections using LLM
        llm_sections = await self.generate_legal_sections(doc_type, fields)

        # Merge with Jinja2 template
        template = self.env.get_template(f"{doc_type}.jinja2")
        rendered = template.render(
            **fields,
            legal_sections=llm_sections,
            date=datetime.now().strftime("%d/%m/%Y"),
        )

        # Translate if needed
        if language != "en":
            rendered = await translate_document(rendered, language)

        return rendered

    async def generate_legal_sections(self, doc_type: str, fields: dict) -> dict:
        """Use LLM to generate contextually appropriate legal language"""
        prompt = DRAFTING_PROMPTS[doc_type].format(**fields)
        response = await self.llm.ainvoke(prompt)
        return parse_llm_sections(response)

    def export_pdf(self, content: str, doc_type: str) -> bytes:
        """Export draft as formatted PDF using ReportLab/WeasyPrint"""
        from weasyprint import HTML
        html_content = self.markdown_to_legal_html(content, doc_type)
        return HTML(string=html_content).write_pdf()
```

### 8.3 Template Schema Example (FIR)

```json
{
    "type": "fir",
    "name": "First Information Report",
    "required_fields": [
        "complainant_name",
        "complainant_address",
        "complainant_phone",
        "incident_date",
        "incident_time",
        "incident_location",
        "incident_description",
        "accused_details",
        "witnesses"
    ],
    "optional_fields": [
        "evidence_description",
        "property_lost",
        "injuries_sustained"
    ],
    "field_types": {
        "complainant_name": {"type": "text", "label": "Full Name of Complainant"},
        "incident_date": {"type": "date", "label": "Date of Incident"},
        "incident_description": {"type": "textarea", "label": "Describe what happened in detail"},
        "witnesses": {"type": "array", "label": "Witness Details", "items": {"name": "text", "address": "text"}}
    }
}
```

---

## 9. User Role-Based Access System

### 9.1 Access Control Matrix

| Feature | Citizen | Lawyer | Legal Advisor | Police | Admin |
|---------|---------|--------|---------------|--------|-------|
| Basic legal query | Yes | Yes | Yes | Yes | Yes |
| Simplified responses | Yes | - | - | - | - |
| IRAC analysis | - | Yes | Yes | - | - |
| Case comparison | - | Yes | Yes | - | - |
| Similar case search | Limited(3) | Full | Full | Limited | Full |
| Section lookup | Yes | Yes | Yes | Yes | Yes |
| Document drafting | Basic(FIR,RTI) | All types | Corporate docs | FIR related | All |
| Precedent analysis | - | Yes | - | - | - |
| Corporate law access | - | - | Yes | - | Yes |
| Resource locator | Yes | Yes | - | - | - |
| Multilingual | Yes | Yes | Yes | Yes | - |
| Bulk case analysis | - | Yes(5/day) | Yes(5/day) | - | Unlimited |
| API rate limit | 20/hr | 100/hr | 50/hr | 50/hr | Unlimited |

### 9.2 Role-Based Collection Filtering

```python
# Each user role gets different Qdrant collections/filters
ROLE_COLLECTION_MAP = {
    "citizen": {
        "collections": ["legal_documents"],
        "filters": {"user_access_level": ["citizen", "all"]},
        "response_style": "simplified",
        "max_chunks": 5,
    },
    "lawyer": {
        "collections": ["legal_documents", "legal_sections"],
        "filters": {"user_access_level": ["lawyer", "all"]},
        "response_style": "technical_irac",
        "max_chunks": 15,
    },
    "legal_advisor": {
        "collections": ["legal_documents", "legal_sections"],
        "filters": {"user_access_level": ["advisor", "all"], "legal_domain": ["corporate", "it", "compliance"]},
        "response_style": "compliance_report",
        "max_chunks": 10,
    },
    "police": {
        "collections": ["legal_documents", "legal_sections"],
        "filters": {"user_access_level": ["police", "all"], "legal_domain": ["criminal"]},
        "response_style": "procedural",
        "max_chunks": 7,
    },
}
```

---

## 10. Source Citation & Verification System

### 10.1 Double-Check Pipeline

```
Response Generation
    │
    ▼
[Citation Extraction]  → Extract all section refs, case citations, legal claims
    │
    ▼
[Database Cross-Check] → Query Qdrant to verify each citation exists
    │
    ├── FOUND → Mark as ✅ VERIFIED
    ├── PARTIAL → Mark as ⚠️ PARTIALLY VERIFIED (warn user)
    └── NOT FOUND → Mark as ❌ REMOVE from response
    │
    ▼
[Consistency Check]    → Verify the cited content matches the claim made
    │
    ▼
[Confidence Score]     → Calculate overall response confidence (0-1)
    │
    ├── > 0.8  → Deliver response with "Verified" badge
    ├── 0.5-0.8 → Deliver with "Partially Verified" warning
    └── < 0.5  → Return "Unable to provide a verified answer. Please consult a legal professional."
```

### 10.2 Citation Format

```
Every response must include:

📋 Source Citations:
1. [Section 302, Indian Penal Code, 1860] - "Punishment for murder..."
   Source: India Code (indiacode.nic.in) | Verified ✅

2. [State of Maharashtra v. XYZ, AIR 2020 SC 1234] - "The court held that..."
   Source: Supreme Court Judgments Database | Verified ✅

3. [Section 154, CrPC] - "Information in cognizable cases..."
   Source: India Code | Verified ✅

⚠️ Verification Status: VERIFIED (3/3 citations confirmed)
📊 Confidence Score: 0.92
```

---

## 11. Multilingual Support

### 11.1 Translation Pipeline

```python
# Using Sarvam AI for Indian languages
SUPPORTED_LANGUAGES = {
    "en": "English",
    "hi": "Hindi",
    "ta": "Tamil",
    "te": "Telugu",
    "ml": "Malayalam",
    "kn": "Kannada",
    "bn": "Bengali",
    "mr": "Marathi",
    "gu": "Gujarati",
    "pa": "Punjabi",
    "or": "Odia",
}

class MultilingualService:
    def __init__(self):
        self.sarvam_client = SarvamClient(api_key=SARVAM_API_KEY)

    async def translate_response(self, text: str, target_lang: str) -> str:
        """Translate legal response while preserving section numbers and citations"""
        # Preserve legal entities (section numbers, case names, act names)
        preserved, placeholders = self.preserve_legal_entities(text)

        # Translate via Sarvam AI
        translated = await self.sarvam_client.translate(
            text=preserved,
            source_language="en",
            target_language=target_lang,
        )

        # Restore preserved entities
        restored = self.restore_legal_entities(translated, placeholders)
        return restored

    async def speech_to_text(self, audio_bytes: bytes, language: str) -> str:
        """Convert voice query to text using Sarvam AI STT"""
        return await self.sarvam_client.speech_to_text(
            audio=audio_bytes,
            language=language,
        )
```

---

## 12. Frontend Architecture

### 12.1 Next.js App Structure

```
frontend/
├── app/
│   ├── layout.tsx              # Root layout with auth provider
│   ├── page.tsx                # Landing page
│   ├── (auth)/
│   │   ├── login/page.tsx
│   │   └── register/page.tsx
│   ├── (dashboard)/
│   │   ├── layout.tsx          # Dashboard layout (role-aware sidebar)
│   │   ├── chat/page.tsx       # Main AI chat interface
│   │   ├── cases/
│   │   │   ├── page.tsx        # Case search & list
│   │   │   └── [id]/page.tsx   # Case analysis detail
│   │   ├── documents/
│   │   │   ├── page.tsx        # Document drafting home
│   │   │   ├── new/page.tsx    # New document form
│   │   │   └── [id]/page.tsx   # Draft editor
│   │   ├── sections/
│   │   │   └── page.tsx        # Act/Section browser
│   │   ├── resources/
│   │   │   └── page.tsx        # Nearby legal resources map
│   │   └── history/
│   │       └── page.tsx        # Query history
│   └── api/                    # Next.js API routes (proxy to FastAPI)
├── components/
│   ├── ui/                     # Shadcn/ui components
│   ├── chat/
│   │   ├── ChatInterface.tsx   # Main chat with streaming
│   │   ├── MessageBubble.tsx   # Role-aware message display
│   │   └── SourceCard.tsx      # Citation display card
│   ├── documents/
│   │   ├── DraftEditor.tsx     # Rich text editor for drafts
│   │   ├── TemplateForm.tsx    # Dynamic form from template schema
│   │   └── PDFPreview.tsx      # PDF preview component
│   └── thesys/
│       └── VisualResponse.tsx  # Thesys API visual components
├── lib/
│   ├── api.ts                  # FastAPI client
│   ├── auth.ts                 # JWT auth utilities
│   └── streaming.ts            # SSE streaming handler
└── hooks/
    ├── useChat.ts              # Chat state management
    ├── useAuth.ts              # Auth hook
    └── useStreaming.ts         # SSE streaming hook
```

### 12.2 Thesys Integration for Visual Responses

```typescript
// Thesys API for enhanced visual legal responses
// Used for layman-friendly visual explanations
import { ThesysClient } from '@thesys/sdk';

const thesys = new ThesysClient({ apiKey: process.env.THESYS_API_KEY });

// Generate visual flowcharts for legal procedures
// Generate infographics for rights and duties
// Generate comparison tables for legal options
```

---

## 13. Deployment Architecture

### 13.1 Infrastructure

```
Production Deployment:
├── Backend (FastAPI + CrewAI)
│   ├── Docker container
│   ├── Gunicorn + Uvicorn workers
│   └── Deploy: Railway / Render / AWS ECS
│
├── Vector Database (Qdrant)
│   ├── Qdrant Cloud (managed) OR
│   ├── Self-hosted Docker container
│   └── Persistent volume for data
│
├── Frontend (Next.js)
│   └── Deploy: Vercel
│
├── GPU Workloads (Embedding generation, fine-tuning)
│   └── Lightning AI (15 credits/month free)
│
├── Database (User data, sessions, drafts)
│   └── PostgreSQL (Supabase / Neon)
│
├── Cache
│   └── Redis (Upstash)
│
└── External APIs
    ├── LLM: DeepSeek API / Groq / Claude API
    ├── Translation: Sarvam AI
    ├── Search: SERP API
    └── Visual: Thesys API
```

### 13.2 Environment Variables

```env
# LLM
LLM_PROVIDER=deepseek  # or groq, anthropic, openai
LLM_API_KEY=
LLM_MODEL=deepseek-chat  # or llama-3.3-70b-versatile (Groq)

# Qdrant
QDRANT_URL=http://localhost:6333
QDRANT_API_KEY=

# Database
DATABASE_URL=postgresql://...

# Auth
JWT_SECRET_KEY=
JWT_ALGORITHM=HS256
JWT_EXPIRY_MINUTES=60

# External APIs
SARVAM_API_KEY=
SERP_API_KEY=
THESYS_API_KEY=

# Embedding (if API-based)
EMBEDDING_API_KEY=

# Redis
REDIS_URL=

# Lightning AI (for GPU tasks)
LIGHTNING_API_KEY=
```

---

## 14. Project Structure

```
Phase2/
├── CLAUDE.md                          # Agent team definitions & project rules
├── plan.md                            # This architecture plan
├── docs/
│   ├── embedding_model_comparison.md  # Embedding model analysis
│   ├── tech_stack_index.md            # Tech stack documentation index
│   └── document_drafting_design.md    # Document drafting system design
│
├── backend/
│   ├── main.py                        # FastAPI application entry
│   ├── requirements.txt
│   ├── .env.example
│   ├── config/
│   │   ├── settings.py                # App configuration
│   │   └── llm_config.py             # LLM provider configuration
│   │
│   ├── api/
│   │   ├── __init__.py
│   │   ├── deps.py                    # Dependencies (auth, DB)
│   │   ├── routes/
│   │   │   ├── auth.py
│   │   │   ├── query.py
│   │   │   ├── cases.py
│   │   │   ├── documents.py
│   │   │   ├── sections.py
│   │   │   ├── resources.py
│   │   │   ├── translate.py
│   │   │   ├── admin.py
│   │   │   └── feedback.py
│   │   └── schemas/
│   │       ├── auth.py
│   │       ├── query.py
│   │       ├── cases.py
│   │       ├── documents.py
│   │       └── common.py
│   │
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── crew_config.py             # CrewAI crew definitions
│   │   ├── agents/
│   │   │   ├── query_analyst.py
│   │   │   ├── retrieval_specialist.py
│   │   │   ├── legal_reasoner.py
│   │   │   ├── citation_checker.py
│   │   │   ├── response_formatter.py
│   │   │   └── document_drafter.py
│   │   ├── tasks/
│   │   │   ├── analysis_tasks.py
│   │   │   ├── retrieval_tasks.py
│   │   │   └── drafting_tasks.py
│   │   └── tools/
│   │       ├── qdrant_search.py
│   │       ├── section_verifier.py
│   │       ├── query_classifier.py
│   │       ├── resource_locator.py
│   │       ├── translation.py
│   │       └── pdf_generator.py
│   │
│   ├── rag/
│   │   ├── __init__.py
│   │   ├── embeddings.py              # Embedding model wrapper
│   │   ├── sparse_encoder.py          # BM25/SPLADE sparse encoder
│   │   ├── hybrid_search.py           # Hybrid search implementation
│   │   ├── reranker.py                # Cross-encoder re-ranking
│   │   └── rrf.py                     # Reciprocal Rank Fusion
│   │
│   ├── preprocessing/
│   │   ├── __init__.py
│   │   ├── pipeline.py                # Main preprocessing pipeline
│   │   ├── extractors/
│   │   │   ├── pdf_extractor.py       # PyMuPDF text extraction
│   │   │   ├── ocr_extractor.py       # OCR for scanned PDFs
│   │   │   └── html_extractor.py      # Web scraping (Indian Kanoon etc.)
│   │   ├── cleaners/
│   │   │   ├── text_cleaner.py        # Unicode, whitespace normalization
│   │   │   ├── header_footer.py       # Remove headers/footers
│   │   │   └── legal_normalizer.py    # Legal abbreviation expansion
│   │   ├── parsers/
│   │   │   ├── act_parser.py          # Act/Section structure parser
│   │   │   ├── judgment_parser.py     # Case judgment parser
│   │   │   └── notification_parser.py # Legal notification parser
│   │   └── chunkers/
│   │       ├── legal_chunker.py       # Legal-aware chunking
│   │       └── metadata_extractor.py  # Auto-extract legal metadata
│   │
│   ├── document_drafting/
│   │   ├── __init__.py
│   │   ├── engine.py                  # Draft generation engine
│   │   ├── templates/
│   │   │   ├── fir.jinja2
│   │   │   ├── rti_application.jinja2
│   │   │   ├── complaint_letter.jinja2
│   │   │   ├── legal_notice.jinja2
│   │   │   ├── affidavit.jinja2
│   │   │   └── bail_application.jinja2
│   │   ├── schemas/
│   │   │   └── template_schemas.json  # Field definitions per template
│   │   └── pdf_generator.py           # PDF export (WeasyPrint)
│   │
│   ├── services/
│   │   ├── auth_service.py
│   │   ├── citation_service.py        # Citation verification logic
│   │   ├── translation_service.py     # Sarvam AI integration
│   │   └── resource_service.py        # SERP API integration
│   │
│   ├── db/
│   │   ├── database.py                # SQLAlchemy setup
│   │   ├── models.py                  # User, QueryHistory, Draft models
│   │   └── migrations/               # Alembic migrations
│   │
│   └── tests/
│       ├── test_query.py
│       ├── test_retrieval.py
│       ├── test_citation.py
│       └── test_drafting.py
│
├── frontend/
│   ├── package.json
│   ├── next.config.js
│   ├── app/                           # Next.js App Router
│   ├── components/
│   ├── lib/
│   └── public/
│
├── data/
│   ├── raw/                           # Raw legal PDFs
│   │   ├── acts/
│   │   ├── judgments/
│   │   └── notifications/
│   ├── processed/                     # Processed/cleaned text
│   └── scripts/
│       ├── ingest_acts.py             # Batch ingest acts
│       ├── ingest_judgments.py        # Batch ingest judgments
│       └── scrape_indiankanoon.py     # Scrape case judgments
│
├── docker-compose.yml                 # Qdrant + Backend + Redis
├── Dockerfile.backend
└── Dockerfile.frontend
```

---

## Appendix A: LLM Provider Strategy

### Cost-Optimized Multi-LLM Approach

| Task | Model | Why |
|------|-------|-----|
| Query Classification | Groq (Llama 3.3 70B) | Fast, free tier, good for classification |
| Legal Reasoning (IRAC) | DeepSeek-R1 / Claude Sonnet | Strong reasoning, handles complex legal analysis |
| Response Formatting | Groq (Llama 3.3 70B) | Fast, good for text formatting |
| Citation Verification | DeepSeek-Chat | Good accuracy, affordable |
| Document Drafting | Claude Sonnet / DeepSeek | High quality text generation |
| Translation | Sarvam AI API | Purpose-built for Indian languages |

### Fallback Chain
```
Primary: DeepSeek API (cost-effective, strong reasoning)
  └─ Fallback 1: Groq (fast, free tier for development)
      └─ Fallback 2: Claude API (highest quality, higher cost)
```

---

## Appendix B: Security Considerations

1. **Data Privacy**: All user queries encrypted at rest and in transit (TLS 1.3)
2. **No PII in Vector DB**: Strip personally identifiable information before embedding
3. **JWT Auth**: Role-based access with token expiry
4. **Rate Limiting**: Per-role rate limits to prevent abuse
5. **Input Sanitization**: Prevent prompt injection attacks
6. **Audit Logging**: Log all queries for compliance (anonymized)
7. **GDPR-like Compliance**: Right to deletion of user data

---

## Appendix C: Performance Targets

| Metric | Target |
|--------|--------|
| Query Response Time (simple) | < 3 seconds |
| Query Response Time (IRAC analysis) | < 10 seconds |
| Document Draft Generation | < 15 seconds |
| Search Recall@10 | > 0.85 |
| Citation Accuracy | > 0.95 |
| System Uptime | 99.5% |
| Concurrent Users | 100+ |
| Vector DB Query Latency | < 200ms |
