"""Retrieval diagnostic — checks what BNS sections are actually indexed in Qdrant.

Run this on Lightning AI to understand why the assault query returns 0/irrelevant results.

Usage (from project root):
    python backend/tests/diagnose_retrieval.py

What it checks:
    1. Which BNS_2023 assault/hurt sections exist in Qdrant by scrolling metadata
    2. Whether legal_domain values are set on indexed BNS sections
    3. Hybrid search output for the assault query with and without legal_domain_filter
    4. Suggests the correct smoke test query (one that actually hits indexed sections)
"""

from __future__ import annotations

import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parents[2]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from dotenv import load_dotenv
load_dotenv(_project_root / ".env")

import logging
logging.getLogger("LiteLLM").setLevel(logging.CRITICAL)

from qdrant_client.models import Filter, FieldCondition, MatchValue

from backend.rag.qdrant_setup import get_qdrant_client, COLLECTION_LEGAL_SECTIONS

DIVIDER = "=" * 70
SECTION  = "-" * 70


def check_bns_assault_sections(client):
    """Scroll Qdrant to find BNS sections related to assault/hurt by keyword."""
    print(f"\n{DIVIDER}")
    print("  CHECK 1: BNS_2023 sections with 'assault' or 'hurt' in title/text")
    print(DIVIDER)

    # Scroll all BNS_2023 sections (no vector needed — payload only)
    all_bns, _ = client.scroll(
        collection_name=COLLECTION_LEGAL_SECTIONS,
        scroll_filter=Filter(must=[
            FieldCondition(key="act_code", match=MatchValue(value="BNS_2023")),
        ]),
        limit=500,
        with_payload=True,
        with_vectors=False,
    )

    print(f"  Total BNS_2023 sections in Qdrant: {len(all_bns)}")

    # Filter for assault/hurt sections
    keywords = ["assault", "hurt", "force", "criminal force", "voluntarily causing"]
    matches = []
    for point in all_bns:
        p = point.payload or {}
        title = (p.get("section_title") or "").lower()
        text  = (p.get("text") or p.get("section_text") or "").lower()
        sec   = p.get("section_number") or "?"
        if any(kw in title or kw in text[:200] for kw in keywords):
            matches.append((sec, p.get("section_title"), p.get("legal_domain")))

    if matches:
        print(f"\n  Found {len(matches)} assault/hurt/force sections:")
        for sec, title, domain in sorted(matches, key=lambda x: x[0] or ""):
            print(f"    BNS s.{sec} — {title!r}  [legal_domain={domain!r}]")
    else:
        print("\n  ⚠️  NO assault/hurt/force sections found in BNS_2023!")
        print("  The BNS assault sections (BNS 115 hurt, BNS 351 assault) are NOT indexed.")
        print("  This is a DATA COVERAGE GAP — the query cannot be answered from the DB.")


def check_legal_domain_values(client):
    """Show all distinct legal_domain values in BNS_2023 sections."""
    print(f"\n{DIVIDER}")
    print("  CHECK 2: legal_domain values in indexed BNS_2023 sections")
    print(DIVIDER)

    all_bns, _ = client.scroll(
        collection_name=COLLECTION_LEGAL_SECTIONS,
        scroll_filter=Filter(must=[
            FieldCondition(key="act_code", match=MatchValue(value="BNS_2023")),
        ]),
        limit=500,
        with_payload=True,
        with_vectors=False,
    )

    domain_counts: dict[str, int] = {}
    for point in all_bns:
        domain = (point.payload or {}).get("legal_domain") or "NULL/not-set"
        domain_counts[domain] = domain_counts.get(domain, 0) + 1

    if domain_counts:
        print("  legal_domain distribution for BNS_2023:")
        for domain, count in sorted(domain_counts.items(), key=lambda x: -x[1]):
            print(f"    {domain!r:35s}  {count} sections")
    else:
        print("  No BNS_2023 sections found.")


