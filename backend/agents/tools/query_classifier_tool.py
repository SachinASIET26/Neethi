"""QueryClassifierTool — Phase 5 query analysis tool.

Calls Groq (Llama 3.3 70B) via LiteLLM to classify the user's legal query.
Fast — designed for the low-latency first step of every crew pipeline.

Output is a structured plaintext block (not JSON) for reliable agent parsing:
    Legal Domain: criminal_substantive
    Intent: information_seeking
    Entities: IPC 302, murder, BNS 103
    Contains Old Statutes: true
    Suggested Act Filter: BNS_2023
    Suggested Era Filter: naveen_sanhitas
    Complexity: simple
    Requires Precedents: false
    Query Type: criminal_offence

The agent reads this output and decides:
    - Whether to call StatuteNormalizationTool (if Contains Old Statutes = true)
    - What act_filter and era_filter to pass to QdrantHybridSearchTool
    - Whether to invoke LegalReasoner (for lawyer/advisor roles + moderate/complex queries)
    - What query_type to pass to QdrantHybridSearchTool (drives weighted RRF)
"""

from __future__ import annotations

import logging
import os
from textwrap import dedent

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from backend.config.llm_config import is_mistral_fallback_active

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Classification prompt
# ---------------------------------------------------------------------------

_CLASSIFICATION_PROMPT = dedent("""\
You are a legal query classifier for an Indian law AI system. Analyze the query below and output ONLY the structured classification — no explanations, no extra text.

USER ROLE: {user_role}
QUERY: {query}

Output EXACTLY this format (fill in values, keep the labels unchanged):

Legal Domain: <one of: criminal_substantive | criminal_procedural | civil | corporate | constitutional | family | property | labor | consumer | evidence | general>
Intent: <one of: information_seeking | section_lookup | case_analysis | document_drafting | procedure_guidance | rights_query>
Entities: <comma-separated list of legal entities found: section numbers, act names, case names, legal terms — or NONE>
Contains Old Statutes: <true if query mentions IPC/CrPC/IEA/Section 302/Section 420/Section 376 etc., else false>
Suggested Act Filter: <canonical act code if query clearly targets one act: BNS_2023 | BNSS_2023 | BSA_2023 | IPC_1860 | CrPC_1973 | IEA_1872 | NONE>
Suggested Era Filter: <naveen_sanhitas if query is about BNS/BNSS/BSA | colonial_codes if query is about IPC/CrPC/IEA | NONE if mixed or unclear>
Complexity: <simple | moderate | complex>
Requires Precedents: <true if query asks about case law, landmark judgments, judicial interpretation, Supreme Court rulings, or precedent — else false>
Query Type: <one of: section_lookup | criminal_offence | civil_conceptual | procedural | old_statute | default>

RULES:
- If the query mentions "BNS", "BNSS", "BSA", "Bharatiya", "2024", "new law" → Suggested Era Filter: naveen_sanhitas
- If the query mentions "IPC", "CrPC", "IEA", "Indian Penal Code", "old law" → Contains Old Statutes: true
- simple = single factual question, moderate = multi-part or requires analysis, complex = full case analysis or IRAC needed
- For citizen role, assume information_seeking unless clearly asking to draft a document
- For lawyer/legal_advisor role, lean toward case_analysis for open-ended queries
- Requires Precedents rules (apply in order):
  1. ALWAYS false for pure section lookups: "what does section X say", "define X under BNS/BNSS/BSA", "text of section N"
  2. ALWAYS true if query contains: "case", "judgment", "judgement", "precedent", "landmark", "Supreme Court", "HC ruled", "court held", "judicial", "interpretation", "appeal", "SC held", "bench"
  3. For user_role = lawyer OR legal_advisor: true if Complexity = moderate or complex, OR Intent = case_analysis — even without explicit judgment keywords
  4. For user_role = citizen OR police: false unless rule 2 applies
- Query Type rules (drives RRF weights — pick EXACTLY ONE):
  section_lookup   → Intent = section_lookup (direct section text queries: "what does s.103 say")
  criminal_offence → Legal Domain = criminal_substantive AND Intent ≠ section_lookup
  civil_conceptual → Legal Domain in {civil, property, family, labor, consumer, corporate} AND Intent ≠ section_lookup
  procedural       → Legal Domain = criminal_procedural OR Intent = procedure_guidance
  old_statute      → Contains Old Statutes = true AND query is about old act text (not normalized)
  default          → everything else (constitutional, evidence, general)
""")

