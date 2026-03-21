"""LLM synthesis service for document analysis.

Turns raw PageIndex retrieved_nodes into a focused, grounded legal answer.
Uses Groq (Llama 3.3 70B, free tier) with DeepSeek-Chat fallback — no paid models.

Anti-hallucination design:
  - The LLM is given ONLY the retrieved node content as context.
  - The system prompt strictly forbids reasoning beyond the provided excerpts.
  - If context is empty or insufficient, the model must say so explicitly.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Provider endpoints (OpenAI-compatible chat completions)
# ---------------------------------------------------------------------------

_GROQ_URL     = "https://api.groq.com/openai/v1/chat/completions"
_DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"

_GROQ_MODEL     = "llama-3.3-70b-versatile"
_DEEPSEEK_MODEL = "deepseek-chat"

_MAX_TOKENS = 1500   # keeps Groq within free-tier 6000 TPM context budget
_TEMPERATURE = 0.15  # low temp → deterministic, grounded answers


# ---------------------------------------------------------------------------
# Grounding prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are an expert Indian Legal Assistant tasked with analysing a legal document.

CRITICAL RULES — you MUST follow every rule without exception:
1. Answer ONLY from the document excerpts supplied in this message.
2. Do NOT use general legal knowledge, case law, or statutes not present in the excerpts.
3. If the excerpts do not contain enough information to answer the query fully, \
state clearly: "The document does not appear to contain sufficient information about [topic]."
4. Quote or closely paraphrase the source text where relevant; never invent details.
5. Structure the answer with short, clear sections when appropriate.
6. Use precise legal language — this answer will be read by legal professionals.
7. Do not add disclaimers about consulting a lawyer; the user already knows this is AI-generated.
"""

_USER_TEMPLATE = """\
## Retrieved Document Excerpts

{context}

---

## Query

{query}

---

Provide a focused, grounded answer based SOLELY on the excerpts above.\
"""


# ---------------------------------------------------------------------------
# Context builder
# ---------------------------------------------------------------------------

def _build_context(retrieved_nodes: list[dict[str, Any]]) -> str:
    """Flatten retrieved_nodes into a numbered plain-text context block."""
    parts: list[str] = []
    for node in retrieved_nodes:
        node_title = node.get("title", "Untitled Section")
        node_id    = node.get("id", "?")
        parts.append(f"### [{node_id}] {node_title}")
        # relevant_contents is array-of-arrays
        for rc_group in node.get("relevant_contents", []):
            items = rc_group if isinstance(rc_group, list) else [rc_group]
            for rc in items:
                section = rc.get("section_title", "").strip()
                content = rc.get("relevant_content", "").strip()
                if not content:
                    continue
                if section and section != node_title:
                    parts.append(f"**{section}**")
                parts.append(content)
    return "\n\n".join(parts) if parts else "(No content retrieved)"


# ---------------------------------------------------------------------------
# Provider calls
# ---------------------------------------------------------------------------

async def _call_groq(messages: list[dict], api_key: str) -> str:
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            _GROQ_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": _GROQ_MODEL,
                "messages": messages,
                "temperature": _TEMPERATURE,
                "max_tokens": _MAX_TOKENS,
            },
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()


async def _call_deepseek(messages: list[dict], api_key: str) -> str:
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            _DEEPSEEK_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": _DEEPSEEK_MODEL,
                "messages": messages,
                "temperature": _TEMPERATURE,
                "max_tokens": _MAX_TOKENS,
            },
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def synthesize_answer(query: str, retrieved_nodes: list[dict[str, Any]]) -> str:
    """Generate a grounded legal answer from PageIndex retrieved nodes.

    Tries Groq (Llama 3.3 70B) first, then DeepSeek-Chat.
    Returns a plain-text answer, or a fallback message if no LLM is configured.

    Args:
        query:           The user's analysis query.
        retrieved_nodes: Raw nodes from PageIndex (id, title, relevant_contents).

    Returns:
        Synthesized answer as a string.
    """
    if not retrieved_nodes:
        return "No relevant content was retrieved from the document for this query."

    context = _build_context(retrieved_nodes)
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user",   "content": _USER_TEMPLATE.format(context=context, query=query)},
    ]

    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    if groq_key:
        try:
            answer = await _call_groq(messages, groq_key)
            logger.info("synthesis: Groq Llama 3.3 70B synthesized answer (%d chars)", len(answer))
            return answer
        except Exception as exc:
            logger.warning("synthesis: Groq failed (%s), trying DeepSeek", exc)

    deepseek_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if deepseek_key:
        try:
            answer = await _call_deepseek(messages, deepseek_key)
            logger.info("synthesis: DeepSeek-Chat synthesized answer (%d chars)", len(answer))
            return answer
        except Exception as exc:
            logger.warning("synthesis: DeepSeek also failed: %s", exc)

    # No LLM configured — return the raw summary text so the UI still works
    logger.warning("synthesis: no LLM key configured (GROQ_API_KEY / DEEPSEEK_API_KEY); returning raw excerpts")
    return context
