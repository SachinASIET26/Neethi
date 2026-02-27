"""IRACAnalyzerTool — Phase 5 legal reasoning tool.

Calls Groq Llama 3.3 70B (primary) or Mistral Large (fallback) via LiteLLM
to produce a structured IRAC analysis from retrieved legal sections.
Used exclusively by the LegalReasoner agent —
activated only for lawyer and legal_advisor roles.

IRAC = Issue | Rule | Application | Conclusion

Output format (plaintext for reliable agent parsing):
    IRAC ANALYSIS:

    ISSUE:
    [The precise legal question raised by the query]

    RULE:
    [The applicable legal sections and their substance]

    APPLICATION:
    [How the rules apply to the facts/scenario presented]

    CONCLUSION:
    [The legal conclusion with confidence indicator]

    APPLICABLE SECTIONS:
    [act_code s.section_number — Title]

    APPLICABLE PRECEDENTS:
    [Case Name (Year) — relevance description, or "No SC precedents retrieved for this query."]

    CONFIDENCE: [high | medium | low]
"""

from __future__ import annotations

import logging
import os
from textwrap import dedent

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# IRAC prompt
# ---------------------------------------------------------------------------

_IRAC_PROMPT = dedent("""\
You are a senior Indian legal analyst. Using ONLY the retrieved legal content provided below, perform a rigorous IRAC analysis.

CRITICAL RULES:
1. Only cite sections that appear in the RETRIEVED SECTIONS below. Never invent section numbers.
2. If the retrieved sections are insufficient to answer, state that in the CONCLUSION.
3. Distinguish between the new acts (BNS/BNSS/BSA, in force from July 1 2024) and old acts (IPC/CrPC/IEA).
4. For every section cited in APPLICATION, confirm it exists in the RETRIEVED SECTIONS.
5. Do NOT add any "Additional Regulatory Provisions", "Related Laws", or any other section that
   is not explicitly listed in the RETRIEVED SECTIONS below — even if such laws seem relevant.
   The database only contains BNS/BNSS/BSA. Companies Act, SEBI, CPC, IT Act, and all other
   laws are outside the scope of this analysis. Do not mention them.
6. The APPLICABLE SECTIONS list at the end must only contain sections from RETRIEVED SECTIONS.
7. SC CASE RULE: In your APPLICATION section, you may reference ONLY case names that appear
   in the PRECEDENT RESULTS block below (if present). Do NOT write any case name — including
   landmark cases like Bachan Singh, Machhi Singh, Kehar Singh, or any other — that is not
   explicitly listed in PRECEDENT RESULTS. If the PRECEDENT RESULTS block is absent or empty,
   write "No SC precedents retrieved for this query." in APPLICABLE PRECEDENTS.
   Hallucinating case names is a critical safety failure in a legal AI system.
8. SECTION NUMBER GUARD: Section numbers that look like 4-digit years (2020, 2021, 2022,
   2023, 2024, 2025) are NEVER valid BNS/BNSS/BSA section numbers. These are hallucinations
   caused by confusing the act year with a section number. Do NOT cite them.

USER ROLE: {user_role}
ORIGINAL QUERY: {original_query}

RETRIEVED LEGAL CONTENT:
{retrieved_sections}

Output EXACTLY this structure (keep all labels, fill in the content):

IRAC ANALYSIS:

ISSUE:
[The precise legal question(s) raised by the query]

RULE:
[The relevant legal sections from the retrieved content and their key provisions]

APPLICATION:
[How the rules apply to the query — cite only retrieved sections and PRECEDENT RESULTS cases]

CONCLUSION:
[The legal conclusion. If uncertain or sections are insufficient, say so explicitly.]

APPLICABLE SECTIONS:
[List each cited section as: act_code s.section_number — Title]

APPLICABLE PRECEDENTS:
[List each SC case as: Case Name (Year) — brief description of relevance.
 If no PRECEDENT RESULTS were in the retrieved content, write: "No SC precedents retrieved for this query."]

CONFIDENCE: [high | medium | low — high only if all cited sections are in retrieved content]
""")

