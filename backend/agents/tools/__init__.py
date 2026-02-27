"""Neethi AI CrewAI tools package.

Safety gates (mandatory in every crew pipeline):
    StatuteNormalizationTool      — before every Qdrant search
    CitationVerificationTool      — before every response delivery

Retrieval tools:
    QdrantHybridSearchTool        — hybrid dense+sparse search with weighted RRF,
                                    score boosting, and optional MMR diversity
    SectionLookupTool             — exact act+section payload filter (no embedding)
                                    for direct section number queries

Analysis tools:
    QueryClassifierTool           — LLM-based query classification (Groq fast path);
                                    outputs Query Type to drive weighted RRF weights
    IRACAnalyzerTool              — Legal IRAC analysis (DeepSeek-R1)
    CrossReferenceExpansionTool   — PostgreSQL graph traversal for exception_reference,
                                    subject_to, definition_import, punishment_table links
                                    (lawyer / legal_advisor crews only)
"""

from backend.agents.tools.citation_verification_tool import CitationVerificationTool
from backend.agents.tools.cross_reference_tool import CrossReferenceExpansionTool
from backend.agents.tools.irac_analyzer_tool import IRACAnalyzerTool
from backend.agents.tools.qdrant_search_tool import QdrantHybridSearchTool
from backend.agents.tools.query_classifier_tool import QueryClassifierTool
from backend.agents.tools.section_lookup_tool import SectionLookupTool
from backend.agents.tools.statute_normalization_tool import StatuteNormalizationTool

__all__ = [
    "StatuteNormalizationTool",
    "CitationVerificationTool",
    "QdrantHybridSearchTool",
    "SectionLookupTool",
    "QueryClassifierTool",
    "IRACAnalyzerTool",
    "CrossReferenceExpansionTool",
]
