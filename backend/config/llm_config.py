"""LLM configuration for Neethi AI agents.

Multi-LLM strategy per task type:

    | Task                        | Primary              | Fallback 1           | Fallback 2    |
    |-----------------------------|----------------------|----------------------|---------------|
    | Query classification        | Mistral Large        | Groq Llama 3.3 70B   | DeepSeek Chat |
    | Tool-heavy retrieval        | Mistral Large        | Groq Llama 3.3 70B   | DeepSeek Chat |
    | Legal reasoning (IRAC)      | Mistral Large        | Groq Llama 3.3 70B   | DeepSeek Chat |
    | Citation verification       | Mistral Large        | Groq Llama 3.3 70B   | DeepSeek Chat |
    | Response formatting         | Mistral Large        | Groq Llama 3.3 70B   | DeepSeek Chat |
    | Document drafting           | Mistral Large        | Groq Llama 3.3 70B   | DeepSeek Chat |

Runtime key selection order (first available wins):
    1. MISTRAL_API_KEY  → mistral/mistral-large-latest   (preferred)
    2. GROQ_API_KEY     → groq/llama-3.3-70b-versatile   (fallback)
    3. DEEPSEEK_API_KEY → deepseek/deepseek-chat          (last resort)
    4. None configured  → RuntimeError at crew build time

Why Mistral Large as primary:
    Mistral Large reliably follows multi-step tool-use instructions — critical
    for RetrievalSpecialist and CitationChecker. Groq is a capable fallback
    but its free tier (100K tokens/day, 12K TPM) is too constrained for
    production legal workloads. Mistral has no comparable hard daily cap.

All models are accessed through LiteLLM (CrewAI dependency), which handles
API routing and retries transparently.

Required environment variables (set in .env):
    MISTRAL_API_KEY   — Mistral AI API key  (primary)
    GROQ_API_KEY      — Groq API key        (fallback 1)
    DEEPSEEK_API_KEY  — DeepSeek API key    (fallback 2, optional)
"""

from __future__ import annotations

import logging
import os

from crewai import LLM

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Model identifiers (LiteLLM format)
# ---------------------------------------------------------------------------

_MISTRAL_LARGE = "mistral/mistral-large-latest"
_GROQ_LLAMA    = "groq/llama-3.3-70b-versatile"
_DEEPSEEK_CHAT = "deepseek/deepseek-chat"
_CLAUDE_SONNET = "anthropic/claude-sonnet-4-5-20251001"  # kept for optional use

# Legacy aliases so any direct import of these names still works
_GROQ_FAST     = _GROQ_LLAMA
_MISTRAL_SMALL = _MISTRAL_LARGE


# ---------------------------------------------------------------------------
# Fallback flag (kept for API compat with admin route — no-op since
# Mistral is now the unconditional primary)
# ---------------------------------------------------------------------------

_mistral_fallback_active: bool = False


def is_mistral_fallback_active() -> bool:
    """Return the fallback flag (legacy — no longer gates model selection)."""
    return _mistral_fallback_active


def set_mistral_fallback(active: bool) -> None:
    """Legacy API kept for admin route compatibility. No longer changes model selection."""
    global _mistral_fallback_active
    _mistral_fallback_active = active
    logger.info(
        "llm_config: set_mistral_fallback(%s) called — "
        "Mistral Large is always primary; flag has no effect on model choice.",
        active,
    )


# ---------------------------------------------------------------------------
# Internal factory — Mistral → Groq → DeepSeek
# ---------------------------------------------------------------------------

def _build_llm(temperature: float, max_tokens: int) -> LLM:
    """Return an LLM using the first configured API key: Mistral → Groq → DeepSeek.

    Fails loudly at crew build time if no key is found — better than silently
    returning wrong legal answers because of a missing env var.
    """
    mistral_key = os.getenv("MISTRAL_API_KEY", "").strip()
    if mistral_key:
        logger.debug("llm_config: using Mistral Large")
        return LLM(
            model=_MISTRAL_LARGE,
            api_key=mistral_key,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    if groq_key:
        logger.info("llm_config: MISTRAL_API_KEY not set — falling back to Groq Llama 3.3 70B")
        return LLM(
            model=_GROQ_LLAMA,
            api_key=groq_key,
            temperature=temperature,
            # Groq free tier: cap tokens to conserve the 12K TPM / 100K TPD budget
            max_tokens=min(max_tokens, 4096),
        )

    deepseek_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if deepseek_key:
        logger.info("llm_config: MISTRAL_API_KEY and GROQ_API_KEY not set — falling back to DeepSeek Chat")
        return LLM(
            model=_DEEPSEEK_CHAT,
            api_key=deepseek_key,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    raise RuntimeError(
        "No LLM API key configured. Set at least one of: "
        "MISTRAL_API_KEY (preferred), GROQ_API_KEY (fallback), "
        "or DEEPSEEK_API_KEY (last resort) in your .env file."
    )


# ---------------------------------------------------------------------------
# LLM factories (public API — unchanged signatures for all callers)
# ---------------------------------------------------------------------------

def get_fast_llm() -> LLM:
    """Query classification and response formatting.

    Mistral Large primary — fast and accurate for classification tasks.
    Falls back to Groq Llama 3.3 70B when Mistral key is unavailable.
    """
    return _build_llm(temperature=0.1, max_tokens=2048)


def get_light_llm() -> LLM:
    """Tool-heavy retrieval agents (RetrievalSpecialist, CitationChecker).

    4096 token budget so both agents can fit their full outputs:
      - RetrievalSpecialist: STATUTORY RESULTS + PRECEDENT RESULTS
      - CitationChecker: all 8 verification steps + Final Answer
    """
    return _build_llm(temperature=0.0, max_tokens=4096)


def get_standard_llm() -> LLM:
    """Citation verification and general-purpose tasks."""
    return _build_llm(temperature=0.1, max_tokens=4096)


def get_reasoning_llm() -> LLM:
    """IRAC legal analysis (LegalReasoner).

    8192 token budget for complex multi-section IRAC analysis covering
    Issue, Rule, Application, Conclusion with supporting citations.
    """
    return _build_llm(temperature=0.3, max_tokens=8192)


def get_drafting_llm() -> LLM:
    """Legal document drafting.

    8192 token budget for complete legal documents (bail applications,
    legal notices, affidavits). ANTHROPIC_API_KEY is not required.
    """
    return _build_llm(temperature=0.2, max_tokens=8192)
