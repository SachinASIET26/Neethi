"""Quick retrieval quality test for sc_judgments collection.

Tests 4 representative legal queries across different domains.
Prints top-3 results per query with scores and metadata.
"""
import os
import sys

sys.path.insert(0, "/teamspace/studios/this_studio/Phase2")

from backend.rag.hybrid_search import HybridSearcher

TEST_QUERIES = [
    {
        "query": "murder conviction mens rea intention Supreme Court",
        "domain": "criminal",
        "note": "Criminal — substantive law",
    },
    {
        "query": "bail anticipatory arrest accused fundamental rights",
        "domain": "criminal",
        "note": "Criminal — procedural",
    },
    {
        "query": "writ petition fundamental rights article 21 life liberty",
        "domain": "constitutional",
        "note": "Constitutional",
    },
    {
        "query": "civil appeal contract breach damages compensation",
        "domain": "civil",
        "note": "Civil",
    },
]


def run_tests():
    from backend.rag.qdrant_setup import get_qdrant_client
    from backend.rag.embeddings import BGEM3Embedder

    print("Loading embedder...")
    embedder = BGEM3Embedder()
    client = get_qdrant_client()
    searcher = HybridSearcher(qdrant_client=client, embedder=embedder)
    print("Ready.\n")
    print("=" * 70)
    print("SC JUDGMENTS RETRIEVAL QUALITY TEST")
    print("=" * 70)

    for t in TEST_QUERIES:
        print(f"\n[{t['note']}]")
        print(f"Query: {t['query']}")
        print("-" * 50)

        results = searcher.search(
            query=t["query"],
            collection="sc_judgments",
            top_k=3,
            act_filter="none",
            era_filter="none",
        )

        if not results:
            print("  NO RESULTS RETURNED")
            continue

        for i, r in enumerate(results, 1):
            p = r.payload
            print(f"  [{i}] score={r.score:.4f}")
            print(f"      case : {p.get('case_name', 'N/A')}")
            print(f"      year : {p.get('year', 'N/A')}")
            print(f"      type : {p.get('section_type', 'N/A')}")
            print(f"      domain: {p.get('legal_domain', 'N/A')}")
            print(f"      disposal: {p.get('disposal_nature', 'N/A')}")
            snippet = r.text[:150].replace("\n", " ")
            print(f"      text : {snippet}...")
            print()

    print("=" * 70)
    print("TEST COMPLETE")


run_tests()
