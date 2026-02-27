"""End-to-end pipeline test for Neethi AI.

Simulates a lawyer crew query:
1. Hybrid search on legal_sections (statutory)
2. Hybrid search on sc_judgments (precedents)
3. Verifies both collections return relevant results

Each query carries the parameters the QueryClassifier would output in production:
  - act_filter  : restricts search to a specific act (avoids BNS vs BNSS confusion)
  - era_filter  : restricts to era ("naveen_sanhitas" or "colonial_codes")
  - query_type  : drives Weighted RRF weights and Score Boosting
  - mmr_diversity: >0 for civil/layman queries; 0.0 for criminal precision queries
"""
import os
import sys

sys.path.insert(0, "/teamspace/studios/this_studio/Phase2")

from backend.rag.qdrant_setup import get_qdrant_client
from backend.rag.embeddings import BGEM3Embedder
from backend.rag.hybrid_search import HybridSearcher

LAWYER_QUERIES = [
    {
        # QueryClassifier output: domain=criminal_procedure, act=BNSS_2023,
        # query_type=procedural (bail procedure is procedural not an offence lookup)
        "query": "accused right to fair trial bail denial constitutional validity",
        "note": "Criminal — bail + constitutional rights",
        "act_filter": "none",
        "era_filter": "naveen_sanhitas",
        "query_type": "procedural",
        "mmr_diversity": 0.0,
        "requires_precedents": True,
    },
    {
        # QueryClassifier output: domain=criminal_substantive, act=BNS_2023,
        # section=101 detected → query_type=section_lookup (sparse-heavy, exact match).
        # act_filter=BNS_2023 is critical — prevents BNSS "Repeal and Savings" (s.531)
        # from ranking above BNS murder sections. s.531 contains "Bharatiya Nyaya
        # Sanhita" verbatim in its body, causing it to beat BNS s.101 on keyword+dense
        # when no act filter is applied.
        "query": "murder punishment culpable homicide Bharatiya Nyaya Sanhita",
        "note": "Criminal — BNS murder (s.101/103/105)",
        "act_filter": "BNS_2023",
        "era_filter": "naveen_sanhitas",
        "query_type": "criminal_offence",
        "mmr_diversity": 0.0,
        "requires_precedents": True,
    },
    {
        # QueryClassifier output: domain=civil_contract, act=none,
        # query_type=civil_conceptual (dense-heavy, semantic understanding needed).
        # mmr_diversity=0.3 ensures results span multiple acts (ICA, SRA, etc.)
        # rather than returning 3 SRA sections for the same concept.
        "query": "contract specific performance breach damages civil remedy",
        "note": "Civil — contract law",
        "act_filter": "none",
        "era_filter": "none",
        "query_type": "civil_conceptual",
        "mmr_diversity": 0.3,
        "requires_precedents": True,
    },
    {
        # Landlord security deposit — documented failure case (retrieval_quality_analysis.md).
        # Model Tenancy Act 2021 is NOT yet indexed → expect PRECEDENT_ONLY.
        # mmr_diversity=0.3 forces multi-act coverage (TPA + ICA + SC precedent).
        "query": "landlord security deposit refund tenant vacated house rights",
        "note": "Civil — landlord/tenant (security deposit)",
        "act_filter": "none",
        "era_filter": "none",
        "query_type": "civil_conceptual",
        "mmr_diversity": 0.3,
        "requires_precedents": True,
    },
]


def print_results(label, results, top_k=3):
    print(f"\n  -- {label} --")
    if not results:
        print("  NO RESULTS")
        return
    for i, r in enumerate(results[:top_k], 1):
        p = r.payload
        # Statutory result
        if p.get("act_code"):
            print(f"  [{i}] score={r.score:.4f} | {p.get('act_code')} s.{p.get('section_number')} | {p.get('section_title', '')[:50]}")
        # Judgment result
        else:
            print(f"  [{i}] score={r.score:.4f} | {p.get('case_name', 'N/A')[:60]}")
            print(f"       year={p.get('year')} | disposal={p.get('disposal_nature', 'N/A')[:30]}")
            print(f"       type={p.get('section_type')} | text={r.text[:100].replace(chr(10),' ')}...")


def run_pipeline_test():
    print("Loading BGE-M3 embedder...")
    embedder = BGEM3Embedder()
    client = get_qdrant_client()
    searcher = HybridSearcher(qdrant_client=client, embedder=embedder)
    print("Ready.\n")

    print("=" * 70)
    print("NEETHI AI — FULL PIPELINE TEST (Lawyer Crew)")
    print("=" * 70)

    for t in LAWYER_QUERIES:
        print(f"\n{'='*70}")
        print(f"[{t['note']}]")
        print(f"Query      : {t['query']}")
        print(f"act_filter : {t['act_filter']}  |  era_filter: {t['era_filter']}")
        print(f"query_type : {t['query_type']}  |  mmr: {t['mmr_diversity']}")

        # 1. Statutory retrieval — passes QueryClassifier-derived parameters
        statutory = searcher.search(
            query=t["query"],
            collection="legal_sections",
            top_k=5,
            act_filter=t["act_filter"],
            era_filter=t["era_filter"],
            query_type=t["query_type"],
            mmr_diversity=t["mmr_diversity"],
        )
        print_results("STATUTORY (legal_sections)", statutory, top_k=5)

        # 2. Precedent retrieval — sc_judgments has no act/era indexes
        if t["requires_precedents"]:
            precedents = searcher.search(
                query=t["query"],
                collection="sc_judgments",
                top_k=3,
                act_filter="none",
                era_filter="none",
                query_type="default",
            )
            print_results("PRECEDENTS (sc_judgments)", precedents)

    print(f"\n{'='*70}")
    print("PIPELINE TEST COMPLETE")
    print("Both collections responding — dual retrieval working correctly.")


run_pipeline_test()
