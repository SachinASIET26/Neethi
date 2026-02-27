"""Neethi AI CrewAI agent definitions.

Each agent is a factory function (not a module-level singleton) so LLM
clients are created fresh per crew run.

Import pattern:
    from backend.agents.agents import make_query_analyst, make_retrieval_specialist
"""

from backend.agents.agents.citation_checker import make_citation_checker
from backend.agents.agents.legal_reasoner import make_legal_reasoner
from backend.agents.agents.query_analyst import make_query_analyst
from backend.agents.agents.response_formatter import make_response_formatter
from backend.agents.agents.retrieval_specialist import make_retrieval_specialist

__all__ = [
    "make_query_analyst",
    "make_retrieval_specialist",
    "make_legal_reasoner",
    "make_citation_checker",
    "make_response_formatter",
]