# ---------------------------------------------------------------------------
# Input schema
# ---------------------------------------------------------------------------


class IRACAnalyzerInput(BaseModel):
    """Input for the IRACAnalyzerTool."""

    retrieved_sections: str = Field(
        ...,
        description="Concatenated text of retrieved legal sections from QdrantHybridSearchTool",
    )
    original_query: str = Field(..., description="The original user legal query")
    user_role: str = Field(
        "lawyer",
        description="User role: lawyer | legal_advisor (this tool is not used for citizens)",
    )


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------

class IRACAnalyzerTool(BaseTool):
    """Perform IRAC (Issue, Rule, Application, Conclusion) analysis on retrieved legal sections.

    Uses Groq Llama 3.3 70B (primary) or Mistral Large (fallback) for legal reasoning.
    Only activated for lawyer and legal_advisor roles.

    Input must include the raw text output from QdrantHybridSearchTool as
    `retrieved_sections` — the IRAC analysis is grounded to only what was retrieved.

    Usage::

        tool = IRACAnalyzerTool()
        result = tool.run({
            "retrieved_sections": "<output from QdrantHybridSearchTool>",
            "original_query": "What constitutes murder under BNS?",
            "user_role": "lawyer",
        })
    """

    name: str = "IRACAnalyzerTool"
    description: str = (
        "Perform structured IRAC legal analysis on retrieved law sections. "
        "For lawyer and legal_advisor roles only. "
        "Input: {retrieved_sections: str, original_query: str, user_role: str}. "
        "Output: IRAC analysis with Issue, Rule, Application, Conclusion, "
        "Applicable Sections list, and confidence score. "
        "IMPORTANT: Only cites sections present in the retrieved_sections input — never hallucinates."
    )
    args_schema: type[BaseModel] = IRACAnalyzerInput

    def _run(  # type: ignore[override]
        self,
        retrieved_sections: str | dict,
        original_query: str = "",
        user_role: str = "lawyer",
    ) -> str:
        """Call Groq Llama 3.3 70B (sync) to produce IRAC analysis.

        Synchronous — CrewAI's BaseTool.run() calls _run() synchronously.
        Uses litellm.completion() (sync) instead of acompletion() to avoid
        the 'asyncio.run() cannot be called from a running event loop' error.

        Falls back to Mistral Large if Groq is rate-limited.
        Handles both dict input and keyword args.
        """
        from litellm import completion

        # Handle dict input
        if isinstance(retrieved_sections, dict):
            original_query = retrieved_sections.get("original_query", "")
            user_role = retrieved_sections.get("user_role", "lawyer")
            retrieved_sections = retrieved_sections.get("retrieved_sections", "")

        if not retrieved_sections.strip():
            return (
                "IRAC ANALYSIS ERROR: No retrieved sections provided. "
                "Run QdrantHybridSearchTool first and pass its output as retrieved_sections."
            )

        if not original_query.strip():
            return "IRAC ANALYSIS ERROR: No original_query provided."

        prompt = _IRAC_PROMPT.format(
            retrieved_sections=retrieved_sections,
            original_query=original_query,
            user_role=user_role,
        )

        # Try Groq first, fall back to Mistral Large
        for model, api_key_env, temperature in [
            ("groq/llama-3.3-70b-versatile", "GROQ_API_KEY", 0.1),
            ("mistral/mistral-large-latest", "MISTRAL_API_KEY", 0.1),
        ]:
            api_key = os.getenv(api_key_env)
            if not api_key:
                continue
            try:
                response = completion(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    api_key=api_key,
                    temperature=temperature,
                    max_tokens=8192,
                )
                content = response.choices[0].message.content.strip()
                logger.info(
                    "irac_analyzer: model=%s query=%r user_role=%s",
                    model, original_query[:60], user_role,
                )
                return content

            except Exception as exc:
                logger.warning("irac_analyzer: model=%s failed: %s", model, exc)
                continue

        return (
            "IRAC ANALYSIS ERROR: All LLM providers failed. "
            "Check GROQ_API_KEY and MISTRAL_API_KEY environment variables."
        )