def check_specific_sections(client):
    """Check if the specific assault/murder/robbery sections are indexed."""
    print(f"\n{DIVIDER}")
    print("  CHECK 3: Specific section lookup (BNS 103, 115, 309, 351)")
    print(DIVIDER)

    sections_to_check = [
        ("BNS_2023", "103", "Murder"),
        ("BNS_2023", "115", "Voluntarily causing hurt"),
        ("BNS_2023", "309", "Robbery"),
        ("BNS_2023", "351", "Assault"),
        ("BNS_2023", "318", "Cheating"),
        ("BNSS_2023", "173", "FIR registration"),
        ("BNSS_2023", "482", "Anticipatory bail"),
    ]

    for act, sec, label in sections_to_check:
        hits, _ = client.scroll(
            collection_name=COLLECTION_LEGAL_SECTIONS,
            scroll_filter=Filter(must=[
                FieldCondition(key="act_code",       match=MatchValue(value=act)),
                FieldCondition(key="section_number", match=MatchValue(value=sec)),
            ]),
            limit=1,
            with_payload=True,
            with_vectors=False,
        )
        status = "✓ INDEXED" if hits else "✗ NOT INDEXED"
        print(f"  {act} s.{sec:5s} ({label:<30s})  {status}")


def run_search_comparison(client):
    """Compare hybrid search results with and without legal_domain_filter."""
    print(f"\n{DIVIDER}")
    print("  CHECK 4: Hybrid search — assault queries (after dedup fix)")
    print(DIVIDER)

    try:
        from backend.rag.embeddings import BGEM3Embedder
        from backend.rag.hybrid_search import HybridSearcher

        embedder = BGEM3Embedder()
        searcher = HybridSearcher(qdrant_client=client, embedder=embedder)

        queries = [
            (
                "short keyword",
                "physical assault criminal force hurt BNS 2023",
            ),
            (
                "actual smoke query",
                "Someone slapped me in public and threatened me. "
                "What is the law against physical assault in India? "
                "What can I do and what sections apply under BNS 2023?",
            ),
        ]

        for label, query in queries:
            print(f"\n  [{label}]")
            print(f"  Query: {query[:80]!r}")
            print()

            # The correct search: era_filter only, no domain filter
            results = searcher.search(query=query, era_filter="naveen_sanhitas", top_k=5)
            print(f"  era_filter='naveen_sanhitas', no domain filter → {len(results)} result(s):")
            for r in results:
                print(f"    {r.act_code} s.{r.section_number} — {r.section_title}")

    except ImportError:
        print("  ⚠️  FlagEmbedding not available — skipping search comparison.")
        print("  Run on Lightning AI (GPU instance) to see search results.")


def suggest_good_smoke_query(client):
    """Find queries that will actually return indexed content."""
    print(f"\n{DIVIDER}")
    print("  CHECK 5: What sections ARE indexed? (sample BNS sections)")
    print(DIVIDER)

    all_bns, _ = client.scroll(
        collection_name=COLLECTION_LEGAL_SECTIONS,
        scroll_filter=Filter(must=[
            FieldCondition(key="act_code", match=MatchValue(value="BNS_2023")),
        ]),
        limit=20,
        with_payload=True,
        with_vectors=False,
    )

    print(f"  First 20 BNS_2023 sections in Qdrant:")
    for point in all_bns:
        p = point.payload or {}
        sec   = p.get("section_number") or "?"
        title = p.get("section_title") or "(no title)"
        domain = p.get("legal_domain") or "NULL"
        print(f"    BNS s.{sec:<6} {title:<50}  [{domain}]")

    print(f"\n  → Use section numbers shown above to build reliable smoke queries.")
    print(f"  → BNS 103 (Murder) is tested in Phase 4 — it should be indexed.")


def main():
    print("\nNeethi AI — Retrieval Diagnostic")
    print("Checking what's actually in Qdrant vs what the smoke test expects\n")

    try:
        client = get_qdrant_client()
    except Exception as exc:
        print(f"ERROR: Could not connect to Qdrant: {exc}")
        sys.exit(1)

    # Check collection exists
    collections = [c.name for c in client.get_collections().collections]
    if COLLECTION_LEGAL_SECTIONS not in collections:
        print(f"ERROR: Collection '{COLLECTION_LEGAL_SECTIONS}' does not exist.")
        print(f"Available collections: {collections}")
        sys.exit(1)

    print(f"Connected to Qdrant. Collection '{COLLECTION_LEGAL_SECTIONS}' found.")

    check_bns_assault_sections(client)
    check_legal_domain_values(client)
    check_specific_sections(client)
    suggest_good_smoke_query(client)
    run_search_comparison(client)

    print(f"\n{DIVIDER}")
    print("  DIAGNOSTIC COMPLETE")
    print(DIVIDER)


if __name__ == "__main__":
    main()
