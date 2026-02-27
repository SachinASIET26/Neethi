# API Routing Architecture

FastAPI layer — middleware stack, authentication, and endpoint organization.

## Middleware Stack

```mermaid
graph TD
    subgraph CLIENT["Client"]
        C[Browser / Mobile App / CLI]
    end

    subgraph MIDDLEWARE["Middleware Stack (LIFO execution)"]
        M1[CORS Middleware\nAllow: localhost:3000, neethiai.com]
        M2[Request ID + Timing\nX-Request-ID header\nX-Response-Time-Ms header]
        M3[Rate Limiter\nPer user role via Redis]
    end

    subgraph AUTH["Authentication"]
        JWT[JWT Dependency\npython-jose\npasslib bcrypt]
        ROLE[Role Extractor\ncitizen / lawyer / advisor / police / admin]
        JWT --> ROLE
    end

    subgraph ROUTERS["API Routers /api/v1"]
        R1["/auth — Authentication\nPOST /register\nPOST /login"]
        R2["/query — Legal Query\nPOST /ask\nPOST /ask/stream SSE"]
        R3["/cases — Case Law\nPOST /search\nPOST /analyze"]
        R4["/documents — Drafting\nPOST /draft\nPOST /draft/id/pdf"]
        R5["/sections — Acts\nGET /acts\nGET /acts/id/sections/num"]
        R6["/resources — Discovery\nPOST /nearby"]
        R7["/translate — Language\nPOST /text"]
        R8["/voice — TTS/STT\nPOST /tts\nPOST /stt"]
        R9["/admin — Operations\nPOST /ingest\nGET /health"]
    end

    subgraph SERVICES["Downstream Services"]
        CREW[CrewAI Agent Pipeline]
        CACHE[Redis Response Cache]
        DB[PostgreSQL Database]
        QDRANT[Qdrant Vector Store]
    end

    C --> M1
    M1 --> M2
    M2 --> M3
    M3 --> AUTH
    AUTH --> ROUTERS
    R2 --> CREW
    R2 --> CACHE
    R1 --> DB
    R3 --> CREW
    R4 --> CREW
    R5 --> QDRANT
    R9 --> QDRANT
```

---

## Endpoint Access Matrix

| Endpoint Group | Citizen | Lawyer | Advisor | Police | Admin |
|---|---|---|---|---|---|
| `/auth` | Yes | Yes | Yes | Yes | Yes |
| `/query/ask` | Simplified | Full IRAC | Corporate | Procedural | Yes |
| `/query/ask/stream` | Yes | Yes | Yes | Yes | Yes |
| `/cases/search` | Read-only | Full | Full | Criminal | Yes |
| `/cases/analyze` | No | Yes | Yes | Limited | Yes |
| `/documents/draft` | Basic | Full | Full | Basic | Yes |
| `/sections` | Yes | Yes | Yes | Yes | Yes |
| `/resources/nearby` | Yes | Yes | Yes | Yes | Yes |
| `/translate` | Yes | Yes | Yes | Yes | Yes |
| `/voice` | Yes | Yes | Yes | Yes | Yes |
| `/admin` | No | No | No | No | Yes |

---

## SSE Streaming Response Format

```mermaid
sequenceDiagram
    participant Client
    participant FastAPI
    participant CrewAI
    participant LLM

    Client->>FastAPI: POST /query/ask/stream
    FastAPI->>CrewAI: akickoff() async
    loop Agent steps
        CrewAI->>LLM: Agent task execution
        LLM-->>CrewAI: Partial response
        CrewAI-->>FastAPI: Stream chunk
        FastAPI-->>Client: data: {chunk}\n\n (SSE)
    end
    FastAPI-->>Client: data: [DONE]\n\n
```

---

## Application Entry Point

```
backend/main.py
├── Lifespan: DB table creation + Redis warmup
├── Middleware: CORS → Request ID → Rate Limit
└── Routers: auth, query, cases, documents, sections,
             resources, translate, voice, admin
```

Start command:
```bash
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --loop asyncio
```
