# Neethi AI — FastAPI Documentation Guide

**Base URL (Development):** `http://localhost:8000/api/v1`
**Base URL (Production):** `https://api.neethiai.com/api/v1`
**OpenAPI Docs:** `http://localhost:8000/docs` (Swagger UI)
**ReDoc:** `http://localhost:8000/redoc`

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Application Entry Point](#2-application-entry-point)
3. [Authentication](#3-authentication)
4. [Query Endpoints](#4-query-endpoints)
5. [Cases Endpoints](#5-cases-endpoints)
6. [Document Drafting Endpoints](#6-document-drafting-endpoints)
7. [Sections & Acts Endpoints](#7-sections--acts-endpoints)
8. [Nearby Legal Resources](#8-nearby-legal-resources)
9. [Translation Endpoints](#9-translation-endpoints)
10. [Voice Endpoints (TTS / STT)](#10-voice-endpoints-tts--stt)
11. [Admin Endpoints](#11-admin-endpoints)
12. [WebSocket / SSE Streaming](#12-websocket--sse-streaming)
13. [Pydantic Schemas Reference](#13-pydantic-schemas-reference)
14. [Error Responses](#14-error-responses)
15. [Rate Limiting](#15-rate-limiting)
16. [Middleware Stack](#16-middleware-stack)
17. [Role-Based Access Control](#17-role-based-access-control)
18. [Environment Variables](#18-environment-variables)
18. [Project File Map](#18-project-file-map)

---

## 1. Architecture Overview

Neethi AI uses a **CrewAI-centric** architecture. The FastAPI layer is a thin HTTP wrapper — it receives requests, validates them, passes them to the agent system, and streams or returns the result.

```
Client Request
      │
      ▼
FastAPI Router (backend/api/routes/)
      │  ← JWT validation (dependency)
      │  ← Role-based access check (dependency)
      │  ← Redis cache check (transparent)
      ▼
handle_query() ← backend/agents/query_router.py
      │
      ▼
Tier 1 (Pattern match, 0 LLM calls)
      OR
Tier 3 (Full CrewAI pipeline)
      │
      ▼
get_crew_for_role(user_role)
      │
      ├── citizen      → Layman Crew     (QueryAnalyst → Retrieval → Citation → Format)
      ├── lawyer       → Lawyer Crew     (QueryAnalyst → Retrieval → IRAC → Citation → Format)
      ├── legal_advisor→ Advisor Crew    (QueryAnalyst → Retrieval → IRAC → Citation → Format)
      └── police       → Police Crew     (QueryAnalyst → Retrieval → Citation → Format)
```

**Key design principle:** The REST layer never generates legal answers itself. It always delegates to the agent pipeline, which enforces statute normalization → retrieval → citation verification → formatting in strict order.

---

## 2. Application Entry Point

**File:** `backend/main.py` *(to be created)*

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from backend.api.routes import auth, query, cases, documents, sections, resources, translate, admin
from backend.db.database import create_all_tables
from backend.services.cache import ResponseCache

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await create_all_tables()          # Dev only — use Alembic in prod
    app.state.cache = ResponseCache()
    yield
    # Shutdown (cleanup if needed)

app = FastAPI(
    title="Neethi AI Legal API",
    description="Indian Legal Domain Agentic AI — citation-verified, hallucination-free.",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# Middleware (applied in order — outermost first)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "https://neethiai.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount routers — all under /api/v1
PREFIX = "/api/v1"
app.include_router(auth.router,      prefix=f"{PREFIX}/auth",      tags=["Authentication"])
app.include_router(query.router,     prefix=f"{PREFIX}/query",     tags=["Legal Query"])
app.include_router(cases.router,     prefix=f"{PREFIX}/cases",     tags=["Case Law"])
app.include_router(documents.router, prefix=f"{PREFIX}/documents", tags=["Document Drafting"])
app.include_router(sections.router,  prefix=f"{PREFIX}/sections",  tags=["Acts & Sections"])
app.include_router(resources.router, prefix=f"{PREFIX}/resources", tags=["Legal Resources"])
app.include_router(translate.router, prefix=f"{PREFIX}/translate", tags=["Translation"])
app.include_router(admin.router,     prefix=f"{PREFIX}/admin",     tags=["Admin"])
```

---

## 3. Authentication

All endpoints except `/auth/register` and `/auth/login` require a **Bearer JWT token** in the `Authorization` header.

```
Authorization: Bearer <token>
```

---

### POST `/auth/register`

Register a new user with a role.

**Request Body:**
```json
{
  "full_name": "Arjun Sharma",
  "email": "arjun@example.com",
  "password": "Secure@1234",
  "role": "lawyer",
  "bar_council_id": "BAR/MH/2019/12345"
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `full_name` | string | Yes | 2–100 characters |
| `email` | string | Yes | Unique, valid email |
| `password` | string | Yes | Min 8 chars, 1 uppercase, 1 digit |
| `role` | string | Yes | `citizen` \| `lawyer` \| `legal_advisor` \| `police` |
| `bar_council_id` | string | Conditional | Required if role = `lawyer` |
| `police_badge_id` | string | Conditional | Required if role = `police` |
| `organization` | string | No | For `legal_advisor` |

**Response `201 Created`:**
```json
{
  "user_id": "usr_01J9XK2M3N4P5Q6R7S8T9U0V",
  "email": "arjun@example.com",
  "role": "lawyer",
  "created_at": "2026-02-25T10:30:00Z",
  "message": "Registration successful. Please verify your email."
}
```

**Response `409 Conflict`:**
```json
{ "detail": "Email already registered." }
```

---

### POST `/auth/login`

Authenticate and receive a JWT access token.

**Request Body:**
```json
{
  "email": "arjun@example.com",
  "password": "Secure@1234"
}
```

**Response `200 OK`:**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "expires_in": 86400,
  "user": {
    "user_id": "usr_01J9XK2M3N4P5Q6R7S8T9U0V",
    "full_name": "Arjun Sharma",
    "email": "arjun@example.com",
    "role": "lawyer"
  }
}
```

**Response `401 Unauthorized`:**
```json
{ "detail": "Invalid email or password." }
```

**Notes:**
- Token expiry: 24 hours (configurable via `JWT_EXPIRY_HOURS` env var)
- Algorithm: HS256 with `JWT_SECRET_KEY`
- The `role` field inside the token is read-only — users cannot change their own role

---

### POST `/auth/refresh`

Exchange a still-valid token for a new one (sliding session).

**Headers:** `Authorization: Bearer <token>`

**Response `200 OK`:**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "expires_in": 86400
}
```

---

### POST `/auth/logout`

Invalidate the current token (adds it to a server-side blocklist in Redis).

**Headers:** `Authorization: Bearer <token>`

**Response `204 No Content`**

---

### GET `/auth/me`

Get the currently authenticated user's profile.

**Headers:** `Authorization: Bearer <token>`

**Response `200 OK`:**
```json
{
  "user_id": "usr_01J9XK2M3N4P5Q6R7S8T9U0V",
  "full_name": "Arjun Sharma",
  "email": "arjun@example.com",
  "role": "lawyer",
  "bar_council_id": "BAR/MH/2019/12345",
  "created_at": "2026-02-25T10:30:00Z",
  "query_count_today": 12,
  "rate_limit_remaining": 38
}
```

---

## 4. Query Endpoints

The core of Neethi AI. All query endpoints invoke the full CrewAI pipeline (or a fast Tier-1 pattern match for simple section lookups).

---

### POST `/query/ask`

Submit a legal query and receive the complete verified response. **Blocking** — waits for full pipeline to complete.

**Headers:** `Authorization: Bearer <token>`

**Request Body:**
```json
{
  "query": "What is the punishment for murder under the new criminal laws?",
  "language": "en",
  "include_precedents": true
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `query` | string | Yes | 10–2000 characters |
| `language` | string | No | `en` (default) \| `hi` \| `ta` \| `te` \| `kn` \| `ml` \| `bn` \| `mr` |
| `include_precedents` | boolean | No | `true` forces SC judgment search (lawyer crew only) |

**Response `200 OK`:**
```json
{
  "query_id": "qry_01J9XK2M3N4P5Q6R",
  "query": "What is the punishment for murder under the new criminal laws?",
  "response": "**Murder under BNS 2023**\n\nUnder the Bharatiya Nyaya Sanhita (BNS) 2023...",
  "verification_status": "VERIFIED",
  "confidence": "high",
  "citations": [
    {
      "act_code": "BNS_2023",
      "section_number": "103",
      "section_title": "Murder — Punishment",
      "verification": "VERIFIED"
    },
    {
      "act_code": "BNS_2023",
      "section_number": "101",
      "section_title": "Murder",
      "verification": "VERIFIED"
    }
  ],
  "precedents": [
    {
      "case_name": "Balu Sudam Khalde v. State of Maharashtra",
      "year": "2023",
      "court": "Supreme Court of India",
      "citation": "(2023) SCC Online SC 481",
      "verification": "VERIFIED"
    }
  ],
  "user_role": "lawyer",
  "processing_time_ms": 4820,
  "cached": false,
  "disclaimer": "This is AI-assisted legal information. Consult a qualified legal professional for advice specific to your situation."
}
```

**Response fields:**

| Field | Description |
|---|---|
| `query_id` | Unique identifier for this query (for feedback/logging) |
| `response` | Full formatted response (Markdown) |
| `verification_status` | `VERIFIED` \| `PARTIALLY_VERIFIED` \| `UNVERIFIED` |
| `confidence` | `high` \| `medium` \| `low` — from the LegalReasoner agent |
| `citations` | Array of verified statutory citations |
| `precedents` | Array of verified SC judgments (lawyer/advisor only) |
| `cached` | `true` if response was served from Redis cache |
| `processing_time_ms` | Total pipeline duration in milliseconds |

**Role-based routing (automatic, based on JWT):**

| Role | Pipeline | Output Style |
|---|---|---|
| `citizen` | QueryAnalyst → Retrieval → Citation → Format | Plain English, step-by-step |
| `lawyer` | QueryAnalyst → Retrieval → IRAC → Citation → Format | IRAC analysis, technical |
| `legal_advisor` | QueryAnalyst → Retrieval → IRAC → Citation → Format | Compliance focus, risk |
| `police` | QueryAnalyst → Retrieval → Citation → Format | Procedural steps, cognizable/bailable |

---

### POST `/query/ask/stream`

Same as `/query/ask` but uses **Server-Sent Events (SSE)** to stream the response as it's generated. The frontend can display tokens in real time as the agent pipeline completes each step.

**Headers:**
```
Authorization: Bearer <token>
Accept: text/event-stream
```

**Request Body:** Same as `/query/ask`

**Response:** `text/event-stream`

The server sends a sequence of SSE events:

```
event: agent_start
data: {"agent": "QueryAnalyst", "message": "Classifying your query..."}

event: agent_start
data: {"agent": "RetrievalSpecialist", "message": "Searching legal database..."}

event: agent_start
data: {"agent": "LegalReasoner", "message": "Applying IRAC analysis..."}

event: agent_start
data: {"agent": "CitationChecker", "message": "Verifying citations..."}

event: token
data: {"text": "**Murder under BNS 2023**\n\n"}

event: token
data: {"text": "Under the Bharatiya Nyaya Sanhita..."}

event: complete
data: {
  "query_id": "qry_01J9XK2M3N4P5Q6R",
  "verification_status": "VERIFIED",
  "confidence": "high",
  "citations": [...],
  "precedents": [...],
  "cached": false
}

event: end
data: {}
```

**Event types:**

| Event | Payload | Description |
|---|---|---|
| `agent_start` | `{agent, message}` | An agent in the pipeline has started |
| `agent_complete` | `{agent, duration_ms}` | An agent has finished |
| `token` | `{text}` | A chunk of the response text |
| `citation_verified` | `{act_code, section_number, status}` | Real-time verification result |
| `complete` | Full metadata object | Pipeline complete, full metadata |
| `error` | `{code, detail}` | An error occurred — stream ends |
| `end` | `{}` | Stream is closed |

**Frontend (Next.js) integration:**
```javascript
const eventSource = new EventSource('/api/v1/query/ask/stream', {
  headers: { Authorization: `Bearer ${token}` }
});

eventSource.addEventListener('token', (e) => {
  const { text } = JSON.parse(e.data);
  setResponse(prev => prev + text);
});

eventSource.addEventListener('complete', (e) => {
  const metadata = JSON.parse(e.data);
  setCitations(metadata.citations);
  setVerificationStatus(metadata.verification_status);
  eventSource.close();
});
```

---

### GET `/query/history`

Get the authenticated user's recent query history.

**Query Parameters:**

| Param | Type | Default | Description |
|---|---|---|---|
| `limit` | int | `10` | Max results (1–50) |
| `offset` | int | `0` | Pagination offset |
| `from_date` | date | — | Filter from date (YYYY-MM-DD) |

**Response `200 OK`:**
```json
{
  "total": 47,
  "queries": [
    {
      "query_id": "qry_01J9XK2M3N4P5Q6R",
      "query_text": "What is the punishment for murder under the new criminal laws?",
      "verification_status": "VERIFIED",
      "confidence": "high",
      "created_at": "2026-02-25T10:30:00Z"
    }
  ]
}
```

---

### GET `/query/{query_id}`

Retrieve a previously submitted query and its full response.

**Path Parameter:** `query_id` — the ID returned by `/query/ask`

**Response `200 OK`:** Same schema as `/query/ask` response.

**Response `404 Not Found`:** If query does not belong to the authenticated user.

---

### POST `/query/feedback`

Submit user feedback on a response (used to improve prompts and flag hallucinations).

**Request Body:**
```json
{
  "query_id": "qry_01J9XK2M3N4P5Q6R",
  "rating": 4,
  "feedback_type": "citation_wrong",
  "comment": "BNS 103 was cited but the section title shown was incorrect."
}
```

| Field | Type | Values |
|---|---|---|
| `rating` | int | 1–5 |
| `feedback_type` | string | `helpful` \| `citation_wrong` \| `hallucination` \| `incomplete` \| `language_issue` |
| `comment` | string | Optional, max 500 chars |

**Response `201 Created`:**
```json
{ "feedback_id": "fb_01J9XK2M", "message": "Feedback recorded. Thank you." }
```

---

## 5. Cases Endpoints

Search and analyze Supreme Court judgments and case law.

---

### POST `/cases/search`

Search for relevant Supreme Court judgments.

**Headers:** `Authorization: Bearer <token>`

**Request Body:**
```json
{
  "query": "anticipatory bail murder accused",
  "act_filter": "BNS_2023",
  "top_k": 5,
  "from_year": 2020,
  "to_year": 2026
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `query` | string | Yes | Legal search terms |
| `act_filter` | string | No | Filter by act: `BNS_2023` \| `BNSS_2023` etc. |
| `top_k` | int | No | 1–10, default 5 |
| `from_year` | int | No | Filter by judgment year |
| `to_year` | int | No | Filter by judgment year |

**Response `200 OK`:**
```json
{
  "results": [
    {
      "case_name": "Balu Sudam Khalde v. State of Maharashtra",
      "citation": "(2023) SCC Online SC 481",
      "court": "Supreme Court of India",
      "judgment_date": "2023-09-15",
      "judges": ["Justice D.Y. Chandrachud", "Justice J.B. Pardiwala"],
      "legal_domain": "criminal_substantive",
      "relevance_score": 0.92,
      "summary": "SC reaffirmed the five Exceptions to murder under provocation doctrine...",
      "sections_cited": ["BNS_2023/101", "BNS_2023/103", "BNS_2023/105"]
    }
  ],
  "total_found": 3,
  "search_time_ms": 340
}
```

**Access:** All roles can search cases, but `citizen` role sees simplified summaries only.

---

### POST `/cases/analyze`

Deep IRAC analysis of a specific case or case scenario. **Lawyer / legal_advisor only.**

**Headers:** `Authorization: Bearer <token>` (role must be `lawyer` or `legal_advisor`)

**Request Body:**
```json
{
  "scenario": "Accused killed victim during a sudden quarrel without premeditation. Prosecution charges under BNS 103.",
  "case_citation": "(2023) SCC Online SC 481",
  "applicable_acts": ["BNS_2023"]
}
```

**Response `200 OK`:**
```json
{
  "irac_analysis": {
    "issue": "Whether the killing during sudden quarrel qualifies as murder under BNS 103 or culpable homicide not amounting to murder under BNS 105.",
    "rule": "BNS 103 defines murder as culpable homicide with intent...\nBNS 105 Exception 4 covers grave and sudden provocation...",
    "application": "In Balu Sudam Khalde (2023), the SC held that...",
    "conclusion": "The accused may be entitled to the benefit of Exception 4 of BNS 105 if..."
  },
  "applicable_sections": [
    { "act_code": "BNS_2023", "section_number": "103", "verification": "VERIFIED" },
    { "act_code": "BNS_2023", "section_number": "105", "verification": "VERIFIED" }
  ],
  "applicable_precedents": [
    {
      "case_name": "Balu Sudam Khalde v. State of Maharashtra",
      "year": "2023",
      "relevance": "Directly applicable — SC on Exception 4 provocation test"
    }
  ],
  "confidence": "high",
  "verification_status": "VERIFIED"
}
```

**Response `403 Forbidden`:** If role is `citizen` or `police`.

---

### GET `/cases/{case_id}`

Retrieve the full text of a specific indexed judgment.

**Path Parameter:** `case_id` — internal ID of the case in Qdrant

**Response `200 OK`:**
```json
{
  "case_id": "sc_balu_sudam_khalde_2023",
  "case_name": "Balu Sudam Khalde v. State of Maharashtra",
  "citation": "(2023) SCC Online SC 481",
  "court": "Supreme Court of India",
  "judgment_date": "2023-09-15",
  "judges": ["Justice D.Y. Chandrachud"],
  "full_text": "JUDGMENT\n\nThis appeal arises from...",
  "sections_cited": ["BNS_2023/101", "BNS_2023/103", "BNS_2023/105"],
  "headnotes": ["Murder — Exception 4 — Grave and sudden provocation..."],
  "indexed_at": "2026-01-10T08:00:00Z"
}
```

---

## 6. Document Drafting Endpoints

Generate legally formatted draft documents. Uses Claude Sonnet for high-quality legal prose.

---

### GET `/documents/templates`

List all available document templates.

**Response `200 OK`:**
```json
{
  "templates": [
    {
      "template_id": "bail_application",
      "template_name": "Bail Application",
      "description": "Application for regular bail under BNSS Section 480",
      "required_fields": ["accused_name", "fir_number", "police_station", "offence_sections", "grounds"],
      "optional_fields": ["surety_details", "previous_bail_history"],
      "jurisdiction": "all",
      "language": "en",
      "access_roles": ["lawyer", "legal_advisor"]
    },
    {
      "template_id": "legal_notice",
      "template_name": "Legal Notice",
      "description": "Formal legal notice for demand or grievance",
      "required_fields": ["sender_name", "receiver_name", "sender_address", "receiver_address", "subject", "demand", "notice_period_days"],
      "optional_fields": ["lawyer_name", "bar_council_id"],
      "jurisdiction": "all",
      "language": "en",
      "access_roles": ["citizen", "lawyer", "legal_advisor"]
    },
    {
      "template_id": "fir_complaint",
      "template_name": "FIR Draft / Complaint",
      "description": "Draft complaint to be converted to FIR at police station",
      "required_fields": ["complainant_name", "complainant_address", "incident_date", "incident_location", "accused_details", "incident_description"],
      "optional_fields": ["witnesses", "evidence_list"],
      "jurisdiction": "all",
      "language": "en",
      "access_roles": ["citizen", "lawyer", "police"]
    },
    {
      "template_id": "anticipatory_bail",
      "template_name": "Anticipatory Bail Application",
      "description": "Application under BNSS Section 482",
      "required_fields": ["accused_name", "fir_number_or_complaint", "police_station", "anticipated_offence_sections", "grounds_for_anticipation"],
      "optional_fields": ["supporting_case_law"],
      "jurisdiction": "all",
      "language": "en",
      "access_roles": ["lawyer", "legal_advisor"]
    },
    {
      "template_id": "power_of_attorney",
      "template_name": "Power of Attorney",
      "description": "General or Special Power of Attorney",
      "required_fields": ["principal_name", "principal_address", "agent_name", "agent_address", "powers_granted", "effective_date"],
      "optional_fields": ["expiry_date", "limitations"],
      "jurisdiction": "all",
      "language": "en",
      "access_roles": ["citizen", "lawyer", "legal_advisor"]
    }
  ]
}
```

**Access:** All roles can list templates, but `access_roles` on each template controls which roles can draft it.

---

### POST `/documents/draft`

Generate a document draft from a template and user-provided fields.

**Headers:** `Authorization: Bearer <token>`

**Request Body:**
```json
{
  "template_id": "bail_application",
  "fields": {
    "accused_name": "Ramesh Kumar",
    "fir_number": "FIR No. 145/2026",
    "police_station": "Bandra (West) Police Station, Mumbai",
    "offence_sections": "BNS 103, BNS 101",
    "grounds": "The accused has been falsely implicated. He has deep roots in the community and there is no risk of flight.",
    "surety_details": "Mr. Suresh Kumar, father, permanent resident of Mumbai"
  },
  "language": "en",
  "include_citations": true
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `template_id` | string | Yes | Must match a template from `/documents/templates` |
| `fields` | object | Yes | Key-value map of required + optional fields |
| `language` | string | No | `en` (default) — see translation endpoint for other languages |
| `include_citations` | boolean | No | Append verified statutory citations at end of document |

**Response `201 Created`:**
```json
{
  "draft_id": "dft_01J9XK2M3N4P5Q6R",
  "template_id": "bail_application",
  "title": "Bail Application — Ramesh Kumar",
  "draft_text": "IN THE COURT OF SESSIONS JUDGE\n\nIN THE MATTER OF:\nRAMESH KUMAR ... Applicant\n\nVERSUS\n\nSTATE OF MAHARASHTRA ... Respondent\n\nAPPLICATION FOR BAIL UNDER SECTION 480 OF BNSS 2023\n\n...",
  "verification_status": "VERIFIED",
  "citations_used": [
    { "act_code": "BNSS_2023", "section_number": "480", "verification": "VERIFIED" }
  ],
  "disclaimer": "DRAFT ONLY — NOT LEGAL ADVICE. This document requires review by a qualified lawyer before filing.",
  "created_at": "2026-02-25T10:30:00Z",
  "word_count": 487
}
```

**Validation errors `422 Unprocessable Entity`:**
```json
{
  "detail": [
    {
      "field": "fir_number",
      "error": "Required field missing for template 'bail_application'"
    }
  ]
}
```

**Role restriction `403 Forbidden`:**
```json
{ "detail": "Template 'bail_application' is not available for role 'citizen'." }
```

---

### GET `/documents/draft/{draft_id}`

Retrieve a previously generated draft.

**Path Parameter:** `draft_id`

**Response `200 OK`:** Same schema as POST `/documents/draft` response.

---

### POST `/documents/draft/{draft_id}/pdf`

Export a draft as a formatted PDF file.

**Path Parameter:** `draft_id`

**Response `200 OK`:**
- `Content-Type: application/pdf`
- `Content-Disposition: attachment; filename="bail_application_ramesh_kumar.pdf"`

The PDF includes:
- Proper Indian legal document formatting
- Header with court name (if applicable)
- Draft watermark: "DRAFT — NOT FOR OFFICIAL USE"
- Footer with generation timestamp and disclaimer

---

### PUT `/documents/draft/{draft_id}`

Update a draft (edit fields and regenerate).

**Request Body:**
```json
{
  "fields": {
    "grounds": "Updated grounds: The accused has cooperated fully with the investigation..."
  }
}
```

**Response `200 OK`:** Updated draft with new `draft_text`.

---

### DELETE `/documents/draft/{draft_id}`

Delete a draft.

**Response `204 No Content`**

---

## 7. Sections & Acts Endpoints

Direct lookup of statutory provisions from the indexed database. These are deterministic (no LLM) and very fast.

---

### GET `/sections/acts`

List all indexed acts.

**Response `200 OK`:**
```json
{
  "acts": [
    {
      "act_code": "BNS_2023",
      "act_name": "Bharatiya Nyaya Sanhita, 2023",
      "short_name": "BNS",
      "era": "naveen_sanhitas",
      "effective_from": "2024-07-01",
      "replaces": ["IPC_1860"],
      "total_sections": 358,
      "indexed_sections": 352
    },
    {
      "act_code": "BNSS_2023",
      "act_name": "Bharatiya Nagarik Suraksha Sanhita, 2023",
      "short_name": "BNSS",
      "era": "naveen_sanhitas",
      "effective_from": "2024-07-01",
      "replaces": ["CrPC_1973"],
      "total_sections": 531,
      "indexed_sections": 528
    },
    {
      "act_code": "BSA_2023",
      "act_name": "Bharatiya Sakshya Adhiniyam, 2023",
      "short_name": "BSA",
      "era": "naveen_sanhitas",
      "effective_from": "2024-07-01",
      "replaces": ["IEA_1872"],
      "total_sections": 170,
      "indexed_sections": 170
    },
    {
      "act_code": "IPC_1860",
      "act_name": "Indian Penal Code, 1860",
      "short_name": "IPC",
      "era": "colonial_codes",
      "effective_from": "1860-01-01",
      "superseded_by": ["BNS_2023"],
      "superseded_on": "2024-07-01",
      "total_sections": 511,
      "indexed_sections": 511
    },
    {
      "act_code": "CrPC_1973",
      "act_name": "Code of Criminal Procedure, 1973",
      "short_name": "CrPC",
      "era": "colonial_codes",
      "effective_from": "1973-04-01",
      "superseded_by": ["BNSS_2023"],
      "superseded_on": "2024-07-01",
      "total_sections": 484,
      "indexed_sections": 484
    }
  ]
}
```

---

### GET `/sections/acts/{act_code}/sections`

List all sections of a specific act (paginated).

**Path Parameter:** `act_code` — e.g., `BNS_2023`

**Query Parameters:**

| Param | Type | Default | Description |
|---|---|---|---|
| `limit` | int | 50 | Max sections per page (1–100) |
| `offset` | int | 0 | Pagination offset |
| `chapter` | string | — | Filter by chapter (e.g., `VI`) |
| `is_offence` | boolean | — | Filter to only offence sections |

**Response `200 OK`:**
```json
{
  "act_code": "BNS_2023",
  "total_sections": 352,
  "sections": [
    {
      "section_number": "103",
      "section_title": "Murder — Punishment",
      "chapter": "VI",
      "is_offence": true,
      "is_cognizable": true,
      "is_bailable": false,
      "triable_by": "Sessions Court"
    }
  ]
}
```

---

### GET `/sections/acts/{act_code}/sections/{section_number}`

Get the full text of a specific section.

**Path Parameters:**
- `act_code` — e.g., `BNS_2023`
- `section_number` — e.g., `103` or `376A` or `53A`

**Response `200 OK`:**
```json
{
  "act_code": "BNS_2023",
  "act_name": "Bharatiya Nyaya Sanhita, 2023",
  "section_number": "103",
  "section_title": "Murder — Punishment",
  "chapter": "VI",
  "chapter_title": "Offences Affecting the Human Body",
  "legal_text": "Whoever commits murder shall be punished with death, or imprisonment for life, and shall also be liable to fine.",
  "is_offence": true,
  "is_cognizable": true,
  "is_bailable": false,
  "triable_by": "Sessions Court",
  "replaces": [{ "act_code": "IPC_1860", "section_number": "302" }],
  "related_sections": ["BNS_2023/100", "BNS_2023/101", "BNS_2023/105"],
  "verification_status": "VERIFIED",
  "extraction_confidence": 0.97
}
```

**Response `404 Not Found`:**
```json
{ "detail": "Section BNS_2023/999 not found in database." }
```

---

### GET `/sections/normalize`

Convert an old statute reference to its new equivalent (IPC/CrPC → BNS/BNSS).

**Query Parameters:**

| Param | Type | Required | Example |
|---|---|---|---|
| `old_act` | string | Yes | `IPC` |
| `old_section` | string | Yes | `302` |

**Example:** `GET /sections/normalize?old_act=IPC&old_section=302`

**Response `200 OK`:**
```json
{
  "input": { "act": "IPC_1860", "section": "302" },
  "mapped_to": { "act": "BNS_2023", "section": "103" },
  "new_section_title": "Murder — Punishment",
  "transition_type": "modified",
  "warning": "CRITICAL: IPC 302 → BNS 103. BNS 302 is Religious Offences — NOT murder. Never conflate these.",
  "effective_from": "2024-07-01",
  "source": "database"
}
```

**Response `200 OK` (no mapping found):**
```json
{
  "input": { "act": "IPC_1860", "section": "999" },
  "mapped_to": null,
  "message": "No mapping found. Section IPC 999 does not exist or has no BNS equivalent."
}
```

---

### POST `/sections/verify`

Batch-verify multiple section citations at once. Used internally by the CitationChecker agent, but also available as an API endpoint for programmatic use.

**Request Body:**
```json
{
  "citations": [
    { "act_code": "BNS_2023", "section_number": "103" },
    { "act_code": "BNS_2023", "section_number": "302" },
    { "act_code": "BNSS_2023", "section_number": "482" }
  ]
}
```

**Response `200 OK`:**
```json
{
  "results": [
    {
      "act_code": "BNS_2023",
      "section_number": "103",
      "status": "VERIFIED",
      "section_title": "Murder — Punishment"
    },
    {
      "act_code": "BNS_2023",
      "section_number": "302",
      "status": "VERIFIED",
      "section_title": "Offences Relating to Religion",
      "warning": "BNS 302 is Religious Offences — NOT murder. Murder is BNS 103."
    },
    {
      "act_code": "BNSS_2023",
      "section_number": "482",
      "status": "VERIFIED",
      "section_title": "Anticipatory Bail"
    }
  ]
}
```

---

## 8. Nearby Legal Resources

Find legal aid centers, courts, lawyers, and police stations near the user's location.

---

### POST `/resources/nearby`

Find nearby legal resources using SERP API geolocation search.

**Headers:** `Authorization: Bearer <token>`

**Request Body:**
```json
{
  "resource_type": "legal_aid",
  "latitude": 19.0760,
  "longitude": 72.8777,
  "radius_km": 10,
  "limit": 5
}
```

| Field | Type | Required | Values |
|---|---|---|---|
| `resource_type` | string | Yes | `legal_aid` \| `court` \| `lawyer` \| `police_station` \| `notary` |
| `latitude` | float | Yes | |
| `longitude` | float | Yes | |
| `radius_km` | int | No | Default 10, max 50 |
| `limit` | int | No | Default 5, max 20 |

**Alternatively, search by city name:**
```json
{
  "resource_type": "court",
  "city": "Mumbai",
  "state": "Maharashtra",
  "limit": 5
}
```

**Response `200 OK`:**
```json
{
  "resource_type": "legal_aid",
  "location": { "latitude": 19.0760, "longitude": 72.8777 },
  "results": [
    {
      "name": "Maharashtra State Legal Services Authority",
      "address": "High Court Building, Fort, Mumbai - 400001",
      "phone": "022-22691100",
      "website": "https://mslsa.gov.in",
      "distance_km": 2.3,
      "open_now": true,
      "services": ["Free legal aid", "Lok Adalat", "Mediation"],
      "rating": 4.1,
      "maps_url": "https://maps.google.com/?q=..."
    }
  ],
  "total_found": 3,
  "note": "Free legal aid is available to citizens with income below ₹3 lakh per annum under the Legal Services Authorities Act."
}
```

**Resource types:**

| Type | Description |
|---|---|
| `legal_aid` | DLSA/SLSA offices — free legal aid for eligible citizens |
| `court` | District courts, sessions courts, high courts |
| `lawyer` | Bar association member lawyers (nearest city only) |
| `police_station` | Nearest police stations |
| `notary` | Registered notaries for document attestation |

---

### GET `/resources/legal-aid/eligibility`

Check if the user is eligible for free legal aid under the Legal Services Authorities Act.

**Query Parameters:**

| Param | Type | Description |
|---|---|---|
| `annual_income` | int | Annual family income in INR |
| `category` | string | `sc` \| `st` \| `woman` \| `child` \| `disabled` \| `general` |
| `state` | string | State code (e.g., `MH`, `DL`, `TN`) |

**Response `200 OK`:**
```json
{
  "eligible": true,
  "basis": "Annual income below ₹3,00,000 threshold",
  "entitlements": [
    "Free legal representation",
    "Court fee waiver",
    "Free copy of court documents"
  ],
  "contact": {
    "authority": "District Legal Services Authority (DLSA)",
    "helpline": "15100",
    "website": "https://nalsa.gov.in"
  }
}
```

---

## 9. Translation Endpoints

Translate legal responses into Indian regional languages using Sarvam AI.

---

### POST `/translate/text`

Translate a text string to a target Indian language.

**Headers:** `Authorization: Bearer <token>`

**Request Body:**
```json
{
  "text": "Murder under BNS Section 103 is punishable with death or imprisonment for life.",
  "source_language": "en",
  "target_language": "hi",
  "domain": "legal"
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `text` | string | Yes | Max 5000 characters |
| `source_language` | string | No | Default `en` |
| `target_language` | string | Yes | See language codes below |
| `domain` | string | No | `legal` (default) — improves legal term preservation |

**Supported languages:**

| Code | Language |
|---|---|
| `hi` | Hindi |
| `ta` | Tamil |
| `te` | Telugu |
| `kn` | Kannada |
| `ml` | Malayalam |
| `bn` | Bengali |
| `mr` | Marathi |
| `gu` | Gujarati |
| `pa` | Punjabi |
| `ur` | Urdu |
| `or` | Odia |

**Response `200 OK`:**
```json
{
  "translated_text": "BNS धारा 103 के तहत हत्या मृत्युदंड या आजीवन कारावास से दंडनीय है।",
  "source_language": "en",
  "target_language": "hi",
  "preserved_terms": ["BNS", "Section 103"],
  "confidence": 0.96,
  "provider": "sarvam_ai"
}
```

**Notes on legal term preservation:**
- Section numbers (`BNS 103`, `BNSS 482`) are never translated — kept as-is
- Act names are transliterated, not translated (`Bharatiya Nyaya Sanhita` stays in Devanagari but the English is kept in brackets)

---

### POST `/translate/query`

Accept a query in any supported Indian language and normalise it to English for pipeline processing.

**Request Body:**
```json
{
  "query": "हत्या की सजा क्या है?",
  "source_language": "hi"
}
```

**Response `200 OK`:**
```json
{
  "original_query": "हत्या की सजा क्या है?",
  "english_query": "What is the punishment for murder?",
  "source_language": "hi",
  "confidence": 0.99
}
```

The frontend should call this endpoint first if the user's query is in a regional language, then pass `english_query` to `/query/ask`.

---

## 10. Voice Endpoints (TTS / STT)

Voice support is powered by **Sarvam AI** — purpose-built for Indian languages. These endpoints enable:
- Citizens who prefer speaking to typing
- Low-literacy users to interact via voice
- Regional language users to query in their mother tongue and hear the answer

**Base path:** `/api/v1/voice`

---

### POST `/voice/speech-to-text`

Transcribe an audio file to text.

**Headers:** `Authorization: Bearer <token>`

**Request:** `multipart/form-data`

| Field | Type | Required | Notes |
|---|---|---|---|
| `file` | audio file | Yes | wav, mp3, ogg, webm, m4a — max 25 MB |
| `language_code` | string | No | BCP-47 code, default `hi-IN` |

**Supported audio formats:** WAV (recommended), MP3, OGG, WebM, M4A

**Supported language codes:**

| Code | Language | Code | Language |
|---|---|---|---|
| `hi-IN` | Hindi | `ta-IN` | Tamil |
| `te-IN` | Telugu | `kn-IN` | Kannada |
| `ml-IN` | Malayalam | `bn-IN` | Bengali |
| `mr-IN` | Marathi | `gu-IN` | Gujarati |
| `pa-IN` | Punjabi | `ur-IN` | Urdu |
| `or-IN` | Odia | `en-IN` | Indian English |

**Response `200 OK`:**
```json
{
  "transcript": "हत्या की सजा क्या है?",
  "language_code": "hi-IN",
  "confidence": 0.97,
  "duration_seconds": 3.2
}
```

**Response `422 Unprocessable Entity`:**
```json
{ "detail": "Could not transcribe audio. Please speak clearly and retry." }
```

**Notes:**
- Maximum audio duration: ~5 minutes
- The transcript is in the same language as the spoken input
- Pass the transcript to `/translate/query` to convert to English before `/query/ask`

---

### POST `/voice/text-to-speech`

Convert text to speech audio.

**Headers:** `Authorization: Bearer <token>`

**Request Body:**
```json
{
  "text": "BNS धारा 103 के तहत हत्या मृत्युदंड या आजीवन कारावास से दंडनीय है।",
  "target_language_code": "hi-IN",
  "speaker": "meera",
  "pitch": 0.0,
  "pace": 1.0,
  "loudness": 1.5,
  "speech_sample_rate": 16000,
  "enable_preprocessing": false
}
```

| Field | Type | Default | Notes |
|---|---|---|---|
| `text` | string | — | Max 3000 characters |
| `target_language_code` | string | `hi-IN` | BCP-47 language code |
| `speaker` | string | `meera` | Voice name (see below) |
| `pitch` | float | `0.0` | -0.5 to +0.5 |
| `pace` | float | `1.0` | 0.5 (slow) to 2.0 (fast) |
| `loudness` | float | `1.5` | 0.5 to 2.0 |
| `speech_sample_rate` | int | `16000` | 8000, 16000, 22050, or 24000 Hz |

**Available speakers:**

| Speaker | Gender | Best for |
|---|---|---|
| `meera` | Female | Hindi, formal legal |
| `pavithra` | Female | Tamil |
| `maitreyi` | Female | General Indian English |
| `arvind` | Male | Hindi |
| `amol` | Male | Marathi |
| `neel` | Male | Bengali |
| `arjun` | Male | General |

**Response `200 OK`:**
- `Content-Type: audio/wav`
- `Content-Disposition: attachment; filename="response.wav"`
- Binary WAV audio data

**Frontend usage:**
```javascript
const resp = await fetch('/api/v1/voice/text-to-speech', {
  method: 'POST',
  headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
  body: JSON.stringify({ text: legalResponse, target_language_code: 'hi-IN' })
});
const audioBlob = await resp.blob();
const audioUrl = URL.createObjectURL(audioBlob);
new Audio(audioUrl).play();
```

---

### POST `/voice/ask`

**Full voice-to-voice legal query pipeline** — the entire journey in one endpoint.

```
Audio Query (user's voice)
     │
     ▼
[Sarvam STT]  →  Transcript
     │
     ▼
[Sarvam Translate]  →  English Query   (if language != English)
     │
     ▼
[CrewAI Legal Pipeline]  →  Legal Answer (English)
     │
     ▼
[Sarvam Translate]  →  Answer in User's Language
     │
     ▼
[Sarvam TTS]  →  Audio Response
     │
     ▼
VoiceAskResponse { transcript, response_text, citations, audio_base64 }
```

**Headers:** `Authorization: Bearer <token>`

**Request:** `multipart/form-data`

| Field | Type | Required | Notes |
|---|---|---|---|
| `file` | audio file | Yes | User's spoken query |
| `language_code` | string | No | Language spoken, default `hi-IN` |
| `respond_in_audio` | boolean | No | Return TTS audio, default `true` |
| `speaker` | string | No | TTS voice, default `meera` |

**Response `200 OK`:**
```json
{
  "transcript": "हत्या की सजा क्या है?",
  "response_text": "**Murder under BNS 2023**\n\nUnder BNS Section 103...",
  "verification_status": "VERIFIED",
  "confidence": "high",
  "citations": [
    { "act_code": "BNS_2023", "section_number": "103", "verification": "VERIFIED" }
  ],
  "audio_base64": "UklGRiQAAABXQVZFZm10IBAAAA...",
  "language_code": "hi-IN",
  "disclaimer": "This is AI-assisted legal information. Consult a qualified legal professional..."
}
```

**`audio_base64`:** Base64-encoded WAV audio. Decode and play on the frontend:
```javascript
const audioBytes = atob(response.audio_base64);
const buffer = new Uint8Array(audioBytes.length).map((_, i) => audioBytes.charCodeAt(i));
const blob = new Blob([buffer], { type: 'audio/wav' });
new Audio(URL.createObjectURL(blob)).play();
```

**Notes:**
- This endpoint counts as one query against the user's daily rate limit
- If `SARVAM_API_KEY` is not set, STT step will fail with `503`
- TTS failure is non-fatal — the text response is always returned even if audio fails
- The legal pipeline runs at the same quality as `/query/ask` — same verification guarantees

---

## 11. Admin Endpoints

Restricted to users with role `admin`. Not accessible from the standard user JWT — requires a separate admin JWT issued by the server administrator.

---

### GET `/admin/health`

System health check — returns status of all dependencies.

**Response `200 OK`:**
```json
{
  "status": "healthy",
  "timestamp": "2026-02-25T10:30:00Z",
  "components": {
    "database": { "status": "healthy", "latency_ms": 12 },
    "qdrant": { "status": "healthy", "latency_ms": 8, "collections": ["legal_sections", "sc_judgments", "document_templates"] },
    "redis": { "status": "healthy", "latency_ms": 3, "hit_rate": 0.42 },
    "groq_api": { "status": "healthy", "tpm_used": 8432, "tpm_limit": 12000 },
    "mistral_api": { "status": "healthy" },
    "anthropic_api": { "status": "healthy" },
    "sarvam_api": { "status": "healthy" }
  },
  "mistral_fallback_active": false,
  "indexed_sections": {
    "BNS_2023": 352,
    "BNSS_2023": 528,
    "BSA_2023": 170,
    "IPC_1860": 511,
    "CrPC_1973": 484,
    "IEA_1872": 187
  }
}
```

**Degraded response `200 OK` (partial failure):**
```json
{
  "status": "degraded",
  "components": {
    "redis": { "status": "unavailable", "error": "Connection refused", "impact": "Caching disabled — higher latency" }
  }
}
```

---

### POST `/admin/ingest`

Trigger ingestion of a new legal document (PDF) into the pipeline. Runs the full preprocessing → PostgreSQL → Qdrant pipeline.

**Request:** `multipart/form-data`

| Field | Type | Required | Notes |
|---|---|---|---|
| `file` | PDF file | Yes | Max 50MB |
| `act_code` | string | Yes | `BNS_2023` \| `BNSS_2023` etc. |
| `document_type` | string | Yes | `statutory` \| `judgment` |
| `source_url` | string | No | Official source URL for the document |
| `overwrite` | boolean | No | Overwrite if act already indexed (default false) |

**Response `202 Accepted`:**
```json
{
  "job_id": "job_01J9XK2M3N4P5Q6R",
  "act_code": "BNS_2023",
  "status": "queued",
  "message": "Ingestion job queued. Check /admin/jobs/{job_id} for status.",
  "estimated_duration_minutes": 5
}
```

---

### GET `/admin/jobs/{job_id}`

Check the status of an ingestion job.

**Response `200 OK`:**
```json
{
  "job_id": "job_01J9XK2M3N4P5Q6R",
  "act_code": "BNS_2023",
  "status": "completed",
  "started_at": "2026-02-25T10:00:00Z",
  "completed_at": "2026-02-25T10:04:32Z",
  "results": {
    "sections_extracted": 358,
    "sections_passed_confidence": 352,
    "sections_indexed_qdrant": 352,
    "sections_queued_review": 6,
    "errors": 0
  }
}
```

**Status values:** `queued` → `running` → `completed` \| `failed`

---

### POST `/admin/cache/flush`

Flush the Redis response cache (by role or entirely).

**Request Body:**
```json
{
  "role": "lawyer"
}
```

Pass `"role": "all"` to flush the entire cache.

**Response `200 OK`:**
```json
{ "flushed_keys": 147, "role": "lawyer" }
```

---

### POST `/admin/mistral-fallback`

Toggle Mistral fallback mode (when Groq hits TPM limit).

**Request Body:**
```json
{ "active": true }
```

**Response `200 OK`:**
```json
{
  "mistral_fallback_active": true,
  "message": "Mistral fallback ACTIVATED — tool-heavy agents → mistral-large-latest"
}
```

---

## 11. WebSocket / SSE Streaming

Neethi AI uses **Server-Sent Events (SSE)** — not WebSockets — because:
- Legal query responses are **unidirectional** (server → client)
- SSE reconnects automatically on drop
- SSE works through standard HTTP/2 load balancers without special config

SSE is implemented via FastAPI's `StreamingResponse` with `media_type="text/event-stream"`.

**FastAPI implementation pattern:**
```python
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
import asyncio, json

router = APIRouter()

async def stream_crew_response(query: str, user_role: str):
    """Async generator that yields SSE-formatted events."""
    crew = get_crew_for_role(user_role, stream=True)

    # Yield agent progress events
    yield f"event: agent_start\ndata: {json.dumps({'agent': 'QueryAnalyst'})}\n\n"

    # Run crew and stream output
    async for chunk in crew.kickoff_async(inputs={"query": query}):
        yield f"event: token\ndata: {json.dumps({'text': chunk})}\n\n"
        await asyncio.sleep(0)  # Yield control to event loop

    yield "event: end\ndata: {}\n\n"

@router.post("/ask/stream")
async def ask_stream(request: QueryRequest, current_user = Depends(get_current_user)):
    return StreamingResponse(
        stream_crew_response(request.query, current_user.role),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Disable Nginx buffering
        }
    )
```

---

## 12. Pydantic Schemas Reference

**File:** `backend/api/schemas/` *(to be created)*

```python
# backend/api/schemas/auth.py
class RegisterRequest(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=100)
    email: EmailStr
    password: str = Field(..., min_length=8)
    role: Literal["citizen", "lawyer", "legal_advisor", "police"]
    bar_council_id: Optional[str] = None
    police_badge_id: Optional[str] = None
    organization: Optional[str] = None

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserProfile

class UserProfile(BaseModel):
    user_id: str
    full_name: str
    email: EmailStr
    role: str
    created_at: datetime

# backend/api/schemas/query.py
class QueryRequest(BaseModel):
    query: str = Field(..., min_length=10, max_length=2000)
    language: str = Field("en")
    include_precedents: bool = False

class CitationResult(BaseModel):
    act_code: str
    section_number: str
    section_title: Optional[str]
    verification: Literal["VERIFIED", "VERIFIED_INCOMPLETE", "NOT_FOUND"]

class PrecedentResult(BaseModel):
    case_name: str
    year: str
    court: str
    citation: Optional[str]
    verification: Literal["VERIFIED", "NOT_FOUND"]

class QueryResponse(BaseModel):
    query_id: str
    query: str
    response: str
    verification_status: Literal["VERIFIED", "PARTIALLY_VERIFIED", "UNVERIFIED"]
    confidence: Literal["high", "medium", "low"]
    citations: List[CitationResult]
    precedents: List[PrecedentResult]
    user_role: str
    processing_time_ms: int
    cached: bool
    disclaimer: str

# backend/api/schemas/documents.py
class DraftRequest(BaseModel):
    template_id: str
    fields: Dict[str, str]
    language: str = "en"
    include_citations: bool = True

class DraftResponse(BaseModel):
    draft_id: str
    template_id: str
    title: str
    draft_text: str
    verification_status: str
    citations_used: List[CitationResult]
    disclaimer: str
    created_at: datetime
    word_count: int
```

---

## 13. Error Responses

All errors follow the same structure:

```json
{
  "detail": "Human-readable error message",
  "error_code": "MACHINE_READABLE_CODE",
  "request_id": "req_01J9XK2M"
}
```

**Standard HTTP error codes:**

| Code | Meaning | Common Cause |
|---|---|---|
| `400 Bad Request` | Invalid input | Malformed JSON, missing fields |
| `401 Unauthorized` | No/expired token | Token missing or expired |
| `403 Forbidden` | Insufficient role | Citizen accessing lawyer-only endpoint |
| `404 Not Found` | Resource not found | Invalid section, draft, query ID |
| `409 Conflict` | Duplicate resource | Email already registered |
| `422 Unprocessable Entity` | Validation error | Pydantic validation failed |
| `429 Too Many Requests` | Rate limit hit | Exceeded per-role query limit |
| `500 Internal Server Error` | Server error | Agent pipeline failure |
| `503 Service Unavailable` | Dependency down | Groq/Qdrant/Mistral unreachable |

**Neethi-specific error codes:**

| `error_code` | Meaning |
|---|---|
| `NO_RELEVANT_DOCUMENTS` | Query found no indexed sections — response is "cannot verify" message |
| `UNVERIFIED_RESPONSE` | All citations failed verification — response withheld |
| `GROQ_RATE_LIMITED` | Groq 429 — automatic fallback to Mistral triggered |
| `QDRANT_UNAVAILABLE` | Vector DB unreachable — degraded mode |
| `TEMPLATE_NOT_FOUND` | Template ID does not exist |
| `ROLE_RESTRICTED` | User's role cannot access this template or feature |
| `SECTION_NOT_INDEXED` | Requested section exists in DB but not in Qdrant (confidence < 0.7) |

---

## 14. Rate Limiting

Rate limits are enforced per user per role, using **Upstash Redis** with a sliding window counter.

| Role | Queries/day | Queries/minute | Documents/day |
|---|---|---|---|
| `citizen` | 20 | 2 | 5 |
| `lawyer` | 100 | 5 | 20 |
| `legal_advisor` | 100 | 5 | 20 |
| `police` | 50 | 5 | 10 |
| `admin` | Unlimited | Unlimited | Unlimited |

**Rate limit response `429 Too Many Requests`:**
```json
{
  "detail": "Rate limit exceeded. You have used 20/20 queries today.",
  "error_code": "RATE_LIMIT_EXCEEDED",
  "limit": 20,
  "remaining": 0,
  "reset_at": "2026-02-26T00:00:00Z"
}
```

**Response headers on every request:**
```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 88
X-RateLimit-Reset: 1740528000
```

---

## 15. Middleware Stack

Applied in this order (outermost first):

```
1. CORS Middleware          — Allow frontend origin
2. Request ID Middleware    — Attach X-Request-ID to every request/response
3. Auth Middleware          — JWT validation (via FastAPI Depends, not global middleware)
4. Rate Limit Middleware    — Check Redis counter
5. Cache Middleware         — Check Redis for cached response (query endpoints only)
6. Logging Middleware       — Structured JSON log every request + response code + duration
```

**Request ID Middleware (custom):**
```python
@app.middleware("http")
async def add_request_id(request: Request, call_next):
    request_id = str(uuid.uuid4())[:8]
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response
```

---

## 16. Role-Based Access Control

JWT payload contains `role`. FastAPI dependencies enforce access:

```python
# backend/api/dependencies.py

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer

security = HTTPBearer()

async def get_current_user(token = Depends(security)) -> UserProfile:
    """Validate JWT and return user. Raises 401 if invalid/expired."""
    ...

def require_role(*allowed_roles: str):
    """Factory for role-checking dependencies."""
    async def _check(user: UserProfile = Depends(get_current_user)):
        if user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"This endpoint requires role: {', '.join(allowed_roles)}. Your role: {user.role}"
            )
        return user
    return _check

# Usage in router:
@router.post("/cases/analyze")
async def analyze_case(
    request: CaseAnalysisRequest,
    user = Depends(require_role("lawyer", "legal_advisor"))
):
    ...
```

**Role access matrix:**

| Endpoint | citizen | lawyer | legal_advisor | police | admin |
|---|---|---|---|---|---|
| `/query/ask` | ✓ | ✓ | ✓ | ✓ | ✓ |
| `/cases/search` | ✓ (simplified) | ✓ | ✓ | ✓ | ✓ |
| `/cases/analyze` | ✗ | ✓ | ✓ | ✗ | ✓ |
| `/documents/draft` (bail app) | ✗ | ✓ | ✓ | ✗ | ✓ |
| `/documents/draft` (FIR draft) | ✓ | ✓ | ✗ | ✓ | ✓ |
| `/documents/draft` (legal notice) | ✓ | ✓ | ✓ | ✗ | ✓ |
| `/sections/*` | ✓ | ✓ | ✓ | ✓ | ✓ |
| `/resources/nearby` | ✓ | ✓ | ✓ | ✓ | ✓ |
| `/translate/*` | ✓ | ✓ | ✓ | ✓ | ✓ |
| `/admin/*` | ✗ | ✗ | ✗ | ✗ | ✓ |

---

## 17. Environment Variables

All secrets and configuration are in `.env` at project root:

```env
# --- Database ---
DATABASE_URL=postgresql+asyncpg://user:password@db.supabase.co:5432/postgres

# --- Qdrant ---
QDRANT_URL=https://your-cluster.qdrant.io
QDRANT_API_KEY=your_qdrant_api_key

# --- LLM Providers ---
GROQ_API_KEY=gsk_...
MISTRAL_API_KEY=...
ANTHROPIC_API_KEY=sk-ant-...

# --- Cache ---
UPSTASH_REDIS_URL=rediss://...
UPSTASH_REDIS_TOKEN=...

# --- Auth ---
JWT_SECRET_KEY=your_very_long_random_secret_key
JWT_EXPIRY_HOURS=24
JWT_ALGORITHM=HS256

# --- External APIs ---
SARVAM_API_KEY=...
SERP_API_KEY=...
THESYS_API_KEY=...

# --- App Config ---
ENVIRONMENT=development           # development | production
LOG_LEVEL=INFO
CORS_ORIGINS=http://localhost:3000,https://neethiai.com
MAX_QUERY_LENGTH=2000
RATE_LIMIT_CITIZEN_DAILY=20
RATE_LIMIT_LAWYER_DAILY=100
```

---

## 18. Project File Map

**Files created** (Phase 6 — FastAPI layer):

```
backend/
├── main.py                           ✓ FastAPI app + lifespan + router mounts + middleware
│
├── api/
│   ├── routes/
│   │   ├── __init__.py               ✓
│   │   ├── auth.py                   ✓ /auth/register, /login, /refresh, /logout, /me
│   │   ├── query.py                  ✓ /query/ask, /ask/stream (SSE), /history, /{id}, /feedback
│   │   ├── cases.py                  ✓ /cases/search, /analyze, /{case_id}
│   │   ├── documents.py              ✓ /documents/templates, /draft, /draft/{id}, pdf export
│   │   ├── sections.py               ✓ /sections/acts, /acts/{code}/sections/{num}, /normalize, /verify
│   │   ├── resources.py              ✓ /resources/nearby, /legal-aid/eligibility
│   │   ├── translate.py              ✓ /translate/text, /translate/query
│   │   ├── voice.py                  ✓ /voice/speech-to-text, /text-to-speech, /ask
│   │   └── admin.py                  ✓ /admin/health, /ingest, /jobs, /cache/flush, /mistral-fallback
│   │
│   ├── schemas/
│   │   ├── __init__.py               ✓ Re-exports all schemas
│   │   ├── auth.py                   ✓ RegisterRequest, LoginRequest, TokenResponse, UserProfile
│   │   ├── query.py                  ✓ QueryRequest, QueryResponse, CitationResult, PrecedentResult
│   │   ├── cases.py                  ✓ CaseSearchRequest, CaseAnalysisRequest, IRACSection
│   │   ├── documents.py              ✓ DraftRequest, DraftResponse, TemplateInfo
│   │   ├── sections.py               ✓ SectionDetail, ActInfo, NormalizeResponse, VerifyRequest
│   │   ├── resources.py              ✓ NearbyRequest, ResourceResult, EligibilityResponse
│   │   ├── translate.py              ✓ TranslateTextRequest/Response, TranslateQueryRequest/Response
│   │   ├── voice.py                  ✓ STTResponse, TTSRequest, VoiceAskResponse
│   │   └── admin.py                  ✓ HealthResponse, IngestResponse, JobStatus
│   │
│   └── dependencies.py               ✓ get_current_user(), require_role(), check_rate_limit(), get_cache()
│
├── db/
│   └── models/
│       └── user.py                   ✓ User, QueryLog, Draft, QueryFeedback (new models)
│
├── agents/                           ← Already built
├── db/                               ← Already built
├── rag/                              ← Already built
├── services/
│   └── cache.py                      ← Already built
└── config/
    └── llm_config.py                 ← Already built
```

---

*Generated: 2026-02-25 | Neethi AI v1.0 | This document covers both implemented and planned API endpoints. Sections marked "to be created" are not yet implemented.*
