# Tech Stack Documentation Index
## Indian Legal Domain Agentic AI System

> **Last Updated:** 2026-02-17
> **Note:** Version numbers reflect the latest stable releases known as of the document creation date. Always verify against the official sources linked below before installing.

---

## Table of Contents

1. [Qdrant - Vector Database for RAG](#1-qdrant---vector-database-for-rag)
2. [FastAPI - Python API Framework](#2-fastapi---python-api-framework)
3. [CrewAI - Multi-Agent AI Framework](#3-crewai---multi-agent-ai-framework)
4. [Next.js / React.js - Frontend](#4-nextjs--reactjs---frontend)
5. [Sarvam AI - Indian Language Translation API](#5-sarvam-ai---indian-language-translation-api)
6. [Thesys API - Visual UI Components](#6-thesys-api---visual-ui-components)
7. [SERP API - Search Engine Results](#7-serp-api---search-engine-results)
8. [LangChain / LangGraph - LLM Orchestration](#8-langchain--langgraph---llm-orchestration)
9. [PyMuPDF / pdfplumber - PDF Processing](#9-pymupdf--pdfplumber---pdf-processing)
10. [Jinja2 - Template Engine for Document Drafting](#10-jinja2---template-engine-for-document-drafting)
11. [Integration Architecture Overview](#11-integration-architecture-overview)
12. [Recommended Installation Order](#12-recommended-installation-order)

---

## 1. Qdrant - Vector Database for RAG

### Role in Our System
Stores vector embeddings of Indian legal documents (IPC/BNS sections, case law, judgments, legal precedents) and enables semantic similarity search for the Retrieval-Augmented Generation (RAG) pipeline.

### Documentation

| Resource | URL |
|---|---|
| Official Docs | https://qdrant.tech/documentation/ |
| Quick Start | https://qdrant.tech/documentation/quickstart/ |
| API Reference | https://qdrant.tech/documentation/interfaces/ |
| Python Client Docs | https://python-client.qdrant.tech/ |
| GitHub Repository | https://github.com/qdrant/qdrant |
| Docker Hub | https://hub.docker.com/r/qdrant/qdrant |

### Version
- **Qdrant Server:** `v1.13.x` (verify at https://github.com/qdrant/qdrant/releases)
- **Python Client:** `qdrant-client >= 1.13.0` (`pip install qdrant-client`)

### Key Concepts for Our Use Case

- **Collections:** Create separate collections for different legal document types:
  - `indian_penal_code` - IPC/BNS sections
  - `case_law` - Court judgments and case precedents
  - `legal_templates` - Document templates for drafting
  - `user_documents` - User-uploaded legal documents
- **Payload Filtering:** Attach metadata (section number, court, date, language, jurisdiction) as payloads for hybrid search combining semantic similarity with metadata filters.
- **Sparse Vectors:** Use sparse vectors alongside dense vectors for hybrid search (keyword + semantic), critical for legal term precision (e.g., "Section 302" must match exactly).
- **Quantization:** Use scalar quantization for production to reduce memory footprint when indexing large volumes of legal text.
- **Snapshots:** Use snapshot functionality for backup/restore of legal knowledge bases.

### Integration Patterns

```python
# Integration with LangChain for RAG pipeline
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient

client = QdrantClient(url="http://localhost:6333")

vector_store = QdrantVectorStore(
    client=client,
    collection_name="indian_legal_docs",
    embedding=your_embedding_model,
)

# Hybrid search with metadata filtering
results = vector_store.similarity_search(
    query="punishment for theft under BNS",
    k=5,
    filter={"jurisdiction": "Supreme Court of India"}
)
```

### Gotchas and Limitations

- **Memory:** Qdrant loads indexes into RAM. For large legal corpora (millions of documents), plan for adequate memory or enable on-disk storage with `on_disk=True`.
- **Collection schema changes:** You cannot modify the vector dimensions of an existing collection. Plan your embedding model choice before creating production collections.
- **Payload indexing:** Always create payload indexes on fields you filter by (e.g., `court`, `year`, `section_number`) -- without indexes, filter queries scan all points.
- **Batch upsert limits:** Keep batch sizes under 1000 points per upsert call to avoid timeouts.
- **Docker networking:** When running Qdrant in Docker alongside FastAPI, ensure they share the same Docker network or use host networking.

---

## 2. FastAPI - Python API Framework

### Role in Our System
Serves as the backend API layer, handling HTTP requests from the frontend, orchestrating CrewAI agents, managing user sessions, and interfacing with all backend services (Qdrant, Sarvam AI, SERP API).

### Documentation

| Resource | URL |
|---|---|
| Official Docs | https://fastapi.tiangolo.com/ |
| Tutorial - First Steps | https://fastapi.tiangolo.com/tutorial/ |
| API Reference | https://fastapi.tiangolo.com/reference/ |
| Advanced User Guide | https://fastapi.tiangolo.com/advanced/ |
| GitHub Repository | https://github.com/fastapi/fastapi |
| PyPI | https://pypi.org/project/fastapi/ |

### Version
- **FastAPI:** `>= 0.115.x` (`pip install "fastapi[standard]"`)
- **Uvicorn:** `>= 0.34.x` (ASGI server, installed with `fastapi[standard]`)
- **Python:** `>= 3.9` (3.11+ recommended for performance)

### Key Concepts for Our Use Case

- **Async Support:** Use `async def` endpoints for I/O-bound operations (calling Sarvam AI, Qdrant, SERP API). Legal queries involve multiple external API calls that benefit from concurrency.
- **Dependency Injection:** Use FastAPI's `Depends()` for database sessions, authentication, and shared clients (Qdrant client, HTTP clients for external APIs).
- **Background Tasks:** Use `BackgroundTasks` for non-blocking operations like logging legal document access, triggering translation jobs, or updating vector stores.
- **WebSocket Support:** Implement WebSocket endpoints for streaming agent responses (CrewAI agents can take time; stream intermediate results).
- **Request Validation:** Use Pydantic models to validate legal query inputs (language code, document type, jurisdiction filters).
- **Middleware:** Add CORS middleware for frontend communication, rate limiting for API protection.

### Integration Patterns

```python
from fastapi import FastAPI, Depends, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize Qdrant client, CrewAI agents on startup
    app.state.qdrant_client = QdrantClient(url="http://localhost:6333")
    app.state.crew = initialize_legal_crew()
    yield
    # Cleanup on shutdown
    app.state.qdrant_client.close()

app = FastAPI(title="Indian Legal AI API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # Next.js frontend
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/api/legal-query")
async def legal_query(query: LegalQueryRequest):
    # Orchestrate CrewAI agents via FastAPI endpoint
    result = await run_legal_crew(query)
    return result

@app.post("/api/translate")
async def translate_document(req: TranslationRequest):
    # Call Sarvam AI for translation
    translated = await sarvam_translate(req.text, req.target_lang)
    return {"translated_text": translated}
```

### Gotchas and Limitations

- **Sync vs Async:** If you call synchronous blocking code (e.g., some CrewAI operations) inside an `async def` endpoint, it will block the event loop. Use `run_in_executor` or define the endpoint as `def` (not `async def`) to let FastAPI run it in a thread pool.
- **File uploads:** For large PDF uploads, use `UploadFile` (streaming) not `File` (loads entire file into memory).
- **Startup time:** Initializing CrewAI agents and loading models at startup can be slow. Use the `lifespan` context manager for proper init/shutdown.
- **CORS:** If the Next.js frontend is on a different port during development, CORS must be configured or API calls will be silently blocked.
- **Pydantic v2:** FastAPI 0.100+ uses Pydantic v2 by default. Ensure all models use the v2 syntax (`model_validator` instead of `validator`, `ConfigDict` instead of inner `class Config`).

---

## 3. CrewAI - Multi-Agent AI Framework

### Role in Our System
Orchestrates multiple specialized AI agents that collaborate to handle complex legal tasks: legal research agent, document drafting agent, case analysis agent, translation coordination agent, and legal advice summarization agent.

### Documentation

| Resource | URL |
|---|---|
| Official Docs | https://docs.crewai.com/ |
| Quick Start | https://docs.crewai.com/quickstart |
| Core Concepts | https://docs.crewai.com/concepts/ |
| API Reference | https://docs.crewai.com/reference/ |
| GitHub Repository | https://github.com/crewAIInc/crewAI |
| PyPI | https://pypi.org/project/crewai/ |
| CrewAI Tools | https://docs.crewai.com/concepts/tools |

### Version
- **CrewAI:** `>= 0.105.x` (`pip install crewai`) - verify at PyPI for latest
- **CrewAI Tools:** `>= 0.38.x` (`pip install 'crewai[tools]'`)
- Requires Python `>= 3.10`

### Key Concepts for Our Use Case

- **Agents:** Define specialized legal agents with distinct roles:
  - **Legal Researcher Agent** - Searches case law, statutes, and legal databases via RAG
  - **Document Drafter Agent** - Generates legal documents using Jinja2 templates
  - **Case Analyzer Agent** - Analyzes facts and maps to relevant legal provisions
  - **Translation Agent** - Coordinates with Sarvam AI for multilingual output
  - **Nearby Resources Agent** - Uses SERP API to find local lawyers, courts, legal aid
- **Tasks:** Each legal query becomes a set of tasks assigned to appropriate agents.
- **Tools:** Custom tools wrapping our Qdrant search, Sarvam AI translation, SERP API, and PDF processing.
- **Process Types:**
  - `sequential` - For step-by-step legal research (research -> analyze -> draft)
  - `hierarchical` - For complex cases where a manager agent delegates subtasks
- **Memory:** Enable crew memory so agents retain context across a user's legal consultation session.
- **Flows:** Use CrewAI Flows for complex multi-step legal workflows.

### Integration Patterns

```python
from crewai import Agent, Task, Crew, Process
from crewai.tools import tool

@tool("Search Indian Legal Database")
def search_legal_db(query: str) -> str:
    """Searches the Indian legal knowledge base using RAG."""
    results = qdrant_client.search(
        collection_name="indian_legal_docs",
        query_vector=embed(query),
        limit=5
    )
    return format_results(results)

@tool("Translate to Indian Language")
def translate_text(text: str, target_language: str) -> str:
    """Translates legal text to an Indian language using Sarvam AI."""
    return sarvam_translate(text, target_language)

legal_researcher = Agent(
    role="Indian Legal Research Specialist",
    goal="Find relevant Indian laws, precedents, and legal provisions",
    backstory="Expert in Indian legal system including IPC, BNS, CrPC, and BNSS",
    tools=[search_legal_db],
    verbose=True,
    llm="gpt-4o"  # or any supported LLM
)

document_drafter = Agent(
    role="Legal Document Drafter",
    goal="Draft accurate legal documents based on Indian legal standards",
    backstory="Specialist in drafting FIRs, complaints, petitions, and legal notices",
    tools=[search_legal_db],
    verbose=True,
)

research_task = Task(
    description="Research applicable legal provisions for: {user_query}",
    expected_output="List of relevant sections, precedents, and legal analysis",
    agent=legal_researcher,
)

drafting_task = Task(
    description="Draft the requested legal document based on research findings",
    expected_output="Complete legal document ready for review",
    agent=document_drafter,
    context=[research_task],  # Uses output of research_task
)

legal_crew = Crew(
    agents=[legal_researcher, document_drafter],
    tasks=[research_task, drafting_task],
    process=Process.sequential,
    memory=True,
    verbose=True,
)

result = legal_crew.kickoff(inputs={"user_query": "Draft FIR for theft"})
```

### Gotchas and Limitations

- **LLM Costs:** Each agent call consumes LLM tokens. With multiple agents collaborating, costs can multiply quickly. Implement token budgets and consider using cheaper models for simpler agents (translation coordination doesn't need GPT-4).
- **Blocking execution:** `crew.kickoff()` is synchronous and can take minutes for complex tasks. In FastAPI, run it in a thread pool or use `crew.kickoff_async()` if available.
- **Agent hallucination:** Agents may fabricate legal citations. Always validate RAG results against the actual vector store data. Implement a verification step.
- **Tool error handling:** If a tool (e.g., Sarvam API) fails, the agent may retry excessively or hallucinate the result. Implement proper error returns in tools.
- **Rate limits:** CrewAI can make many LLM calls in rapid succession. Configure rate limiting or use the `max_rpm` parameter on agents.
- **Memory persistence:** By default, crew memory is in-memory and session-scoped. For persistent legal consultation history, implement custom memory backed by a database.
- **Version churn:** CrewAI is evolving rapidly. Pin your version and test upgrades carefully.

---

## 4. Next.js / React.js - Frontend

### Role in Our System
Provides the user interface for the legal AI platform: legal query input (with multi-language support), document viewing/editing, chat-like interaction with AI agents, and display of search results for nearby legal resources.

### Documentation

| Resource | URL |
|---|---|
| Next.js Official Docs | https://nextjs.org/docs |
| Next.js Getting Started | https://nextjs.org/docs/getting-started/installation |
| Next.js App Router | https://nextjs.org/docs/app |
| React.js Official Docs | https://react.dev/ |
| React.js Learn | https://react.dev/learn |
| Next.js GitHub | https://github.com/vercel/next.js |
| React.js GitHub | https://github.com/facebook/react |

### Version
- **Next.js:** `>= 15.x` (`npx create-next-app@latest`)
- **React.js:** `>= 19.x` (bundled with Next.js 15)
- **Node.js:** `>= 18.18` (LTS 20.x or 22.x recommended)

### When to Use Next.js vs React.js

| Criterion | Next.js (Recommended) | React.js (CRA/Vite) |
|---|---|---|
| SEO for public legal info pages | Yes (SSR/SSG) | No (CSR only) |
| Multi-language URL routing | Built-in i18n routing | Manual setup |
| API routes (BFF pattern) | Built-in | Needs separate server |
| Initial load performance | Excellent (SSR) | Good (CSR) |
| Complexity | Higher | Lower |

**Recommendation:** Use **Next.js** for this project. Legal information pages benefit from SSR/SSG for SEO, the i18n routing is essential for multi-language support, and API routes can proxy calls to the FastAPI backend.

### Key Concepts for Our Use Case

- **App Router (Next.js 15):** Use the `app/` directory with React Server Components for legal content pages.
- **Internationalization:** Configure `next.config.js` with Indian language locales (`hi`, `bn`, `ta`, `te`, `mr`, `gu`, `kn`, `ml`, `pa`, `or`).
- **Streaming:** Use React Suspense + Next.js streaming to progressively render AI agent responses.
- **Server Actions:** Use for form submissions (legal query forms, document upload).
- **Dynamic Routes:** `app/case/[id]/page.tsx` for individual case analysis views.

### Integration Patterns

```typescript
// app/api/legal-query/route.ts - Next.js API Route proxying to FastAPI
export async function POST(request: Request) {
  const body = await request.json();
  const response = await fetch("http://localhost:8000/api/legal-query", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return Response.json(await response.json());
}

// Streaming agent responses via WebSocket
"use client";
import { useEffect, useState } from "react";

function LegalChat() {
  const [messages, setMessages] = useState<Message[]>([]);

  useEffect(() => {
    const ws = new WebSocket("ws://localhost:8000/ws/legal-chat");
    ws.onmessage = (event) => {
      setMessages((prev) => [...prev, JSON.parse(event.data)]);
    };
    return () => ws.close();
  }, []);

  return <ChatInterface messages={messages} />;
}
```

### Gotchas and Limitations

- **App Router learning curve:** The App Router (Next.js 13+) paradigm with Server Components vs Client Components can be confusing. Mark interactive components with `"use client"`.
- **Hydration errors:** When rendering content that differs between server and client (e.g., user-specific legal history), use `useEffect` or `dynamic()` with `ssr: false`.
- **Bundle size:** Libraries like PDF viewers and rich text editors can bloat the client bundle. Use dynamic imports (`next/dynamic`) with `{ ssr: false }`.
- **CORS with FastAPI:** During development, Next.js (port 3000) and FastAPI (port 8000) are on different origins. Either proxy through Next.js API routes or configure CORS on FastAPI.
- **Indian language fonts:** Ensure proper font loading for Devanagari, Tamil, Bengali, Telugu, and other scripts. Use `next/font` with Google Fonts (Noto Sans for comprehensive Indic script support).
- **Vercel deployment limits:** If deploying on Vercel, serverless function timeouts (default 10s) may be too short for AI agent responses. Consider alternative hosting or streaming responses.

---

## 5. Sarvam AI - Indian Language Translation API

### Role in Our System
Provides translation, transliteration, and text-to-speech capabilities for Indian languages, enabling the legal AI system to serve users in their preferred language (Hindi, Bengali, Tamil, Telugu, Marathi, Gujarati, Kannada, Malayalam, Punjabi, Odia, and more).

### Documentation

| Resource | URL |
|---|---|
| Official Docs | https://docs.sarvam.ai/ |
| API Reference | https://docs.sarvam.ai/api-reference-docs |
| Dashboard / API Keys | https://dashboard.sarvam.ai/ |
| Sarvam Translate | https://docs.sarvam.ai/api-reference-docs/translate |
| Text-to-Speech | https://docs.sarvam.ai/api-reference-docs/text-to-speech |
| Speech-to-Text | https://docs.sarvam.ai/api-reference-docs/speech-to-text |
| Transliterate | https://docs.sarvam.ai/api-reference-docs/transliterate |
| GitHub (Python SDK) | https://github.com/sarvamai/sarvam-ai-sdk |

### Version
- **Sarvam Python SDK:** Check PyPI for `sarvamai` or use REST API directly
- **API Version:** v1 (latest as per docs)

### Supported Languages (relevant for Indian Legal)

| Language | Code | Script |
|---|---|---|
| Hindi | `hi` | Devanagari |
| Bengali | `bn` | Bengali |
| Tamil | `ta` | Tamil |
| Telugu | `te` | Telugu |
| Marathi | `mr` | Devanagari |
| Gujarati | `gu` | Gujarati |
| Kannada | `kn` | Kannada |
| Malayalam | `ml` | Malayalam |
| Punjabi | `pa` | Gurmukhi |
| Odia | `or` | Odia |
| English | `en` | Latin |

### Key Concepts for Our Use Case

- **Legal Terminology Translation:** Legal terms often have specific translations. Use Sarvam's translation with domain context where possible. Consider building a legal glossary overlay.
- **Translate API:** Core endpoint for translating legal summaries, document drafts, and AI responses into user's preferred Indian language.
- **Text-to-Speech (TTS):** Useful for accessibility -- read out legal advice in the user's native language.
- **Speech-to-Text (STT):** Allow users to describe their legal issue verbally in their native language.
- **Transliterate:** Convert Romanized input (e.g., "mujhe chori ki FIR karni hai") to Devanagari script.

### Integration Patterns

```python
import httpx

SARVAM_API_KEY = "your-api-key"
SARVAM_BASE_URL = "https://api.sarvam.ai"

async def translate_legal_text(
    text: str,
    source_lang: str = "en",
    target_lang: str = "hi"
) -> str:
    """Translate legal text using Sarvam AI."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{SARVAM_BASE_URL}/translate",
            headers={
                "API-Subscription-Key": SARVAM_API_KEY,
                "Content-Type": "application/json",
            },
            json={
                "input": text,
                "source_language_code": source_lang,
                "target_language_code": target_lang,
                "mode": "formal",  # Legal text should use formal mode
                "enable_preprocessing": True,
            },
        )
        response.raise_for_status()
        return response.json()["translated_text"]

# CrewAI tool wrapper
@tool("Translate Legal Text")
def translate_for_agent(text: str, target_language: str) -> str:
    """Translates legal text into the specified Indian language."""
    import asyncio
    return asyncio.run(translate_legal_text(text, "en", target_language))
```

### Gotchas and Limitations

- **Legal terminology accuracy:** General-purpose translation may not correctly translate specialized legal terms (e.g., "cognizable offense", "bail", "habeas corpus"). Implement post-processing or a legal glossary.
- **Rate limits:** API has rate limits. Implement retry logic with exponential backoff. Cache frequently translated phrases (e.g., standard legal disclaimers).
- **Character limits:** Individual API calls may have character/token limits. For long legal documents, chunk the text and translate in segments, preserving paragraph structure.
- **Script mixing:** Legal documents often mix English terms within Indian language text (e.g., "FIR", "IPC Section 420"). Handle these gracefully -- don't translate abbreviations and section references.
- **API key security:** Store the API key in environment variables, never in frontend code. All Sarvam API calls should go through the FastAPI backend.
- **Latency:** Translation API calls add latency. For user-facing responses, consider translating in the background and streaming results.

---

## 6. Thesys API - Visual UI Components

### Role in Our System
Provides pre-built visual UI components (charts, flowcharts, decision trees, interactive cards) to present legal information in a more digestible format -- e.g., visualizing legal process flowcharts, case timelines, penalty comparison charts, and decision trees for legal options.

### Documentation

| Resource | URL |
|---|---|
| Official Docs | https://docs.thesys.ai/ or https://www.thesys.ai/docs |
| API Reference | Check official site for latest endpoints |
| Dashboard | https://app.thesys.ai/ or https://www.thesys.ai/ |
| GitHub | Check https://github.com/thesysai for available repos |

> **Note:** Thesys is a relatively newer product. Documentation URLs and features may change. Verify the above links against the current official site.

### Version
- Check the official Thesys website for the latest SDK/API version.

### Key Concepts for Our Use Case

- **Legal Process Flowcharts:** Visualize the step-by-step process for filing an FIR, bail application, court proceedings, etc.
- **Decision Trees:** Interactive decision trees for "Which legal provision applies to your situation?"
- **Comparison Tables:** Compare penalties, legal options, or outcomes visually.
- **Case Timelines:** Visualize chronological events in a legal case.
- **Interactive Cards:** Present legal information as expandable, categorized cards for better mobile UX.
- **Generative UI:** Use Thesys to dynamically generate UI components from AI agent outputs.

### Integration Patterns

```typescript
// Example: Rendering a Thesys component in Next.js
// Approach depends on whether Thesys provides a React SDK or REST API

// Option A: If Thesys provides an embeddable component / React SDK
import { ThesysRenderer } from "@thesys/react"; // hypothetical package name

function LegalFlowchart({ processData }) {
  return (
    <ThesysRenderer
      type="flowchart"
      data={processData}
      theme="light"
      locale="hi" // Hindi localization
    />
  );
}

// Option B: If Thesys is API-based, call from backend
// FastAPI endpoint
@app.post("/api/visualize")
async def generate_visualization(req: VisualizationRequest):
    thesys_response = await httpx.AsyncClient().post(
        "https://api.thesys.ai/v1/generate",
        headers={"Authorization": f"Bearer {THESYS_API_KEY}"},
        json={
            "type": req.chart_type,
            "data": req.data,
            "options": req.options,
        }
    )
    return thesys_response.json()
```

### Gotchas and Limitations

- **Newer product:** Documentation and APIs may be less mature than other tools in the stack. Expect breaking changes.
- **Indic language rendering:** Verify that Thesys components properly render Indian language scripts (Devanagari, Tamil, Bengali, etc.).
- **Bundle size:** If using a client-side SDK, check the bundle size impact on the Next.js frontend.
- **Fallback:** Build fallback UI components using standard charting libraries (e.g., Recharts, D3.js) in case Thesys API has downtime or doesn't support a specific visualization type.
- **Pricing:** Check the pricing model carefully -- visual generation APIs can be expensive at scale.

---

## 7. SERP API - Search Engine Results

### Role in Our System
Enables searching for nearby legal resources: local lawyers, legal aid clinics, court locations, police stations for FIR filing, and other location-specific legal services relevant to the user.

### Documentation

| Resource | URL |
|---|---|
| Official Docs | https://serpapi.com/docs |
| Google Search API | https://serpapi.com/search-api |
| Google Maps API | https://serpapi.com/google-maps-api |
| Google Local Results | https://serpapi.com/google-local-results |
| Playground | https://serpapi.com/playground |
| Python Library | https://serpapi.com/integrations/python |
| GitHub | https://github.com/serpapi/google-search-results-python |
| PyPI | https://pypi.org/project/google-search-results/ |

### Version
- **Python Client:** `google-search-results >= 2.4.2` (`pip install google-search-results`)

### Key Concepts for Our Use Case

- **Local Search:** Use Google Maps/Local search to find lawyers, courts, and legal aid centers near the user's location.
- **Organic Search:** Search for specific legal information, government notifications, and legal updates from Indian legal databases.
- **Knowledge Graph:** Extract structured information about legal entities, laws, and institutions.
- **Location-based results:** Use `location` parameter with Indian cities/states for localized results.

### Integration Patterns

```python
from serpapi import GoogleSearch

SERP_API_KEY = "your-api-key"

def find_nearby_lawyers(location: str, specialization: str = "criminal") -> list:
    """Find nearby lawyers using SERP API Google Maps."""
    params = {
        "engine": "google_maps",
        "q": f"{specialization} lawyer near {location}",
        "type": "search",
        "api_key": SERP_API_KEY,
        "hl": "en",
        "gl": "in",  # Country: India
    }
    search = GoogleSearch(params)
    results = search.get_dict()

    lawyers = []
    for place in results.get("local_results", []):
        lawyers.append({
            "name": place.get("title"),
            "address": place.get("address"),
            "phone": place.get("phone"),
            "rating": place.get("rating"),
            "reviews": place.get("reviews"),
            "gps_coordinates": place.get("gps_coordinates"),
        })
    return lawyers

def search_legal_info(query: str) -> list:
    """Search for Indian legal information on the web."""
    params = {
        "engine": "google",
        "q": f"{query} Indian law",
        "api_key": SERP_API_KEY,
        "gl": "in",
        "hl": "en",
        "num": 10,
    }
    search = GoogleSearch(params)
    results = search.get_dict()
    return results.get("organic_results", [])

# CrewAI tool
@tool("Find Nearby Legal Resources")
def find_legal_resources(location: str, resource_type: str) -> str:
    """Finds nearby legal resources (lawyers, courts, police stations, legal aid)."""
    results = find_nearby_lawyers(location, resource_type)
    return format_lawyer_results(results)
```

### Gotchas and Limitations

- **API credits:** SERP API charges per search. Each Google Maps query and Google Search query consumes credits. Implement aggressive caching for common location-based queries.
- **Rate limits:** Free tier is limited (100 searches/month). Paid plans required for production.
- **Stale data:** Google Maps data can be outdated (wrong phone numbers, closed offices). Display disclaimer to users.
- **Location accuracy:** Indian address formatting is inconsistent. Allow users to specify their city/district rather than relying on full addresses.
- **No real-time availability:** SERP results don't tell you if a lawyer is currently available or accepting cases.
- **India-specific:** Set `gl=in` (geolocation India) and consider `hl` parameter for Hindi/English results.
- **Legal compliance:** Display appropriate disclaimers that search results are informational and not endorsements.

---

## 8. LangChain / LangGraph - LLM Orchestration

### Role in Our System
Provides the LLM orchestration layer: manages prompt templates, chains, RAG pipelines, and (via LangGraph) complex stateful agent workflows. Used alongside CrewAI -- LangChain handles RAG retrieval and prompt management while CrewAI manages multi-agent coordination.

### Documentation

| Resource | URL |
|---|---|
| LangChain Docs | https://python.langchain.com/docs/ |
| LangChain API Reference | https://python.langchain.com/api_reference/ |
| LangGraph Docs | https://langchain-ai.github.io/langgraph/ |
| LangChain Quick Start | https://python.langchain.com/docs/tutorials/ |
| LangSmith (Tracing) | https://docs.smith.langchain.com/ |
| LangChain GitHub | https://github.com/langchain-ai/langchain |
| LangGraph GitHub | https://github.com/langchain-ai/langgraph |
| PyPI (langchain) | https://pypi.org/project/langchain/ |
| PyPI (langgraph) | https://pypi.org/project/langgraph/ |
| Qdrant Integration | https://python.langchain.com/docs/integrations/vectorstores/qdrant/ |

### Version
- **langchain:** `>= 0.3.x` (`pip install langchain`)
- **langchain-core:** `>= 0.3.x` (installed as dependency)
- **langchain-community:** `>= 0.3.x` (for community integrations)
- **langchain-qdrant:** `>= 0.2.x` (`pip install langchain-qdrant`)
- **langgraph:** `>= 0.3.x` (`pip install langgraph`)

### Key Concepts for Our Use Case

- **RAG Pipeline:** `langchain-qdrant` provides `QdrantVectorStore` that integrates directly with the Qdrant vector database for legal document retrieval.
- **Prompt Templates:** Manage legal-domain-specific prompts with `ChatPromptTemplate`. Maintain templates for different legal tasks (case analysis, document drafting, section lookup).
- **Chains (LCEL):** Use LangChain Expression Language (LCEL) to compose retrieval -> formatting -> LLM -> output parsing chains.
- **LangGraph Workflows:** For complex legal workflows that require conditional logic, cycles, and state management (e.g., "if user needs FIR, follow path A; if user needs bail info, follow path B").
- **Output Parsers:** Use structured output parsers (Pydantic-based) to get consistent structured legal data from LLM responses.
- **LangSmith Tracing:** Enable LangSmith for monitoring and debugging LLM calls in production.

### Integration Patterns

```python
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import PydanticOutputParser
from langchain_qdrant import QdrantVectorStore
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from pydantic import BaseModel, Field

# RAG chain for legal document retrieval
class LegalAnalysis(BaseModel):
    applicable_sections: list[str] = Field(description="Applicable IPC/BNS sections")
    summary: str = Field(description="Legal analysis summary")
    recommended_action: str = Field(description="Recommended legal action")

parser = PydanticOutputParser(pydantic_object=LegalAnalysis)

prompt = ChatPromptTemplate.from_messages([
    ("system", """You are an Indian legal expert. Analyze the legal situation
    based on the following retrieved legal provisions:

    {context}

    {format_instructions}"""),
    ("human", "{query}"),
])

retriever = QdrantVectorStore(
    client=qdrant_client,
    collection_name="indian_legal_docs",
    embedding=OpenAIEmbeddings(),
).as_retriever(search_kwargs={"k": 5})

# LCEL chain
chain = (
    {"context": retriever, "query": lambda x: x, "format_instructions": lambda _: parser.get_format_instructions()}
    | prompt
    | ChatOpenAI(model="gpt-4o")
    | parser
)

result: LegalAnalysis = chain.invoke("What are the legal remedies for online fraud in India?")
```

```python
# LangGraph for complex legal workflow with conditional routing
from langgraph.graph import StateGraph, END
from typing import TypedDict

class LegalState(TypedDict):
    query: str
    query_type: str  # "fir", "bail", "legal_advice", "document_draft"
    context: list[str]
    analysis: str
    output: str

def classify_query(state: LegalState) -> LegalState:
    # Classify the legal query type
    ...
    return state

def route_query(state: LegalState) -> str:
    return state["query_type"]

graph = StateGraph(LegalState)
graph.add_node("classify", classify_query)
graph.add_node("fir_handler", handle_fir)
graph.add_node("bail_handler", handle_bail)
graph.add_node("advice_handler", handle_advice)
graph.add_node("draft_handler", handle_draft)

graph.set_entry_point("classify")
graph.add_conditional_edges("classify", route_query, {
    "fir": "fir_handler",
    "bail": "bail_handler",
    "legal_advice": "advice_handler",
    "document_draft": "draft_handler",
})

for node in ["fir_handler", "bail_handler", "advice_handler", "draft_handler"]:
    graph.add_edge(node, END)

legal_workflow = graph.compile()
```

### CrewAI + LangChain Coexistence

| Concern | Recommendation |
|---|---|
| RAG Retrieval | Use LangChain (langchain-qdrant) for the retrieval pipeline |
| Multi-Agent Coordination | Use CrewAI for agent orchestration |
| Complex Workflows | Use LangGraph if you need stateful, conditional workflows beyond CrewAI's process types |
| Prompt Management | Use LangChain's `ChatPromptTemplate` across both systems |
| Tracing/Observability | Use LangSmith -- it can trace LangChain calls even when initiated by CrewAI |

### Gotchas and Limitations

- **Package fragmentation:** LangChain has split into `langchain-core`, `langchain-community`, `langchain-openai`, `langchain-qdrant`, etc. You need to install the right sub-packages.
- **Rapid API changes:** LangChain's API changes frequently between versions. Pin versions and watch for deprecation warnings.
- **LCEL learning curve:** LangChain Expression Language (pipe `|` operator) can be confusing. Start with simple chains before building complex ones.
- **Overlap with CrewAI:** Both frameworks can do agent orchestration. Clearly delineate responsibilities to avoid redundancy: LangChain for RAG/chains, CrewAI for multi-agent coordination.
- **LangGraph complexity:** LangGraph is powerful but complex. Only use it if CrewAI's `sequential` and `hierarchical` processes are insufficient.
- **Token tracking:** Use LangSmith or callback handlers to track token usage across all chains. Legal queries can be verbose and consume many tokens.

---

## 9. PyMuPDF / pdfplumber - PDF Processing

### Role in Our System
Extracts text, tables, and metadata from legal PDF documents (court orders, judgments, legal notices, FIR copies, government gazettes) for indexing in Qdrant and for analysis by CrewAI agents.

### Documentation

| Resource | URL |
|---|---|
| **PyMuPDF** | |
| Official Docs | https://pymupdf.readthedocs.io/ |
| Quick Start | https://pymupdf.readthedocs.io/en/latest/tutorial.html |
| API Reference | https://pymupdf.readthedocs.io/en/latest/module.html |
| GitHub | https://github.com/pymupdf/PyMuPDF |
| PyPI | https://pypi.org/project/PyMuPDF/ |
| **pdfplumber** | |
| Official Docs / README | https://github.com/jsvine/pdfplumber |
| PyPI | https://pypi.org/project/pdfplumber/ |
| Wiki | https://github.com/jsvine/pdfplumber/wiki |

### Version
- **PyMuPDF:** `>= 1.25.x` (`pip install PyMuPDF`) -- import as `fitz` or `pymupdf`
- **pdfplumber:** `>= 0.11.x` (`pip install pdfplumber`)

### When to Use Which

| Feature | PyMuPDF (`fitz`) | pdfplumber |
|---|---|---|
| Text extraction speed | Very fast (C-based) | Slower (Python-based) |
| Table extraction | Basic | Excellent (built-in) |
| Image extraction | Yes | No |
| PDF creation/editing | Yes | No (read-only) |
| Scanned PDFs (OCR) | Yes (with Tesseract) | No |
| Indian language PDFs | Good Unicode support | Good Unicode support |
| Memory usage | Lower | Higher |

**Recommendation:** Use **PyMuPDF** as the primary PDF processor for speed and versatility. Use **pdfplumber** specifically when you need accurate table extraction from legal documents (e.g., charge sheets with tabular data, court fee schedules).

### Key Concepts for Our Use Case

- **Legal Document Parsing:** Extract text from court judgments, FIR copies, and legal notices while preserving structure (headings, paragraphs, numbered sections).
- **Table Extraction:** Legal documents often contain tables (charge details, witness lists, evidence lists). Use pdfplumber for these.
- **Metadata Extraction:** Extract PDF metadata (title, author, creation date) for indexing.
- **Scanned Document OCR:** Many Indian court documents are scanned PDFs. Use PyMuPDF + Tesseract for OCR with Indian language support.
- **Text Chunking:** After extraction, chunk text into appropriate sizes for embedding and storage in Qdrant.

### Integration Patterns

```python
import fitz  # PyMuPDF
import pdfplumber
from typing import List, Dict

def extract_text_pymupdf(pdf_path: str) -> List[Dict]:
    """Extract text from PDF using PyMuPDF, preserving page structure."""
    doc = fitz.open(pdf_path)
    pages = []
    for page_num, page in enumerate(doc):
        text = page.get_text("text")
        pages.append({
            "page_number": page_num + 1,
            "text": text,
            "metadata": {
                "page_count": len(doc),
                "title": doc.metadata.get("title", ""),
                "author": doc.metadata.get("author", ""),
            }
        })
    doc.close()
    return pages

def extract_tables_pdfplumber(pdf_path: str) -> List[Dict]:
    """Extract tables from legal PDFs using pdfplumber."""
    tables = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages):
            page_tables = page.extract_tables()
            for table_idx, table in enumerate(page_tables):
                tables.append({
                    "page": page_num + 1,
                    "table_index": table_idx,
                    "data": table,
                })
    return tables

def process_legal_pdf(pdf_path: str) -> Dict:
    """Complete legal PDF processing pipeline."""
    # Extract text with PyMuPDF (fast)
    pages = extract_text_pymupdf(pdf_path)

    # Extract tables with pdfplumber (accurate)
    tables = extract_tables_pdfplumber(pdf_path)

    # Chunk text for Qdrant ingestion
    chunks = chunk_legal_text(pages)

    return {
        "pages": pages,
        "tables": tables,
        "chunks": chunks,
    }

# FastAPI endpoint for PDF upload and processing
@app.post("/api/upload-document")
async def upload_document(file: UploadFile):
    contents = await file.read()
    # Save temporarily and process
    temp_path = f"/tmp/{file.filename}"
    with open(temp_path, "wb") as f:
        f.write(contents)

    result = process_legal_pdf(temp_path)

    # Index chunks in Qdrant
    await index_in_qdrant(result["chunks"])

    return {"status": "processed", "pages": len(result["pages"]), "tables": len(result["tables"])}
```

### Gotchas and Limitations

- **Scanned PDFs:** Many Indian court documents are scanned images, not searchable text. PyMuPDF alone won't extract text -- you need OCR (Tesseract with `hindi`, `bengali`, `tamil`, etc. trained models).
- **Encoding issues:** Some older Indian government PDFs use non-standard encodings or custom fonts. Text extraction may produce garbage characters. Test with a variety of real legal documents.
- **Table extraction quality:** pdfplumber's table extraction works best with clearly bordered tables. Borderless or poorly formatted tables (common in government documents) may not extract correctly.
- **Large PDFs:** Court judgments can be 100+ pages. Process in chunks to avoid memory issues. Use `page.get_text()` per page rather than extracting entire document at once.
- **PyMuPDF import name:** The package is installed as `PyMuPDF` but imported as `fitz` (legacy name) or `pymupdf`. This confuses many developers.
- **pdfplumber memory:** pdfplumber can consume significant memory on large PDFs. Always use context managers (`with pdfplumber.open(...) as pdf:`) and process one page at a time.
- **PDF/A compliance:** Some court-issued PDFs are PDF/A format. Both libraries handle these, but test specifically with your target documents.

---

## 10. Jinja2 - Template Engine for Document Drafting

### Role in Our System
Powers the legal document generation system. Maintains templates for common Indian legal documents (FIRs, bail applications, legal notices, complaints, affidavits, petitions) and fills them with data from the AI analysis pipeline.

### Documentation

| Resource | URL |
|---|---|
| Official Docs | https://jinja.palletsprojects.com/ |
| Template Designer Docs | https://jinja.palletsprojects.com/en/stable/templates/ |
| API Reference | https://jinja.palletsprojects.com/en/stable/api/ |
| GitHub | https://github.com/pallets/jinja |
| PyPI | https://pypi.org/project/Jinja2/ |
| Sandbox | https://jinja.palletsprojects.com/en/stable/sandbox/ |

### Version
- **Jinja2:** `>= 3.1.x` (`pip install Jinja2`)
- Note: Jinja2 is already a dependency of FastAPI (via Starlette), so it is likely already installed.

### Key Concepts for Our Use Case

- **Template Inheritance:** Create a base legal document template with common structure (header, footer, signature blocks) and extend it for specific document types.
- **Filters:** Custom Jinja2 filters for legal formatting (date formatting to Indian standard DD/MM/YYYY, currency in INR, ordinal numbers).
- **Macros:** Reusable macros for common legal clauses, sections, and boilerplate text.
- **Internationalization:** Templates that can render in multiple Indian languages using the translated content from Sarvam AI.
- **Autoescaping:** Enable autoescaping when generating HTML documents. Disable for plain text / LaTeX legal documents.

### Integration Patterns

```python
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pathlib import Path

# Setup Jinja2 environment for legal templates
template_dir = Path("templates/legal")
env = Environment(
    loader=FileSystemLoader(template_dir),
    autoescape=select_autoescape(["html"]),  # Autoescape HTML only
    trim_blocks=True,
    lstrip_blocks=True,
)

# Custom filters for Indian legal documents
def format_indian_date(date_obj):
    return date_obj.strftime("%d/%m/%Y")

def format_inr(amount):
    # Indian number formatting (e.g., 1,00,000)
    s = str(int(amount))
    if len(s) <= 3:
        return s
    last3 = s[-3:]
    rest = s[:-3]
    formatted = ""
    while len(rest) > 2:
        formatted = "," + rest[-2:] + formatted
        rest = rest[:-2]
    formatted = rest + formatted
    return formatted + "," + last3

env.filters["indian_date"] = format_indian_date
env.filters["inr"] = format_inr

# Render a legal document
def draft_legal_document(template_name: str, data: dict) -> str:
    """Generate a legal document from template and data."""
    template = env.get_template(template_name)
    return template.render(**data)

# Example: FIR draft
fir_content = draft_legal_document("fir_template.html", {
    "complainant_name": "Rajesh Kumar",
    "date_of_incident": datetime(2026, 2, 15),
    "description": "Theft of mobile phone from residence",
    "police_station": "Saket Police Station, New Delhi",
    "applicable_sections": ["Section 303 BNS (Theft)", "Section 331 BNS (Trespass)"],
})

# FastAPI endpoint for document generation
@app.post("/api/draft-document")
async def draft_document(req: DocumentDraftRequest):
    content = draft_legal_document(req.template_name, req.data)
    return {"document_html": content}
```

**Example Template: `templates/legal/fir_template.html`**

```html
{% extends "base_legal_document.html" %}

{% block title %}First Information Report (FIR){% endblock %}

{% block content %}
<div class="legal-document">
  <h1>FIRST INFORMATION REPORT</h1>
  <p><strong>Police Station:</strong> {{ police_station }}</p>
  <p><strong>Date:</strong> {{ date_of_incident | indian_date }}</p>

  <h2>Complainant Details</h2>
  <p><strong>Name:</strong> {{ complainant_name }}</p>

  <h2>Description of Incident</h2>
  <p>{{ description }}</p>

  <h2>Applicable Legal Provisions</h2>
  <ul>
    {% for section in applicable_sections %}
    <li>{{ section }}</li>
    {% endfor %}
  </ul>

  {% block signature %}
  <div class="signature-block">
    <p>Signature of Complainant: ___________________</p>
    <p>Date: {{ "now" | indian_date }}</p>
  </div>
  {% endblock %}
</div>
{% endblock %}
```

### Gotchas and Limitations

- **Security (SSTI):** NEVER pass user input directly as a template string. Always use pre-defined template files and only pass data as context variables. Server-Side Template Injection (SSTI) is a critical vulnerability.
- **Sandboxing:** For any user-customizable templates, use `jinja2.sandbox.SandboxedEnvironment` to prevent arbitrary code execution.
- **Unicode/Indic scripts:** Jinja2 handles Unicode natively, but ensure your output rendering (HTML, PDF) correctly displays Devanagari, Tamil, Bengali, and other scripts. Use UTF-8 encoding everywhere.
- **PDF generation:** Jinja2 generates text/HTML, not PDF directly. To produce PDF documents, pair with `weasyprint` or `xhtml2pdf` to convert HTML templates to PDF.
- **Template management:** As the number of legal templates grows, organize them with a clear directory structure:
  ```
  templates/legal/
    base_legal_document.html
    fir/
      fir_template.html
      fir_template_hi.html  (Hindi version)
    bail/
      bail_application.html
    notice/
      legal_notice.html
    petition/
      writ_petition.html
  ```
- **Whitespace control:** Legal documents are formatting-sensitive. Use `trim_blocks` and `lstrip_blocks` in the Environment, and `{%-` / `-%}` in templates to control whitespace precisely.

---

## 11. Integration Architecture Overview

```
                        +-------------------+
                        |    Next.js / React |
                        |    Frontend        |
                        |  (Port 3000)       |
                        +--------+----------+
                                 |
                                 | HTTP / WebSocket
                                 |
                        +--------v----------+
                        |     FastAPI        |
                        |  Backend API       |
                        |  (Port 8000)       |
                        +--------+----------+
                                 |
              +------------------+------------------+
              |                  |                  |
    +---------v------+  +-------v--------+  +------v-------+
    |   CrewAI       |  |  LangChain     |  |  Jinja2      |
    |   Multi-Agent  |  |  RAG Pipeline  |  |  Document    |
    |   Orchestration|  |  + LangGraph   |  |  Templates   |
    +-------+--------+  +-------+--------+  +--------------+
            |                    |
            |            +-------v--------+
            |            |    Qdrant      |
            |            |  Vector DB     |
            |            |  (Port 6333)   |
            |            +----------------+
            |
    +-------+--------+-------+--------+
    |                |                 |
+---v----+    +------v------+   +-----v------+
|Sarvam  |    |  SERP API   |   | PyMuPDF /  |
|AI API  |    |  (Google    |   | pdfplumber |
|(Transl)|    |   Search)   |   | (PDF Proc) |
+--------+    +-------------+   +------------+

                        +-------------------+
                        |    Thesys API     |
                        | (Visual UI Gen)   |
                        +-------------------+
                              ^
                              | Called from
                              | Frontend or Backend
```

### Data Flow for a Typical Legal Query

1. **User** submits query in any Indian language via **Next.js** frontend.
2. **FastAPI** receives the request, detects language, and (if not English) sends to **Sarvam AI** for translation to English.
3. **FastAPI** triggers **CrewAI** crew with the translated query.
4. **CrewAI Legal Researcher Agent** uses **LangChain RAG** pipeline to search **Qdrant** for relevant legal provisions.
5. **CrewAI Case Analyzer Agent** analyzes retrieved context and produces legal analysis.
6. **CrewAI Document Drafter Agent** (if needed) uses **Jinja2** templates to draft legal documents.
7. **CrewAI Nearby Resources Agent** uses **SERP API** to find local lawyers/courts.
8. Results are translated back to user's language via **Sarvam AI**.
9. **Thesys API** generates visual components (flowcharts, decision trees) for the response.
10. **FastAPI** sends structured response to **Next.js** frontend for rendering.

---

## 12. Recommended Installation Order

### Backend (Python)

```bash
# 1. Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# or: venv\Scripts\activate  # Windows

# 2. Core framework
pip install "fastapi[standard]"

# 3. LLM orchestration
pip install langchain langchain-core langchain-community langchain-openai langchain-qdrant
pip install langgraph

# 4. Multi-agent framework
pip install "crewai[tools]"

# 5. Vector database client
pip install qdrant-client

# 6. PDF processing
pip install PyMuPDF pdfplumber

# 7. Template engine (likely already installed via FastAPI)
pip install Jinja2

# 8. SERP API client
pip install google-search-results

# 9. HTTP client for external APIs (Sarvam AI, Thesys)
pip install httpx

# 10. Additional utilities
pip install python-dotenv python-multipart
```

### Frontend (Node.js)

```bash
# 1. Create Next.js project
npx create-next-app@latest legal-ai-frontend --typescript --tailwind --app

# 2. Install dependencies
cd legal-ai-frontend
npm install axios               # HTTP client
npm install @tanstack/react-query  # Server state management
npm install zustand              # Client state management
npm install next-intl            # Internationalization
```

### Infrastructure

```bash
# Qdrant via Docker
docker pull qdrant/qdrant
docker run -p 6333:6333 -p 6334:6334 \
    -v $(pwd)/qdrant_storage:/qdrant/storage \
    qdrant/qdrant
```

---

## Version Summary Table

| Technology | Package Name | Recommended Version | Install Command |
|---|---|---|---|
| Qdrant Server | `qdrant/qdrant` (Docker) | `>= 1.13.x` | `docker pull qdrant/qdrant` |
| Qdrant Client | `qdrant-client` | `>= 1.13.0` | `pip install qdrant-client` |
| FastAPI | `fastapi` | `>= 0.115.x` | `pip install "fastapi[standard]"` |
| CrewAI | `crewai` | `>= 0.105.x` | `pip install "crewai[tools]"` |
| Next.js | `next` | `>= 15.x` | `npx create-next-app@latest` |
| React | `react` | `>= 19.x` | Bundled with Next.js 15 |
| LangChain | `langchain` | `>= 0.3.x` | `pip install langchain` |
| LangGraph | `langgraph` | `>= 0.3.x` | `pip install langgraph` |
| LangChain-Qdrant | `langchain-qdrant` | `>= 0.2.x` | `pip install langchain-qdrant` |
| PyMuPDF | `PyMuPDF` | `>= 1.25.x` | `pip install PyMuPDF` |
| pdfplumber | `pdfplumber` | `>= 0.11.x` | `pip install pdfplumber` |
| Jinja2 | `Jinja2` | `>= 3.1.x` | `pip install Jinja2` |
| SERP API | `google-search-results` | `>= 2.4.2` | `pip install google-search-results` |
| Sarvam AI | REST API / SDK | Latest | See docs.sarvam.ai |
| Thesys | REST API / SDK | Latest | See thesys.ai |

---

## Environment Variables Required

```bash
# .env file (NEVER commit this to git)

# LLM Provider
OPENAI_API_KEY=sk-...
# or
ANTHROPIC_API_KEY=sk-ant-...

# Qdrant
QDRANT_URL=http://localhost:6333
QDRANT_API_KEY=           # Only if using Qdrant Cloud

# Sarvam AI
SARVAM_API_KEY=your-sarvam-api-key

# SERP API
SERP_API_KEY=your-serp-api-key

# Thesys
THESYS_API_KEY=your-thesys-api-key

# LangSmith (optional, for tracing)
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=your-langsmith-api-key
LANGCHAIN_PROJECT=indian-legal-ai

# App Config
APP_ENV=development
FASTAPI_PORT=8000
NEXT_PUBLIC_API_URL=http://localhost:8000
```

---

## Key External References for Indian Legal Domain

| Resource | URL | Purpose |
|---|---|---|
| India Code (Official) | https://www.indiacode.nic.in/ | All central acts including BNS, BNSS, BSA |
| Supreme Court of India | https://main.sci.gov.in/ | Supreme Court judgments |
| Indian Kanoon | https://indiankanoon.org/ | Legal search engine for case law |
| National Legal Services Authority | https://nalsa.gov.in/ | Legal aid information |
| eCourts | https://ecourts.gov.in/ | Court case status |
| Bharatiya Nyaya Sanhita (BNS) | https://www.indiacode.nic.in/handle/123456789/20062 | Replacement for IPC |

---

> **Disclaimer:** This document was compiled on 2026-02-17. Technology versions and documentation URLs may have changed. Always verify against the official sources before production deployment. Version numbers are approximate minimums -- check PyPI and official releases for the exact latest stable versions.