# ---------------------------------------------------------------------------
# Input schema
# ---------------------------------------------------------------------------


class QueryClassifierInput(BaseModel):
    """Input for the QueryClassifierTool."""

    query: str = Field(..., description="The raw user legal query to classify")
    user_role: str = Field(
        "citizen",
        description="User role: citizen | lawyer | legal_advisor | police",
    )


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------

class QueryClassifierTool(BaseTool):
    """Classify a legal query by domain, intent, entities, and search parameters.

    Uses Groq (Llama 3.3 70B) for fast classification. Output tells the agent:
    - What legal domain the query belongs to
    - What the user intends (information, drafting, case analysis, etc.)
    - Whether old statutes (IPC/CrPC/IEA) are mentioned (→ call StatuteNormalizationTool)
    - What act_filter/era_filter to apply to Qdrant search

    Usage::

        tool = QueryClassifierTool()
        result = tool.run({"query": "What is punishment for murder?", "user_role": "citizen"})
    """

    name: str = "QueryClassifierTool"
    description: str = (
        "Classify a legal query to determine domain, intent, entities, and search parameters. "
        "Input: {query: str, user_role: str}. "
        "Output: structured classification with Legal Domain, Intent, Entities, "
        "Contains Old Statutes (true/false), Suggested Act Filter, Suggested Era Filter, "
        "Complexity, Requires Precedents (true/false — whether to search SC judgment collection), "
        "and Query Type (section_lookup|criminal_offence|civil_conceptual|procedural|old_statute|default — "
        "pass this to QdrantHybridSearchTool as query_type to enable weighted RRF)."
    )
    args_schema: type[BaseModel] = QueryClassifierInput

    def _run(self, query: str | dict, user_role: str = "citizen") -> str:  # type: ignore[override]
        """Call Groq LLM (sync) to classify the query.

        Synchronous — CrewAI's BaseTool.run() calls _run() synchronously.
        Uses litellm.completion() (sync) instead of acompletion() to avoid
        the 'asyncio.run() cannot be called from a running event loop' error
        that occurs when async def _run is called from within uvicorn's loop.

        Handles both dict input and keyword args.
        """
        from litellm import completion

        # Handle dict input
        if isinstance(query, dict):
            user_role = query.get("user_role", "citizen")
            query = query.get("query", "")

        if not query.strip():
            return "CLASSIFICATION ERROR: Empty query provided."

        prompt = _CLASSIFICATION_PROMPT.format(query=query, user_role=user_role)

        try:
            if is_mistral_fallback_active():
                _model = "mistral/mistral-small-latest"
                _api_key = os.getenv("MISTRAL_API_KEY")
            else:
                _model = "groq/llama-3.3-70b-versatile"
                _api_key = os.getenv("GROQ_API_KEY")

            response = completion(
                model=_model,
                messages=[{"role": "user", "content": prompt}],
                api_key=_api_key,
                temperature=0.1,
                max_tokens=512,
            )
            classification = response.choices[0].message.content.strip()
            classification = _enforce_precedents_rule(classification, user_role)
            logger.info(
                "query_classifier: query=%r role=%s domain=%s requires_precedents=%s",
                query[:60],
                user_role,
                _extract_field(classification, "Legal Domain"),
                _extract_field(classification, "Requires Precedents"),
            )
            return f"QUERY CLASSIFICATION:\n{classification}"

        except Exception as exc:
            logger.exception("query_classifier: LLM call failed: %s", exc)
            return _fallback_classification(query, user_role)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_field(text: str, field_name: str) -> str:
    """Extract a field value from the structured classification output."""
    for line in text.splitlines():
        if line.startswith(f"{field_name}:"):
            return line.split(":", 1)[1].strip()
    return "unknown"


