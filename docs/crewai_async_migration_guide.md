# Neethi AI — CrewAI Synchronous to Asynchronous Migration Guide

## Document Purpose

This guide details the transition of NeethiApp's CrewAI pipeline from its current fully synchronous execution model to an asynchronous model. The goal: **multiple users can query simultaneously without bottlenecking**, while preserving the strict sequential agent ordering (Process.sequential) that guarantees legal accuracy within each individual request.

**Key principle**: Inside asynchronous, agents remain synchronous (sequential). The async boundary exists at the crew-execution level — one user's crew does not block another user's crew.

---

## Table of Contents

1. [The Bottleneck Problem](#1-the-bottleneck-problem)
2. [CrewAI Async Methods — What's Available](#2-crewai-async-methods--whats-available)
3. [Migration Strategy Overview](#3-migration-strategy-overview)
4. [Layer 1 — Crew-Level Async (akickoff)](#4-layer-1--crew-level-async-akickoff)
5. [Layer 2 — Tool-Level Async (_run to async _run)](#5-layer-2--tool-level-async-_run-to-async-_run)
6. [Layer 3 — Infrastructure (AsyncQdrantClient + asyncpg)](#6-layer-3--infrastructure-asyncqdrantclient--asyncpg)
7. [Layer 4 — FastAPI Integration (Clean Async Endpoints)](#7-layer-4--fastapi-integration-clean-async-endpoints)
8. [Layer 5 — SSE Streaming with Async Crews](#8-layer-5--sse-streaming-with-async-crews)
9. [Migration Sequence (Ordered Steps)](#9-migration-sequence-ordered-steps)
10. [What Does NOT Change](#10-what-does-not-change)
11. [Testing the Migration](#11-testing-the-migration)
12. [Risk Assessment](#12-risk-assessment)

---

## 1. The Bottleneck Problem

### Current Execution Model

```
User A sends query ──► crew.kickoff() ──► [20-85 seconds blocking] ──► Response A
                                                                          │
User B sends query ──► WAITS ─────────────────────────────────────────────┘
                       ▲                                                   │
                       │ blocked until User A's crew finishes              │
                       └───────────────── crew.kickoff() ──► Response B
```

`crew.kickoff()` is a blocking call. The entire sequential pipeline — QueryAnalyst → RetrievalSpecialist → [LegalReasoner] → CitationChecker → ResponseFormatter — runs synchronously. Nothing else happens on the same thread until it finishes.

### Current Workaround

The project uses `ThreadPoolExecutor` to offload the blocking `kickoff()` call:

```python
# Current approach in FastAPI (Week 10 implementation)
executor = ThreadPoolExecutor()

@app.post("/query/ask")
async def ask(request: QueryRequest):
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        executor,
        lambda: crew.kickoff(inputs={...})
    )
    return result
```

This works but creates problems:
- Each concurrent user spawns an OS thread (expensive, limited by OS)
- Thread pool size limits true concurrency (default is `min(32, os.cpu_count() + 4)`)
- Exception handling across thread boundaries is fragile
- Tool calls inside the crew that use async (asyncpg, aiohttp) cannot share the FastAPI event loop — each thread creates its own event loop via `asyncio.run()`

### Target Execution Model

```
User A sends query ──► await crew.akickoff() ──► [agents run sequentially] ──► Response A
                                                                                    │
User B sends query ──► await crew.akickoff() ──► [agents run sequentially] ──► Response B
                       ▲                                                            │
                       │ NOT blocked — both run concurrently on the event loop       │
                                                                                    │
User C sends query ──► await crew.akickoff() ──► [agents run sequentially] ──► Response C
```

All three users' crews run concurrently on the same async event loop. Within each crew, agents still execute sequentially (Process.sequential is preserved). The async benefit is inter-user concurrency, not intra-crew parallelism.

---

## 2. CrewAI Async Methods — What's Available

CrewAI (0.80.0+) provides **six kickoff methods** in three categories:

### Method Signatures

```python
# ─── Synchronous (current) ───
def kickoff(self, inputs: dict | None = None) -> CrewOutput
def kickoff_for_each(self, inputs: list[dict]) -> list[CrewOutput]

# ─── Native Async (RECOMMENDED) ───
async def akickoff(self, inputs: dict | None = None) -> CrewOutput
async def akickoff_for_each(self, inputs: list[dict]) -> list[CrewOutput]

# ─── Thread-Based Async (wrapper) ───
async def kickoff_async(self, inputs: dict | None = None) -> CrewOutput
async def kickoff_for_each_async(self, inputs: list[dict]) -> list[CrewOutput]
```

### Comparison: `akickoff()` vs `kickoff_async()`

| Aspect | `akickoff()` (Native) | `kickoff_async()` (Thread-based) |
|--------|----------------------|----------------------------------|
| Implementation | True async/await through entire chain | Wraps sync `kickoff()` in `asyncio.to_thread()` |
| Task execution | Native async | Synchronous within thread pool |
| Memory operations | Native async | Synchronous within thread pool |
| Knowledge queries | Native async | Synchronous within thread pool |
| Concurrency model | Event-loop cooperative | OS thread-based |
| Tool async support | Full — async `_run()` works natively | No — tools run sync in thread |
| Exception handling | Direct propagation | Can be lost crossing thread boundary |
| Best for | High-concurrency, I/O-bound (our case) | Quick migration, backward compat |

### Recommendation for Neethi AI: `akickoff()`

`akickoff()` is the correct choice because:
1. Our tools are I/O-bound (Qdrant queries, PostgreSQL lookups, LiteLLM API calls)
2. We need true concurrent multi-user support, not thread pool limits
3. Our database layer is already async (asyncpg) — `akickoff()` lets tools use it directly
4. Exception handling across thread boundaries was a known CrewAI bug (fixed in PR #2488 but still a risk)

**`kickoff_async()` is NOT recommended** — it's just `asyncio.to_thread(self.kickoff)` internally, which is essentially the same `ThreadPoolExecutor` workaround we already have but wrapped inside CrewAI instead of in our code. It solves nothing at the tool level.

---

## 3. Migration Strategy Overview

The migration has five layers, ordered from outermost (easiest) to innermost (most impactful):

```
┌──────────────────────────────────────────────────┐
│  Layer 5: SSE Streaming (stream=True + akickoff) │
│  ┌────────────────────────────────────────────┐  │
│  │  Layer 4: FastAPI Endpoints (async def)     │  │
│  │  ┌──────────────────────────────────────┐  │  │
│  │  │  Layer 1: Crew Execution (akickoff)  │  │  │
│  │  │  ┌────────────────────────────────┐  │  │  │
│  │  │  │  Layer 2: Tool Methods         │  │  │  │
│  │  │  │  (_run → async _run)           │  │  │  │
│  │  │  │  ┌──────────────────────────┐  │  │  │  │
│  │  │  │  │  Layer 3: Infrastructure │  │  │  │  │
│  │  │  │  │  AsyncQdrantClient       │  │  │  │  │
│  │  │  │  │  asyncpg direct          │  │  │  │  │
│  │  │  │  │  aiohttp for LiteLLM     │  │  │  │  │
│  │  │  │  └──────────────────────────┘  │  │  │  │
│  │  │  └────────────────────────────────┘  │  │  │
│  │  └──────────────────────────────────────┘  │  │
│  └────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────┘
```

**Critical constraint**: `Process.sequential` is preserved at every layer. Agents within a crew always run one after another. The async benefit is that multiple crews (multiple users) run concurrently on the event loop, and I/O waits within tools (database queries, API calls) yield control back to the event loop instead of blocking a thread.

---

## 4. Layer 1 — Crew-Level Async (akickoff)

### Current State

**File**: `backend/agents/crew_config.py`

```python
# Current — crew factory returns Crew with Process.sequential
def make_layman_crew() -> Crew:
    # ... agent and task definitions ...
    return Crew(
        agents=[query_analyst, retrieval_specialist, citation_checker, response_formatter],
        tasks=[task_classify, task_retrieve, task_verify, task_format],
        process=Process.sequential,
        verbose=True
    )

# Current — caller uses sync kickoff
crew = make_layman_crew()
result = crew.kickoff(inputs={"query": query, "user_role": "citizen"})
```

### After Migration

```python
# Crew definition — NO CHANGES to crew_config.py
# Process.sequential stays. Agent ordering stays. Task definitions stay.
# The Crew object itself is identical.
def make_layman_crew() -> Crew:
    # ... exact same agent and task definitions ...
    return Crew(
        agents=[query_analyst, retrieval_specialist, citation_checker, response_formatter],
        tasks=[task_classify, task_retrieve, task_verify, task_format],
        process=Process.sequential,   # UNCHANGED — legal accuracy guarantee
        verbose=True
    )

# Caller — switch to akickoff
crew = make_layman_crew()
result = await crew.akickoff(inputs={"query": query, "user_role": "citizen"})
```

### What Changes

| Component | Before | After |
|-----------|--------|-------|
| `crew_config.py` crew definitions | No change | **No change** |
| Agent definitions | No change | **No change** |
| Task definitions | No change | **No change** |
| Process type | `Process.sequential` | **`Process.sequential` (unchanged)** |
| Kickoff call site | `crew.kickoff(inputs={...})` | `await crew.akickoff(inputs={...})` |
| Calling function | `def run_query():` | `async def run_query():` |

### What This Achieves Alone

Even without tool-level changes, switching to `akickoff()` means:
- FastAPI endpoint no longer needs `ThreadPoolExecutor`
- Multiple concurrent users' crews can run on the event loop
- However, individual tool I/O (Qdrant, PostgreSQL) still blocks within each crew turn until Layer 2+3 are done

---

## 5. Layer 2 — Tool-Level Async (_run to async _run)

CrewAI supports async tool methods. Both patterns work:

```python
# Pattern 1: BaseTool subclass with async _run
class MyTool(BaseTool):
    async def _run(self, arg: str) -> str:
        result = await some_async_operation()
        return result

# Pattern 2: @tool decorator with async function
@tool("my_tool")
async def my_tool(arg: str) -> str:
    """Tool description."""
    result = await some_async_operation()
    return result
```

### Tool-by-Tool Migration Plan

#### 5.1 CitationVerificationTool

**File**: `backend/agents/tools/citation_verification_tool.py`

**Current** (sync `_run` with ThreadPoolExecutor for async DB calls):
```python
class CitationVerificationTool(BaseTool):
    def _run(self, act_code: str | dict, section_number: str = "") -> str:
        # ... normalization logic ...
        qdrant_result = self._scroll_qdrant(act_code, section_number)
        if qdrant_result:
            return f"VERIFIED: {qdrant_result}"
        pg_result = _run_async(self._query_postgres(act_code, section_number))
        return f"VERIFIED: {pg_result}" if pg_result else "NOT_FOUND"

    def _scroll_qdrant(self, act_code, section_number):
        # Synchronous QdrantClient.scroll()
        ...

    async def _query_postgres(self, act_code, section_number):
        # Async asyncpg query — currently wrapped in _run_async()
        ...
```

**After** (async `_run`, direct await):
```python
class CitationVerificationTool(BaseTool):
    async def _run(self, act_code: str | dict, section_number: str = "") -> str:
        # ... same normalization logic (pure string ops, no I/O) ...

        # Primary: async Qdrant scroll
        qdrant_result = await self._scroll_qdrant_async(act_code, section_number)
        if qdrant_result:
            return f"VERIFIED: {qdrant_result}"

        # Fallback: direct async PostgreSQL (no ThreadPoolExecutor needed)
        pg_result = await self._query_postgres(act_code, section_number)
        return f"VERIFIED: {pg_result}" if pg_result else "NOT_FOUND"

    async def _scroll_qdrant_async(self, act_code, section_number):
        # AsyncQdrantClient.scroll() — see Layer 3
        ...

    async def _query_postgres(self, act_code, section_number):
        # Direct asyncpg — no wrapper needed anymore
        async with async_session() as session:
            result = await session.execute(
                select(Section).where(
                    Section.act_code == act_code,
                    Section.section_number == section_number
                )
            )
            return result.scalar_one_or_none()
```

**What changes**: `def _run` → `async def _run`, remove `_run_async()` helper, use `await` directly.
**What stays**: All normalization logic, act code mapping, verification output format, anti-fabrication rules.

#### 5.2 StatuteNormalizationTool

**File**: `backend/agents/tools/statute_normalization_tool.py`

**Current**: Sync `_run` with `_run_async()` wrapper for PostgreSQL `TransitionRepository.lookup_transition()`.

**After**:
```python
class StatuteNormalizationTool(BaseTool):
    async def _run(self, old_act: str | dict, old_section: str = "") -> str:
        # ... same input parsing, short-form expansion, parenthetical stripping ...

        # Direct await — no ThreadPoolExecutor wrapper
        async with async_session() as session:
            repo = TransitionRepository(session)
            results = await repo.lookup_transition(normalized_act, normalized_section)

        # ... same output formatting, collision warnings ...
        return formatted_result
```

**What changes**: `def _run` → `async def _run`, remove `_run_async()` helper.
**What stays**: Short-form expansion logic, parenthetical stripping, collision warning injection, all output formatting.

#### 5.3 QdrantHybridSearchTool

**File**: `backend/agents/tools/qdrant_search_tool.py`

**Current**: Sync `_run`, calls `HybridSearcher.search()` (sync), lazy-loaded `QdrantClient` (sync).

**After**:
```python
class QdrantHybridSearchTool(BaseTool):
    async def _run(self, query: str | dict, act_filter: str = "none", ...) -> str:
        # ... same input parsing, sentinel normalization ...

        searcher = await self._get_async_searcher()
        results = await searcher.search_async(
            query=keyword_query,
            act_filter=act_filter if act_filter != "none" else None,
            era_filter=era_filter if era_filter != "none" else None,
            top_k=top_k,
            collection=collection
        )

        # ... same output formatting (statutory vs judgment detection) ...
        return formatted_results
```

**Dependency**: Requires `HybridSearcher` to expose an `async search_async()` method — see Layer 3.

#### 5.4 QueryClassifierTool

**File**: `backend/agents/tools/query_classifier_tool.py`

**Current**: Sync `_run`, calls LiteLLM `completion()` (sync).

**After**:
```python
class QueryClassifierTool(BaseTool):
    async def _run(self, query: str | dict, user_role: str = "citizen") -> str:
        # ... same input parsing ...
        try:
            response = await acompletion(   # LiteLLM async version
                model="groq/llama-3.3-70b-versatile",
                messages=[...],
                temperature=0.1
            )
            return response.choices[0].message.content
        except Exception:
            # ... same static fallback classification ...
            return self._static_fallback(query, user_role)
```

**Note**: LiteLLM provides `acompletion()` as the async equivalent of `completion()`. Same parameters, same return type, just awaitable.

#### 5.5 IRACAnalyzerTool

**File**: `backend/agents/tools/irac_analyzer_tool.py`

**Current**: Sync `_run`, calls LiteLLM `completion()` with Groq → Mistral fallback.

**After**:
```python
class IRACAnalyzerTool(BaseTool):
    async def _run(self, retrieved_sections: str | dict, ...) -> str:
        # ... same input parsing ...
        try:
            response = await acompletion(
                model="groq/llama-3.3-70b-versatile",
                messages=[...],
                temperature=0.1
            )
            return response.choices[0].message.content
        except Exception:
            try:
                response = await acompletion(
                    model="mistral/mistral-large-latest",
                    messages=[...],
                    temperature=0.1
                )
                return response.choices[0].message.content
            except Exception:
                return "IRAC_TOOL_FAILURE: ..."
```

**What changes**: `completion()` → `await acompletion()`.
**What stays**: All IRAC prompt content, scope limits, fallback chain, error messages.

### Tool Migration Summary Table

| Tool | Current `_run` | After `_run` | I/O Operations Changed |
|------|---------------|-------------|----------------------|
| CitationVerificationTool | sync + `_run_async()` wrapper | `async def _run` | Qdrant scroll → async; PostgreSQL → direct await |
| StatuteNormalizationTool | sync + `_run_async()` wrapper | `async def _run` | PostgreSQL → direct await |
| QdrantHybridSearchTool | sync | `async def _run` | HybridSearcher → async method |
| QueryClassifierTool | sync | `async def _run` | `completion()` → `await acompletion()` |
| IRACAnalyzerTool | sync | `async def _run` | `completion()` → `await acompletion()` |

---

## 6. Layer 3 — Infrastructure (AsyncQdrantClient + asyncpg)

### 6.1 Qdrant: Sync Client → Async Client

**Current** (`backend/rag/hybrid_search.py`):
```python
from qdrant_client import QdrantClient

client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
results = client.query_points(...)   # Blocking
scroll_results = client.scroll(...)  # Blocking
```

**After**:
```python
from qdrant_client import AsyncQdrantClient

client = AsyncQdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
results = await client.query_points(...)   # Non-blocking
scroll_results = await client.scroll(...)  # Non-blocking
```

`AsyncQdrantClient` has the exact same method signatures as `QdrantClient` — every method is identical but returns a coroutine. This is a near-drop-in replacement.

**File to modify**: `backend/rag/hybrid_search.py`

```python
class HybridSearcher:
    def __init__(self):
        self.client = AsyncQdrantClient(
            url=QDRANT_URL,
            api_key=QDRANT_API_KEY,
            timeout=30
        )
        self.embedder = BGEM3Embedder()  # CPU embedding stays sync (compute-bound)

    async def search_async(self, query, act_filter=None, era_filter=None,
                           top_k=5, collection="legal_sections"):
        # Embedding generation is CPU-bound — run in thread to not block event loop
        dense_vector, sparse_vector = await asyncio.to_thread(
            self.embedder.embed, query
        )

        # Qdrant queries — I/O-bound, native async
        results = await self.client.query_points(
            collection_name=collection,
            prefetch=[
                Prefetch(query=dense_vector, using="dense", limit=top_k * 5),
                Prefetch(query=sparse_vector, using="sparse", limit=top_k * 5),
            ],
            query=FusionQuery(fusion=Fusion.RRF),
            limit=top_k * 2,
            query_filter=self._build_filter(act_filter, era_filter),
            with_payload=True
        )

        return results
```

**Note on embeddings**: BGE-M3 embedding generation is CPU-bound (matrix multiplication), not I/O-bound. It should be wrapped in `asyncio.to_thread()` to avoid blocking the event loop during the ~100ms embedding computation. This is the one place where `to_thread()` is correct — CPU work genuinely needs a thread.

### 6.2 PostgreSQL: Remove _run_async Wrapper

**Current** (`backend/agents/tools/statute_normalization_tool.py`, lines 77-86):
```python
def _run_async(coro):
    """Run an async coroutine from synchronous CrewAI context."""
    with ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(asyncio.run, coro).result()
```

This pattern exists because sync `_run()` cannot `await`. With async `_run()`, this wrapper is entirely unnecessary.

**After**: Delete `_run_async()` from both files. Use `await` directly in async `_run()`.

### 6.3 LiteLLM: completion() → acompletion()

LiteLLM provides a native async interface:

```python
# Sync (current)
from litellm import completion
response = completion(model="groq/llama-3.3-70b-versatile", messages=[...])

# Async (after)
from litellm import acompletion
response = await acompletion(model="groq/llama-3.3-70b-versatile", messages=[...])
```

Same parameters, same response object, same error types. Used in:
- `QueryClassifierTool._run()`
- `IRACAnalyzerTool._run()`

---

## 7. Layer 4 — FastAPI Integration (Clean Async Endpoints)

### Current (ThreadPoolExecutor workaround)

```python
from concurrent.futures import ThreadPoolExecutor
import asyncio

executor = ThreadPoolExecutor(max_workers=4)

@app.post("/query/ask")
async def ask(request: QueryRequest, user=Depends(get_current_user)):
    crew = get_crew_for_role(user.role)
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        executor,
        lambda: crew.kickoff(inputs={
            "query": request.query,
            "user_role": user.role
        })
    )
    return {"response": result.raw, "token_usage": result.token_usage}
```

### After (Clean async, no ThreadPoolExecutor)

```python
@app.post("/query/ask")
async def ask(request: QueryRequest, user=Depends(get_current_user)):
    crew = get_crew_for_role(user.role)
    result = await crew.akickoff(inputs={
        "query": request.query,
        "user_role": user.role
    })
    return {"response": result.raw, "token_usage": result.token_usage}
```

The `ThreadPoolExecutor` import, the `executor` global, and the `run_in_executor` call are all removed. The endpoint is a clean async function that awaits the crew result directly.

### Concurrent User Handling

With `akickoff()`, FastAPI handles concurrent users naturally:

```python
# User A's request arrives → starts crew A on event loop
# User B's request arrives → starts crew B on event loop (does NOT wait for A)
# User C's request arrives → starts crew C on event loop (does NOT wait for A or B)
#
# All three crews run concurrently. Within each crew, agents run sequentially.
# When crew A's RetrievalSpecialist awaits a Qdrant query, the event loop
# can run crew B's QueryAnalyst or crew C's CitationChecker during the wait.
```

---

## 8. Layer 5 — SSE Streaming with Async Crews

CrewAI supports streaming natively when `stream=True` is set on the Crew.

### Crew Configuration Change

```python
def make_layman_crew(stream: bool = False) -> Crew:
    # ... same agents and tasks ...
    return Crew(
        agents=[query_analyst, retrieval_specialist, citation_checker, response_formatter],
        tasks=[task_classify, task_retrieve, task_verify, task_format],
        process=Process.sequential,
        verbose=True,
        stream=stream     # NEW — enables token-level streaming from all agents
    )
```

### SSE Endpoint with Streaming

```python
from sse_starlette.sse import EventSourceResponse

@app.get("/query/ask/stream")
async def ask_stream(request: QueryRequest, user=Depends(get_current_user)):
    crew = get_crew_for_role(user.role, stream=True)

    async def event_generator():
        streaming_output = await crew.akickoff(inputs={
            "query": request.query,
            "user_role": user.role
        })

        async for chunk in streaming_output:
            yield {
                "event": "chunk",
                "data": json.dumps({
                    "content": chunk.content,
                    "agent": chunk.agent_role,
                    "task": chunk.task_name,
                    "type": chunk.chunk_type.value   # "TEXT" or "TOOL_CALL"
                })
            }

        # Final result after all chunks
        result = streaming_output.result
        yield {
            "event": "complete",
            "data": json.dumps({
                "response": result.raw,
                "token_usage": result.token_usage
            })
        }

    return EventSourceResponse(event_generator())
```

### Stream Chunk Properties (from CrewAI docs)

| Property | Type | Description |
|----------|------|-------------|
| `task_name` | `str` | Current task name (e.g., "classify_query") |
| `task_index` | `int` | Position in task sequence (0-indexed) |
| `agent_role` | `str` | Role of executing agent (e.g., "Legal Query Analyst") |
| `content` | `str` | Text content of this chunk |
| `chunk_type` | `StreamChunkType` | Either `TEXT` or `TOOL_CALL` |
| `tool_call` | `object` | Tool name + arguments (only for `TOOL_CALL` chunks) |

### Frontend SSE Handling (Next.js)

```javascript
// Frontend can show which agent is currently active
const eventSource = new EventSource('/query/ask/stream?query=...');

eventSource.addEventListener('chunk', (event) => {
    const data = JSON.parse(event.data);
    // data.agent tells the UI which agent is running
    // data.content is the streamed text
    updateUI(data.agent, data.content);
});

eventSource.addEventListener('complete', (event) => {
    const data = JSON.parse(event.data);
    showFinalResponse(data.response);
    eventSource.close();
});
```

---

## 9. Migration Sequence (Ordered Steps)

The migration should be done in this specific order. Each step can be tested independently before moving to the next.

### Step 1: Infrastructure — AsyncQdrantClient

**Files**: `backend/rag/hybrid_search.py`

- Replace `QdrantClient` import with `AsyncQdrantClient`
- Add `async search_async()` method to `HybridSearcher`
- Keep sync `search()` method intact (backward compatibility during migration)
- Wrap BGE-M3 embedding in `asyncio.to_thread()` (CPU-bound work)

**Test**: Run existing retrieval tests. The sync `search()` method still works. New `search_async()` method can be tested with `asyncio.run()`.

### Step 2: Tool Layer — Convert _run to async _run

**Files**: All 5 tool files in `backend/agents/tools/`

- Convert `def _run()` → `async def _run()` in all five tools
- Replace `completion()` → `await acompletion()` in QueryClassifierTool and IRACAnalyzerTool
- Replace `_run_async(coro)` → `await coro` in StatuteNormalizationTool and CitationVerificationTool
- Replace sync `HybridSearcher.search()` → `await HybridSearcher.search_async()` in QdrantHybridSearchTool
- Delete the `_run_async()` helper functions from both tools that have them

**Test**: Tools can still be tested individually with `asyncio.run(tool._run(...))`.

### Step 3: Crew Execution — akickoff()

**Files**: `backend/tests/smoke_e2e.py` (test runner), any service layer that calls `crew.kickoff()`

- Change `crew.kickoff(inputs={...})` → `await crew.akickoff(inputs={...})`
- Change calling functions from `def` → `async def`
- Update test runner to use `asyncio.run(main())`

**Test**: Run full smoke tests for all 4 crews. Verify identical output quality. Compare results with pre-migration smoke test outputs.

### Step 4: FastAPI Endpoints — Remove ThreadPoolExecutor

**Files**: `backend/api/` endpoint files

- Remove `ThreadPoolExecutor` import and `executor` global
- Remove `loop.run_in_executor()` wrapper
- Use `await crew.akickoff()` directly in endpoint handlers

**Test**: Load test with 3-5 concurrent requests. Verify all return correct results without blocking each other.

### Step 5: SSE Streaming — stream=True

**Files**: `backend/agents/crew_config.py`, SSE endpoint file

- Add `stream` parameter to crew factory functions
- Implement SSE endpoint using `async for chunk in streaming_output`
- Update Next.js frontend to consume SSE events

**Test**: Verify streaming works for all 4 user roles. Verify `chunk.agent_role` correctly identifies each agent as it runs.

---

## 10. What Does NOT Change

These components remain identical through the entire migration:

| Component | Why It Stays |
|-----------|-------------|
| `Process.sequential` | Legal accuracy guarantee — agents must run in strict order |
| Agent definitions (role, goal, backstory) | Business logic, not execution model |
| Task descriptions and expected_output | Prompt engineering, not execution model |
| Agent ordering in crews | Safety gate ordering (CitationChecker before ResponseFormatter) |
| Tool input/output schemas (`*Input` Pydantic models) | Interface contracts unchanged |
| StatuteNormalization collision warnings | Safety-critical logic, pure data |
| Act-code normalization logic | String operations, no I/O |
| LLM model selection (Groq → Mistral fallback) | Provider strategy unchanged |
| `_mistral_fallback_active` flag mechanism | Rate-limit handling unchanged |
| CrewOutput structure (`.raw`, `.token_usage`) | CrewAI return type is the same for all kickoff methods |

---

## 11. Testing the Migration

### Pre-Migration Baseline

Before starting, capture baseline outputs for comparison:

```python
# Run each crew with a fixed query and save the output
baselines = {}
for role in ["citizen", "lawyer", "legal_advisor", "police"]:
    crew = get_crew_for_role(role)
    result = crew.kickoff(inputs={
        "query": BASELINE_QUERIES[role],
        "user_role": role
    })
    baselines[role] = {
        "raw": result.raw,
        "sections_cited": extract_sections(result.raw),
        "token_usage": result.token_usage
    }
    save_baseline(role, baselines[role])
```

### Post-Migration Validation

```python
# Run each crew with akickoff and compare
for role in ["citizen", "lawyer", "legal_advisor", "police"]:
    crew = get_crew_for_role(role)
    result = await crew.akickoff(inputs={
        "query": BASELINE_QUERIES[role],
        "user_role": role
    })

    # Verify same sections are cited (legal accuracy preserved)
    new_sections = extract_sections(result.raw)
    assert new_sections == baselines[role]["sections_cited"], \
        f"Section mismatch for {role}: {new_sections} != {baselines[role]['sections_cited']}"
```

### Concurrency Test

```python
import asyncio
import time

async def concurrent_test():
    crews = [
        (get_crew_for_role("citizen"), {"query": "What is assault?", "user_role": "citizen"}),
        (get_crew_for_role("lawyer"), {"query": "Murder IRAC analysis", "user_role": "lawyer"}),
        (get_crew_for_role("police"), {"query": "Robbery at knifepoint", "user_role": "police"}),
    ]

    start = time.time()

    # Run all 3 crews concurrently
    results = await asyncio.gather(
        *[crew.akickoff(inputs=inputs) for crew, inputs in crews]
    )

    elapsed = time.time() - start

    # All 3 should complete in roughly the time of the LONGEST single crew,
    # not 3x the time (which is what sync would take)
    print(f"3 concurrent crews completed in {elapsed:.1f}s")

    for i, result in enumerate(results):
        assert "NOT_FOUND" not in result.raw or "cannot verify" in result.raw.lower()
        print(f"Crew {i+1}: {len(result.raw)} chars, sections verified")

asyncio.run(concurrent_test())
```

### Safety Gate Verification

The most critical test — verify that async execution does not break the citation verification gate:

```python
async def safety_gate_test():
    """Verify CitationChecker still runs BEFORE ResponseFormatter in async mode."""
    crew = get_crew_for_role("citizen")

    # Query that triggers IPC 302 → BNS 103 collision
    result = await crew.akickoff(inputs={
        "query": "What is the punishment for murder under IPC 302?",
        "user_role": "citizen"
    })

    # BNS 103 MUST appear (correct mapping)
    assert "BNS 103" in result.raw or "103" in result.raw
    # BNS 302 MUST NOT appear for murder (wrong mapping — Snatching)
    assert "BNS 302" not in result.raw or "snatching" in result.raw.lower()
```

---

## 12. Risk Assessment

### Low Risk

| Risk | Mitigation |
|------|-----------|
| `akickoff()` returns different output than `kickoff()` | Same underlying agent/task execution; only execution context changes. Baseline comparison test confirms. |
| `async def _run` breaks tool registration | CrewAI 0.80.0+ explicitly supports async `_run()` in BaseTool. Documented with examples. |
| `acompletion()` behaves differently from `completion()` | LiteLLM's async interface is a thin wrapper; same parameters, same response type. |

### Medium Risk

| Risk | Mitigation |
|------|-----------|
| BGE-M3 embedding blocks event loop | Wrap in `asyncio.to_thread()` — this is the one legitimate use of thread offloading (CPU-bound work). |
| `AsyncQdrantClient` connection pooling differs from sync client | Test with concurrent requests; Qdrant's async client uses `aiohttp` internally with connection pooling. Monitor for connection exhaustion under load. |
| Rate-limit flag (`_mistral_fallback_active`) race condition with concurrent crews | The flag is a simple boolean read/write. In CPython, the GIL makes bool assignment atomic. For safety, consider `asyncio.Lock` if two crews could detect rate limits simultaneously. |

### High Risk (Requires Careful Handling)

| Risk | Mitigation |
|------|-----------|
| `Process.sequential` accidentally changed during migration | **Never touch Process type.** Add assertion in crew factories: `assert crew.process == Process.sequential`. |
| Agent ordering broken (CitationChecker after ResponseFormatter) | **Never reorder tasks list.** Add integration test that verifies CitationChecker output appears in crew's task chain before ResponseFormatter. |
| Async exception swallowed silently | `akickoff()` propagates exceptions directly (unlike `kickoff_async()` which had a known bug). Add try/except with structured logging at the endpoint level. |

---

## Appendix A — File Change Summary

| File | Change Type | Description |
|------|-------------|-------------|
| `backend/rag/hybrid_search.py` | Modify | Add `AsyncQdrantClient`, add `async search_async()` |
| `backend/agents/tools/citation_verification_tool.py` | Modify | `_run` → `async _run`, remove `_run_async()`, async Qdrant scroll |
| `backend/agents/tools/statute_normalization_tool.py` | Modify | `_run` → `async _run`, remove `_run_async()`, direct await PostgreSQL |
| `backend/agents/tools/qdrant_search_tool.py` | Modify | `_run` → `async _run`, call `search_async()` |
| `backend/agents/tools/query_classifier_tool.py` | Modify | `_run` → `async _run`, `completion()` → `await acompletion()` |
| `backend/agents/tools/irac_analyzer_tool.py` | Modify | `_run` → `async _run`, `completion()` → `await acompletion()` |
| `backend/agents/crew_config.py` | Minor | Add optional `stream` parameter to crew factories |
| `backend/api/` (endpoint files) | Modify | Remove `ThreadPoolExecutor`, use `await crew.akickoff()` |
| `backend/tests/smoke_e2e.py` | Modify | `crew.kickoff()` → `await crew.akickoff()`, add `asyncio.run()` |
| `backend/config/llm_config.py` | No change | LLM factory functions unchanged |
| Agent definition files (5 files) | No change | Agent role/goal/backstory/tools unchanged |

---

## Appendix B — Dependency Requirements

```
# Already in requirements.txt
crewai>=0.80.0        # akickoff() available since ~0.51+
litellm               # acompletion() available in all recent versions
qdrant-client         # AsyncQdrantClient available since qdrant-client 1.7+
asyncpg               # Already used
sqlalchemy[asyncio]   # Already used

# May need addition
aiohttp               # Required by AsyncQdrantClient internally
sse-starlette         # For SSE streaming endpoint (if not already present)
```

---

## Appendix C — Quick Reference: CrewAI Async API

```python
# ─── Native Async (use this) ───
result = await crew.akickoff(inputs={"query": "...", "user_role": "citizen"})
results = await crew.akickoff_for_each(inputs=[{...}, {...}, {...}])

# ─── Streaming ───
crew = Crew(agents=[...], tasks=[...], stream=True)
streaming = await crew.akickoff(inputs={...})
async for chunk in streaming:
    print(chunk.content)        # text content
    print(chunk.agent_role)     # which agent
    print(chunk.task_name)      # which task
    print(chunk.chunk_type)     # TEXT or TOOL_CALL
result = streaming.result       # access AFTER iteration completes

# ─── Async Tool Definition ───
class MyTool(BaseTool):
    name: str = "my_tool"
    description: str = "..."
    async def _run(self, arg: str) -> str:
        result = await some_async_io()
        return result

# ─── LiteLLM Async ───
from litellm import acompletion
response = await acompletion(model="groq/llama-3.3-70b-versatile", messages=[...])

# ─── CrewOutput (same for all kickoff methods) ───
result.raw              # str — default text output
result.pydantic         # Optional[BaseModel] — structured output
result.json_dict        # Optional[Dict] — JSON output
result.tasks_output     # List[TaskOutput] — per-task results
result.token_usage      # Dict — LLM usage metrics
```

---

*Neethi AI — CrewAI Async Migration Guide*
*Version 1.0 | February 2026*
*Reference: CrewAI docs — https://docs.crewai.com/en/learn/kickoff-async*