def _enforce_precedents_rule(classification: str, user_role: str) -> str:
    """Post-process LLM classification to enforce Requires Precedents rules in Python.

    LLMs (especially Mistral Small on fallback) sometimes return
    'Requires Precedents: false' for lawyer/advisor + moderate/complex queries
    even when the prompt says to set it true.  This function enforces the same
    4-rule logic as the prompt, overriding the LLM output when necessary.

    Rules (mirror the prompt exactly):
        1. Pure section-lookup intent → always false (don't override to true)
        2. Explicit judgment keywords in the raw text → true (LLM already set it)
        3. lawyer / legal_advisor + complexity moderate or complex → force true
        4. citizen / police → no override (false unless rule 2 fired)

    Only modifies the 'Requires Precedents:' line — all other fields unchanged.
    """
    if user_role not in ("lawyer", "legal_advisor"):
        return classification  # Rule 4: no change for citizen/police

    intent     = _extract_field(classification, "Intent").lower()
    complexity = _extract_field(classification, "Complexity").lower()
    current    = _extract_field(classification, "Requires Precedents").lower()

    # Rule 1: pure section-lookup — never force true
    if intent == "section_lookup":
        return classification

    # Rule 3: professional role + moderate/complex → must be true
    if complexity in ("moderate", "complex") and current != "true":
        logger.info(
            "query_classifier: enforcing Requires Precedents: true "
            "(role=%s complexity=%s llm_said=%s)",
            user_role, complexity, current,
        )
        lines = classification.splitlines()
        new_lines = []
        for line in lines:
            if line.startswith("Requires Precedents:"):
                new_lines.append("Requires Precedents: true")
            else:
                new_lines.append(line)
        return "\n".join(new_lines)

    return classification


def _fallback_classification(query: str, user_role: str) -> str:
    """Rule-based fallback when Groq is unavailable."""
    query_lower = query.lower()

    # Domain detection
    domain = "general"
    if any(w in query_lower for w in ["murder", "theft", "rape", "assault", "fir", "arrest", "bail", "bns", "ipc"]):
        domain = "criminal_substantive"
    elif any(w in query_lower for w in ["crpc", "bnss", "procedure", "cognizable", "warrant"]):
        domain = "criminal_procedural"
    elif any(w in query_lower for w in ["company", "gst", "contract", "corporate", "it act"]):
        domain = "corporate"
    elif any(w in query_lower for w in ["divorce", "marriage", "custody", "maintenance"]):
        domain = "family"

    # Old statute detection
    has_old = any(w in query_lower for w in ["ipc", "crpc", "iea", "indian penal", "section 302", "section 420", "section 376"])

    # Era filter
    era = "NONE"
    if any(w in query_lower for w in ["bns", "bnss", "bsa", "bharatiya", "2024", "new law"]):
        era = "naveen_sanhitas"
    elif has_old:
        era = "colonial_codes"

    complexity = "moderate" if user_role in ("lawyer", "legal_advisor") else "simple"

    # Pure section-lookup detection — never needs precedents
    _section_lookup_words = ("what does section", "text of section", "define section",
                              "what is section", "section say", "full text")
    _is_pure_section_lookup = any(w in query_lower for w in _section_lookup_words)

    # Explicit judgment/case keywords
    _explicit_precedent_words = [
        "case", "judgment", "judgement", "precedent", "landmark", "supreme court",
        "high court", "sc held", "hc ruled", "court held", "bench", "ruled", "appeal",
        "judicial", "interpretation",
    ]
    _explicit_precedent = any(w in query_lower for w in _explicit_precedent_words)

    if _is_pure_section_lookup:
        # Rule 1: pure lookup — never needs precedents
        requires_precedents = False
    elif _explicit_precedent:
        # Rule 2: explicit judgment keywords — always true
        requires_precedents = True
    elif user_role in ("lawyer", "legal_advisor"):
        # Rule 3: for professional roles, default true for moderate/complex queries
        # (fallback marks lawyer/advisor as moderate by default above)
        requires_precedents = complexity in ("moderate", "complex")
    else:
        requires_precedents = False

    # Derive query_type from domain + intent
    if _is_pure_section_lookup:
        query_type_str = "section_lookup"
    elif has_old and not any(w in query_lower for w in ["bns", "bnss", "bsa", "bharatiya"]):
        query_type_str = "old_statute"
    elif domain == "criminal_substantive":
        query_type_str = "criminal_offence"
    elif domain == "criminal_procedural":
        query_type_str = "procedural"
    elif domain in ("civil", "property", "family", "labor", "consumer", "corporate"):
        query_type_str = "civil_conceptual"
    else:
        query_type_str = "default"

    return (
        f"QUERY CLASSIFICATION (fallback — LLM unavailable):\n"
        f"Legal Domain: {domain}\n"
        f"Intent: information_seeking\n"
        f"Entities: NONE\n"
        f"Contains Old Statutes: {str(has_old).lower()}\n"
        f"Suggested Act Filter: NONE\n"
        f"Suggested Era Filter: {era}\n"
        f"Complexity: {complexity}\n"
        f"Requires Precedents: {str(requires_precedents).lower()}\n"
        f"Query Type: {query_type_str}"
    )
