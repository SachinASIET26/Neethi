"""Crew configurations for Neethi AI — Phase 5.

Defines four crew factories corresponding to the four user roles.
All crews use Process.sequential — legal reasoning requires strict ordering.

ENFORCED ORDERING RULE (corrected from plan.md):
    CitationChecker MUST run BEFORE ResponseFormatter in every crew.
    The formatter only receives verified content — never raw agent output.

Correct order for all crews:
    QueryAnalyst → RetrievalSpecialist → [LegalReasoner] → CitationChecker → ResponseFormatter

Crew configurations:

    Layman / Citizen:
        QueryAnalyst → RetrievalSpecialist → CitationChecker → ResponseFormatter

    Lawyer:
        QueryAnalyst → RetrievalSpecialist → LegalReasoner → CitationChecker → ResponseFormatter

    Legal Advisor (Corporate):
        QueryAnalyst → RetrievalSpecialist → LegalReasoner → CitationChecker → ResponseFormatter
        (Same pipeline as Lawyer — task descriptions differ by domain/format)

    Police:
        QueryAnalyst → RetrievalSpecialist → CitationChecker → ResponseFormatter
        (No LegalReasoner — police need procedural steps, not IRAC analysis)

Usage::

    from backend.agents.crew_config import make_lawyer_crew, get_crew_for_role

    # Async execution (recommended — supports concurrent multi-user requests):
    crew = make_lawyer_crew()
    result = await crew.akickoff(inputs={
        "query": "What is the punishment for murder under BNS?",
        "user_role": "lawyer",
    })

    # Streaming (SSE endpoint):
    crew = make_lawyer_crew(stream=True)
    streaming = await crew.akickoff(inputs={...})
    async for chunk in streaming:
        print(chunk.content, chunk.agent_role)
"""

from __future__ import annotations

import logging

from crewai import Crew, Process, Task

from backend.agents.agents import (
    make_citation_checker,
    make_legal_reasoner,
    make_query_analyst,
    make_response_formatter,
    make_retrieval_specialist,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Crew 1: Layman / Citizen Crew
# ---------------------------------------------------------------------------

def make_layman_crew(stream: bool = False) -> Crew:
    """Crew for citizen/layman legal queries.

    Pipeline: QueryAnalyst → RetrievalSpecialist → CitationChecker → ResponseFormatter

    Output style: Simple language, step-by-step guidance, practical next steps.
    No IRAC analysis — citizens need clear answers, not legal frameworks.

    Args:
        stream: If True, enables token-level SSE streaming via crew.akickoff().
                Use False (default) for standard async request/response.
    """
    query_analyst = make_query_analyst()
    retrieval_specialist = make_retrieval_specialist()
    citation_checker = make_citation_checker()
    response_formatter = make_response_formatter()

    classify_task = Task(
        description=(
            "Classify the following legal query from a citizen and determine what to search for.\n\n"
            "Query: {query}\nUser Role: {user_role}\n\n"
            "Steps:\n"
            "1. Call QueryClassifierTool with the query and user_role.\n"
            "2. If Contains Old Statutes is true: call StatuteNormalizationTool for each "
            "old statute reference found.\n"
            "3. Output the classification result and normalized statute references (if any) "
            "for the retrieval step."
        ),
        expected_output=(
            "Structured classification including: Legal Domain, Intent, Entities, "
            "whether old statutes need normalization, suggested act/era filters, "
            "and normalized new statute references if applicable."
        ),
        agent=query_analyst,
    )

    retrieval_task = Task(
        description=(
            "Search the Neethi AI database using the classification.\n\n"
            "Query: {query}\nUser Role: {user_role}\n\n"
            "Steps:\n"
            "1. If old statutes found: call StatuteNormalizationTool.\n"
            "2. Search legal_sections via QdrantHybridSearchTool (top_k=3, use act/era filters).\n"
            "3. If 0 results, retry with broader query and no filters.\n"
            "4. If 'Requires Precedents: true', search sc_judgments (top_k=3).\n"
            "5. Final Answer: Return ONLY what the tools returned verbatim. "
            "Output 'NO_RELEVANT_DOCUMENTS_FOUND' ONLY if ALL calls return 0 results."
        ),
        expected_output=(
            "Top legal sections (statutory) with act code, section number, title, text preview, "
            "and procedural metadata — PLUS Supreme Court judgment chunks if 'Requires Precedents' "
            "was true — OR the exact string 'NO_RELEVANT_DOCUMENTS_FOUND' only when all tool calls "
            "returned 0 results."
        ),
        agent=retrieval_specialist,
        context=[classify_task],
    )

    verify_task = Task(
        description=(
            "Verify every section cited in the retrieved results AND assess whether each "
            "section actually applies to the user's legal situation.\n\n"
            "Query: {query}\n\n"
            "Steps:\n"
            "1. For each distinct act_code + section_number pair in the retrieval output: "
            "call CitationVerificationTool.\n"
            "   IMPORTANT: pass act_code as 'BNS_2023', 'BNSS_2023', or 'BSA_2023' — "
            "never the short form 'BNS', 'BNSS', or 'BSA'.\n"
            "2. The tool returns one of three statuses:\n"
            "   - VERIFIED: section exists and data is complete.\n"
            "   - VERIFIED_INCOMPLETE: section exists but title or text is missing. "
            "Keep but flag with '(incomplete data)'.\n"
            "   - NOT_FOUND: section does not exist. Remove it entirely.\n"
            "3. Remove any NOT_FOUND citations. Do NOT rename or renumber any section.\n"
            "4. RELEVANCE ASSESSMENT — run for every VERIFIED or VERIFIED_INCOMPLETE section:\n"
            "   Read the section's actual legal text (from the tool output) and the user's query. "
            "Ask: does this section's rule DIRECTLY govern the user's legal situation?\n"
            "   Classify each section as:\n"
            "   - RELEVANT: The section's rule is the operative legal authority for this situation. "
            "Example: query about unpaid wages → section defining employer obligations = RELEVANT.\n"
            "   - TANGENTIAL: Section touches a related concept but is NOT the operative rule. "
            "Keep it but label clearly as '(contextual — not primary authority)'. "
            "Example: query about security deposit recovery → section on burden of proof for "
            "proving a landlord-tenant relationship exists = TANGENTIAL "
            "(relationship is admitted; section doesn't govern what happens to the deposit).\n"
            "   - NOT_APPLICABLE: Section only matched due to keyword overlap — its rule has no "
            "bearing on the user's situation. Remove it, same as NOT_FOUND. "
            "Example: query about security deposit → arbitration deposit section = NOT_APPLICABLE "
            "(unless the rental agreement includes an arbitration clause).\n"
            "5. Output the final statutory citations list with status for each: "
            "RELEVANT, TANGENTIAL (contextual), or removed (NOT_FOUND / NOT_APPLICABLE).\n"
            "6. PRECEDENT ASSESSMENT — for each SC case/judgment in the retrieval output:\n"
            "   Read the case excerpt and the user's query. Classify as:\n"
            "   - RELEVANT_PRECEDENT: Case directly addresses the user's legal situation. "
            "Example: SC case about landlord refusing to refund a security deposit = "
            "RELEVANT_PRECEDENT for a security deposit recovery query.\n"
            "   - NOT_APPLICABLE_PRECEDENT: Case only shares keywords but not the core legal issue.\n"
            "   List all RELEVANT_PRECEDENT cases in your output.\n"
            "7. Set overall verification status:\n"
            "   - VERIFIED: 1+ RELEVANT statutory sections exist.\n"
            "   - PRECEDENT_ONLY: Zero RELEVANT statutory sections but 1+ RELEVANT_PRECEDENT "
            "cases exist. Our database has SC precedent coverage but not full statutory coverage "
            "for this area.\n"
            "   - UNVERIFIED: Zero RELEVANT statutory sections AND zero RELEVANT_PRECEDENT cases."
        ),
        expected_output=(
            "Statutory citations classified as RELEVANT, TANGENTIAL (contextual), or removed "
            "(NOT_FOUND / NOT_APPLICABLE). SC precedents classified as RELEVANT_PRECEDENT or "
            "NOT_APPLICABLE_PRECEDENT. Overall verification status: VERIFIED (has relevant statute), "
            "PRECEDENT_ONLY (has relevant SC cases but no relevant statute), or UNVERIFIED (neither)."
        ),
        agent=citation_checker,
        context=[retrieval_task],
    )

    format_task = Task(
        description=(
            "Format the verified legal information for a citizen in plain, accessible language.\n\n"
            "Query: {query}\nUser Role: citizen\n\n"
            "CRITICAL FIRST CHECK — three cases:\n"
            "  CASE A (UNVERIFIED): Previous step shows UNVERIFIED with zero RELEVANT statutory "
            "sections AND zero RELEVANT_PRECEDENT cases → output ONLY the cannot-verify message "
            "(see your backstory). Do NOT attempt to answer from your own knowledge.\n"
            "  CASE B (PRECEDENT_ONLY): Zero RELEVANT statutory sections but RELEVANT_PRECEDENT "
            "SC cases exist → proceed: answer based on SC precedents as the primary authority. "
            "Note clearly: 'Our database does not currently index [the specific statute, e.g. "
            "Transfer of Property Act / State Rent Control Acts] for this area. The answer below "
            "is based on Supreme Court judgments from our database.' Recommend checking "
            "legislative.gov.in for the statute text and consulting a lawyer.\n"
            "  CASE C (VERIFIED): RELEVANT statutory sections exist → proceed normally.\n\n"
            "Otherwise, format requirements:\n"
            "- Use simple, jargon-free language (8th grade reading level)\n"
            "- Lead with a direct answer to the question\n"
            "- Number the key points (1, 2, 3...)\n"
            "- Include 'What this means for you' section\n"
            "- Include 'What to do next' with actionable steps\n"
            "- List verified citations at the bottom\n"
            "- Show verification status prominently\n"
            "- CITATIONS RULE: In your Sources/Citations section:\n"
            "  * List RELEVANT sections as primary legal authority "
            "(e.g. 'Section X directly governs...')\n"
            "  * List TANGENTIAL sections separately under 'Related Law (for context)' if any — "
            "never present them as primary authority for the user's specific situation.\n"
            "  * Do NOT include sections the CitationChecker removed as NOT_APPLICABLE.\n"
            "  * Do NOT add section numbers from your own knowledge.\n"
            "  * List RELEVANT_PRECEDENT SC cases under 'Supreme Court Precedents' — include "
            "case name, year, and one sentence on what it decided.\n"
            "- End with: 'This is AI-assisted legal information. Consult a qualified lawyer "
            "for advice specific to your situation.'"
        ),
        expected_output=(
            "Either: a clearly formatted legal response in plain English with direct answer, "
            "numbered key points, RELEVANT verified citations or RELEVANT_PRECEDENT SC cases "
            "as primary authority, TANGENTIAL citations listed separately as context-only, "
            "verification status badge (VERIFIED / PRECEDENT_ONLY / UNVERIFIED), "
            "actionable next steps, and professional disclaimer — "
            "OR the standard cannot-verify message only if status is UNVERIFIED with zero "
            "RELEVANT sections and zero RELEVANT_PRECEDENT cases."
        ),
        agent=response_formatter,
        context=[verify_task],
    )

    return Crew(
        agents=[query_analyst, retrieval_specialist, citation_checker, response_formatter],
        tasks=[classify_task, retrieval_task, verify_task, format_task],
        process=Process.sequential,
        verbose=False,
        stream=stream,
    )


# ---------------------------------------------------------------------------
# Crew 2: Lawyer Analysis Crew
# ---------------------------------------------------------------------------

def make_lawyer_crew(stream: bool = False) -> Crew:
    """Crew for lawyer legal analysis queries.

    Pipeline: QueryAnalyst → RetrievalSpecialist → LegalReasoner → CitationChecker → ResponseFormatter

    Output style: IRAC format, technical precision, multiple case comparison.

    Args:
        stream: If True, enables token-level SSE streaming via crew.akickoff().
    """
    query_analyst = make_query_analyst()
    retrieval_specialist = make_retrieval_specialist()
    legal_reasoner = make_legal_reasoner()
    citation_checker = make_citation_checker()
    response_formatter = make_response_formatter()

    classify_task = Task(
        description=(
            "Classify the following legal query from a lawyer.\n\n"
            "Query: {query}\nUser Role: {user_role}\n\n"
            "Steps:\n"
            "1. Call QueryClassifierTool with the query and user_role='lawyer'.\n"
            "2. If Contains Old Statutes is true: call StatuteNormalizationTool for each "
            "old statute reference.\n"
            "3. Output classification and normalized references for retrieval. "
            "IMPORTANT: include the 'Requires Precedents' field from the classification — "
            "the RetrievalSpecialist will use it to decide whether to also search SC judgments."
        ),
        expected_output=(
            "Detailed classification with legal domain, intent, all extracted entities "
            "(section numbers, act names, legal terms), statute normalizations, "
            "recommended search parameters, and Requires Precedents (true/false)."
        ),
        agent=query_analyst,
    )

    retrieval_task = Task(
        description=(
            "Retrieve legal material for IRAC analysis.\n\n"
            "Query: {query}\nUser Role: {user_role}\n\n"
            "1. Search legal_sections via QdrantHybridSearchTool (top_k=3, use filters).\n"
            "2. If 'Requires Precedents: true', search sc_judgments (top_k=3).\n"
            "3. Final Answer: Return ONLY tool output verbatim. Include BOTH sections."
        ),
        expected_output=(
            "STATUTORY RESULTS (up to 5 sections with complete metadata) "
            "followed by PRECEDENT RESULTS (up to 3 SC judgments) when sc_judgments was searched — "
            "both sections required and labelled. "
            "OR the exact string 'NO_RELEVANT_DOCUMENTS_FOUND' (only when all tools returned 0 results)."
        ),
        agent=retrieval_specialist,
        context=[classify_task],
    )

    irac_task = Task(
        description=(
            "Perform structured IRAC analysis on the retrieved legal sections.\n\n"
            "Query: {query}\nUser Role: lawyer\n\n"
            "Steps:\n"
            "1. Call IRACAnalyzerTool with the COMPLETE output from the RetrievalSpecialist "
            "as retrieved_sections — this MUST include BOTH the STATUTORY RESULTS and the "
            "PRECEDENT RESULTS sections, verbatim, as a single string. Do NOT truncate, "
            "summarize, or strip out the PRECEDENT RESULTS block. The IRAC tool needs the "
            "SC case names from PRECEDENT RESULTS to produce a legally complete analysis. "
            "Also pass the original query as original_query.\n"
            "2. Ensure the IRAC analysis ONLY cites sections present in the retrieved results. "
            "Do NOT add section numbers from your own knowledge.\n"
            "3. SC CASE RULE: The IRACAnalyzerTool will use only case names from PRECEDENT "
            "RESULTS. Do NOT add any case name in your own commentary that was not in the "
            "PRECEDENT RESULTS. Fabricating case names is a critical safety failure.\n"
            "4. Return the complete IRAC analysis with confidence level.\n"
            "TOOL FAILURE RULE: If IRACAnalyzerTool returns 'IRAC ANALYSIS ERROR', do NOT write "
            "an IRAC analysis from your own knowledge. Return exactly: "
            "'IRAC TOOL FAILED: [paste the error message]' as your Final Answer."
        ),
        expected_output=(
            "Full IRAC analysis: Issue (precise legal question), Rule (applicable sections), "
            "Application (how rules apply), Conclusion (legal outcome), "
            "Applicable Sections list, Applicable Precedents list (SC cases or 'No SC precedents'), "
            "and Confidence indicator (high/medium/low)."
        ),
        agent=legal_reasoner,
        context=[retrieval_task],
    )

    verify_task = Task(
        description=(
            "Verify every section cited in the IRAC analysis.\n\n"
            "Query: {query}\n\n"
            "Steps:\n"
            "0. YEAR-AS-SECTION GUARD (run first, before any tool call): "
            "Scan all cited section numbers in the IRAC analysis. "
            "If any section number is a 4-digit year (2020, 2021, 2022, 2023, 2024, 2025, 2026): "
            "flag it immediately as 'HALLUCINATED (year used as section number — not a real section)' "
            "and remove it WITHOUT calling CitationVerificationTool. "
            "BNS/BNSS/BSA section numbers are at most 3 digits. No 4-digit section exists.\n"
            "1. Parse the IRAC analysis for all remaining cited BNS/BNSS/BSA sections "
            "(act_code + section_number) after the year guard.\n"
            "2. Call CitationVerificationTool for each distinct BNS/BNSS/BSA citation. "
            "IMPORTANT: pass act_code as 'BNS_2023', 'BNSS_2023', or 'BSA_2023' — "
            "never the short form 'BNS', 'BNSS', or 'BSA'. "
            "Do NOT call CitationVerificationTool for laws outside the database. "
            "Indexed acts: BNS_2023, BNSS_2023, BSA_2023, IPC_1860, CrPC_1973, IEA_1872, "
            "SRA_1963, TPA_1882, CPA_2019, CPC_1908, LA_1963. "
            "For anything else (Companies Act, SEBI, IT Act, GST) — label UNVERIFIED (out-of-scope).\n"
            "3. The tool returns one of three statuses:\n"
            "   - VERIFIED: section exists and data is complete. Keep and use normally.\n"
            "   - VERIFIED_INCOMPLETE: section exists but title or legal text is missing. "
            "Keep the citation but mark it '(incomplete data)' and do NOT rely on its "
            "procedural metadata (cognizable/bailable/court) for legal conclusions.\n"
            "   - NOT_FOUND: section does not exist. Remove it entirely.\n"
            "4. Remove NOT_FOUND citations and note the removal. "
            "Do NOT rename, renumber, or substitute a different section number. "
            "The section_number in your output must be identical to the input — never change it.\n"
            "4b. RELEVANCE ASSESSMENT — for every remaining VERIFIED or VERIFIED_INCOMPLETE section:\n"
            "    Read the section's legal text and the query. "
            "Ask: does this section's rule directly govern or materially inform the IRAC analysis?\n"
            "    Classify as:\n"
            "    - RELEVANT: Directly applies to the legal question (use as primary authority).\n"
            "    - TANGENTIAL: Related legal concept but not the operative rule for this query "
            "(keep, label as '(contextual reference only)').\n"
            "    - NOT_APPLICABLE: Retrieved due to keyword overlap only — does not bear on this "
            "query. Remove it, same as NOT_FOUND. Document the removal and reason.\n"
            "5. For non-BNS/BNSS/BSA citations (Companies Act, SEBI etc.): "
            "label them as 'UNVERIFIED (out-of-scope — not in database)' and retain them.\n"
            "6. For SC judgment citations — TWO-STEP EXACT MATCH:\n"
            "   Step 6a — MATERIALISE the retrieved list: Look at the PRECEDENT RESULTS "
            "section in the RetrievalSpecialist output (context above). "
            "Copy out each case name VERBATIM, one per line, like this:\n"
            "   RETRIEVED PRECEDENT CASES:\n"
            "   - [exact case name as returned by the tool]\n"
            "   - [exact case name as returned by the tool]\n"
            "   If there are no PRECEDENT RESULTS (or the label was absent), write: "
            "   RETRIEVED PRECEDENT CASES: NONE\n"
            "   Step 6b — EXACT MATCH: For every SC case name in the IRAC analysis, "
            "check if it appears — word-for-word — in your RETRIEVED PRECEDENT CASES list above. "
            "A 'match' requires the party names to match (allowing for minor punctuation, "
            "'v.' vs '&', upper/lower case). Different parties = NOT a match. "
            "Cases that DO match → label 'SC JUDGMENT — cited as precedent'. "
            "Cases that do NOT appear in RETRIEVED PRECEDENT CASES → flag as "
            "'HALLUCINATED — fabricated from model knowledge, not retrieved from database' "
            "and mark for removal. "
            "Do NOT call CitationVerificationTool for case citations.\n"
            "7. CONFIDENCE RULE: In your output, state the confidence level exactly as the "
            "LegalReasoner stated it (high/medium/low). Do NOT upgrade the confidence level. "
            "If LegalReasoner said 'Low', output 'Low'.\n"
            "8. If confidence drops below 0.5 after removing NOT_FOUND and NOT_APPLICABLE citations, "
            "recommend the user consult a qualified legal professional."
        ),
        expected_output=(
            "Verified IRAC analysis with each BNS/BNSS/BSA citation marked "
            "VERIFIED / VERIFIED_INCOMPLETE / removed (NOT_FOUND). "
            "Year-as-section numbers removed as hallucinated. "
            "RETRIEVED PRECEDENT CASES list written out verbatim. "
            "SC cases compared by exact name match — hallucinated cases flagged and removed. "
            "Non-BNS/BNSS/BSA laws labeled out-of-scope. "
            "Overall verification status and confidence score (unchanged from LegalReasoner)."
        ),
        agent=citation_checker,
        context=[retrieval_task, irac_task],
    )

    format_task = Task(
        description=(
            "Format the verified IRAC analysis for a lawyer.\n\n"
            "Query: {query}\nUser Role: lawyer\n\n"
            "CRITICAL FIRST CHECK: If the previous step's output contains "
            "'NO_RELEVANT_DOCUMENTS_FOUND' or UNVERIFIED with zero citations, "
            "output ONLY the standard cannot-verify message (see your backstory). "
            "Do NOT answer from your own knowledge.\n\n"
            "Otherwise, format requirements:\n"
            "- Present in full IRAC structure with clear headings\n"
            "- Use precise legal language — do not simplify\n"
            "- Include all applicable sections with act code, number, and title\n"
            "- Show verification status for each citation\n"
            "- CONFIDENCE RULE: Use the exact confidence level from the CitationChecker output. "
            "Do NOT upgrade it — if it says Low, write Low.\n"
            "- Note any limitations (sections not found, insufficient coverage)\n"
            "- STATUTORY CITATIONS RULE: In your Citations section, include EVERY BNS/BNSS/BSA "
            "section that the CitationChecker marked VERIFIED or VERIFIED_INCOMPLETE. "
            "The CitationChecker's output contains a verification table with rows like: "
            "| BNS Section 103 | BNS_2023 | 103 | VERIFIED | Retained |. "
            "Scan ALL rows in that table — include every row where Verification Result is "
            "'VERIFIED' or 'VERIFIED_INCOMPLETE'. Do NOT omit any such row. "
            "Do NOT add section numbers from your own knowledge.\n"
            "- YEAR-AS-SECTION GUARD: Never cite a section number that is a 4-digit year "
            "(2020–2026). These are not real section numbers — they are hallucinations. "
            "If the CitationChecker removed any such section, do NOT re-add it.\n"
            "- CASE CITATIONS ANTI-HALLUCINATION RULE: List ONLY SC cases that appear in the "
            "CitationChecker's output as 'SC JUDGMENT — cited as precedent'. "
            "Do NOT write any case name — including landmark cases like Bachan Singh, "
            "Machhi Singh, or any other — that was not explicitly retained by the CitationChecker. "
            "Inventing case names is the most dangerous error in a legal AI system. "
            "If no SC cases survived, write: 'No SC precedents available for this query.'\n"
            "- End with: 'Generated by Neethi AI | Verified citations only | "
            "Not a substitute for legal advice.'"
        ),
        expected_output=(
            "Structured legal analysis report in IRAC format with: precise Issue statement, "
            "Rule section with cited provisions, Application analysis, Conclusion with "
            "confidence level, verified citation list, and professional disclaimer."
        ),
        agent=response_formatter,
        context=[verify_task],
    )

    return Crew(
        agents=[query_analyst, retrieval_specialist, legal_reasoner, citation_checker, response_formatter],
        tasks=[classify_task, retrieval_task, irac_task, verify_task, format_task],
        process=Process.sequential,
        verbose=False,
        stream=stream,
    )


# ---------------------------------------------------------------------------
# Crew 3: Corporate Advisor Crew
# ---------------------------------------------------------------------------

def make_advisor_crew(stream: bool = False) -> Crew:
    """Crew for legal advisor / corporate compliance queries.

    Pipeline: QueryAnalyst → RetrievalSpecialist → LegalReasoner → CitationChecker → ResponseFormatter

    Same pipeline as lawyer but domain-focused on corporate, IT, and compliance laws.
    Output style: compliance-focused with risk assessment format.

    Args:
        stream: If True, enables token-level SSE streaming via crew.akickoff().
    """
    query_analyst = make_query_analyst()
    retrieval_specialist = make_retrieval_specialist()
    legal_reasoner = make_legal_reasoner()
    citation_checker = make_citation_checker()
    response_formatter = make_response_formatter()

    classify_task = Task(
        description=(
            "Classify this corporate/compliance legal query.\n\n"
            "Query: {query}\nUser Role: {user_role}\n\n"
            "Focus on: corporate law, IT Act, GST, SEBI regulations, data protection, "
            "employment law, contract law. "
            "Call QueryClassifierTool then StatuteNormalizationTool if old statutes present. "
            "IMPORTANT: include the 'Requires Precedents' field from the classification — "
            "the RetrievalSpecialist will use it to decide whether to also search SC judgments."
        ),
        expected_output=(
            "Classification with legal domain (should be corporate/IT/compliance), "
            "intent, entities, normalized statute references, and Requires Precedents (true/false)."
        ),
        agent=query_analyst,
    )

    retrieval_task = Task(
        description=(
            "Retrieve corporate and compliance legal material.\n\n"
            "Query: {query}\nUser Role: {user_role}\n\n"
            "1. Search legal_sections via QdrantHybridSearchTool (top_k=3, use filters).\n"
            "2. If 'Requires Precedents: true', search sc_judgments (top_k=3).\n"
            "3. Final Answer: Return ONLY tool output verbatim. Include BOTH sections."
        ),
        expected_output=(
            "STATUTORY RESULTS (up to 5 sections with full metadata) "
            "followed by PRECEDENT RESULTS (up to 3 SC judgments) when sc_judgments was searched — "
            "both sections required and labelled. "
            "OR the exact string 'NO_RELEVANT_DOCUMENTS_FOUND'."
        ),
        agent=retrieval_specialist,
        context=[classify_task],
    )

    irac_task = Task(
        description=(
            "Analyze compliance requirements and legal risks using IRAC.\n\n"
            "Query: {query}\nUser Role: legal_advisor\n\n"
            "Steps:\n"
            "1. Call IRACAnalyzerTool with the COMPLETE output from the RetrievalSpecialist "
            "as retrieved_sections — this MUST include BOTH the STATUTORY RESULTS and the "
            "PRECEDENT RESULTS sections, verbatim, as a single string. Do NOT truncate, "
            "summarize, or strip out the PRECEDENT RESULTS block. "
            "Also pass the original query as original_query.\n"
            "2. Focus the Application section on: compliance obligations, regulatory risk, "
            "penalty exposure, and recommended actions.\n"
            "3. SC CASE RULE: Only reference case names that appear in the PRECEDENT RESULTS "
            "from the RetrievalSpecialist. Do NOT add case names from your own knowledge.\n"
            "TOOL FAILURE RULE: If IRACAnalyzerTool returns 'IRAC ANALYSIS ERROR', do NOT write "
            "an IRAC analysis from your own knowledge. Return exactly: "
            "'IRAC TOOL FAILED: [paste the error message]' as your Final Answer."
        ),
        expected_output=(
            "IRAC analysis with compliance focus: Issue (compliance question), "
            "Rule (applicable regulations), Application (compliance requirements and risks), "
            "Conclusion (compliance status and recommendations), "
            "Applicable Sections, Applicable Precedents (SC cases or 'No SC precedents')."
        ),
        agent=legal_reasoner,
        context=[retrieval_task],
    )

    verify_task = Task(
        description=(
            "Verify all regulatory citations in the compliance analysis.\n\n"
            "Query: {query}\n\n"
            "Steps:\n"
            "0. YEAR-AS-SECTION GUARD (run first, before any tool call): "
            "Scan all cited section numbers in the IRAC analysis. "
            "If any section number is a 4-digit year (2020, 2021, 2022, 2023, 2024, 2025, 2026): "
            "flag it immediately as 'HALLUCINATED (year used as section number — not a real section)' "
            "and remove it WITHOUT calling CitationVerificationTool. "
            "BNS/BNSS/BSA section numbers are at most 3 digits. No 4-digit section exists.\n"
            "1. For each remaining cited section in the IRAC analysis: "
            "call CitationVerificationTool. "
            "IMPORTANT: pass act_code as 'BNS_2023', 'BNSS_2023', or 'BSA_2023' — "
            "never the short form 'BNS', 'BNSS', or 'BSA'. "
            "Do NOT call CitationVerificationTool for laws outside the database. "
            "Indexed acts: BNS_2023, BNSS_2023, BSA_2023, IPC_1860, CrPC_1973, IEA_1872, "
            "SRA_1963, TPA_1882, CPA_2019, CPC_1908, LA_1963. "
            "For anything else (Companies Act, SEBI, IT Act, GST) — label UNVERIFIED (out-of-scope).\n"
            "2. The tool returns one of three statuses:\n"
            "   - VERIFIED: section exists and data is complete. Keep and use normally.\n"
            "   - VERIFIED_INCOMPLETE: section exists but data is missing. "
            "Keep the citation but flag it '(incomplete data)' and do NOT use its "
            "procedural metadata in compliance conclusions.\n"
            "   - NOT_FOUND: section does not exist. Remove it entirely.\n"
            "3. Remove NOT_FOUND citations. "
            "Do NOT rename, renumber, or substitute a different section number — "
            "the section_number must be identical to the input.\n"
            "3b. RELEVANCE ASSESSMENT — for every remaining VERIFIED or VERIFIED_INCOMPLETE section:\n"
            "    Read the section's legal text and the compliance query. "
            "Ask: does this section directly impose an obligation, right, or penalty relevant "
            "to the compliance scenario being analysed?\n"
            "    Classify as:\n"
            "    - RELEVANT: Directly applies to the compliance obligation or risk in the query.\n"
            "    - TANGENTIAL: Related legal concept but not an operative rule for this compliance "
            "scenario (keep, label as '(contextual — not primary compliance authority)').\n"
            "    - NOT_APPLICABLE: Retrieved due to keyword overlap only — has no bearing on "
            "this compliance query. Remove it, same as NOT_FOUND.\n"
            "4. For non-BNS/BNSS/BSA citations: label them "
            "'UNVERIFIED (out-of-scope — not in database)' and retain them.\n"
            "5. For SC judgment citations — TWO-STEP EXACT MATCH:\n"
            "   Step 5a — MATERIALISE the retrieved list: Look at the PRECEDENT RESULTS "
            "section in the RetrievalSpecialist output (context above). "
            "Copy out each case name VERBATIM, one per line:\n"
            "   RETRIEVED PRECEDENT CASES:\n"
            "   - [exact case name as returned by the tool]\n"
            "   If there are no PRECEDENT RESULTS, write: "
            "   RETRIEVED PRECEDENT CASES: NONE\n"
            "   Step 5b — EXACT MATCH: For every SC case name in the IRAC, "
            "check if it appears — word-for-word — in your RETRIEVED PRECEDENT CASES list above. "
            "A 'match' requires the party names to match (allowing for minor punctuation, "
            "'v.' vs '&', upper/lower case). Different parties = NOT a match. "
            "Cases that DO match → label 'SC JUDGMENT — cited as precedent'. "
            "Cases that do NOT appear → flag as "
            "'HALLUCINATED — fabricated from model knowledge, not retrieved from database' "
            "and mark for removal. "
            "Do NOT call CitationVerificationTool for case citations.\n"
            "6. CONFIDENCE RULE: State the confidence level exactly as the LegalReasoner stated it. "
            "Do NOT upgrade it.\n"
            "Corporate advice with wrong citations is a serious risk."
        ),
        expected_output=(
            "Verified compliance analysis: BNS/BNSS/BSA sections marked "
            "VERIFIED / VERIFIED_INCOMPLETE / removed (NOT_FOUND). "
            "Year-as-section numbers removed as hallucinated. "
            "RETRIEVED PRECEDENT CASES list written out verbatim. "
            "SC cases compared by exact name match — hallucinated cases flagged and removed. "
            "Non-BNS/BNSS/BSA laws labeled out-of-scope. All changes noted."
        ),
        agent=citation_checker,
        context=[retrieval_task, irac_task],
    )

    format_task = Task(
        description=(
            "Format the verified compliance analysis as a professional advisory report.\n\n"
            "Query: {query}\nUser Role: legal_advisor\n\n"
            "CRITICAL FIRST CHECK: If the previous step contains 'NO_RELEVANT_DOCUMENTS_FOUND' "
            "or UNVERIFIED with zero citations, output ONLY the standard cannot-verify message "
            "(see your backstory). Do NOT answer from your own knowledge.\n\n"
            "Otherwise, format: Compliance Summary → Risk Assessment (High/Medium/Low) → "
            "Applicable Regulations → Required Actions → Verified Citations → Disclaimer.\n"
            "STATUTORY CITATIONS RULE: In your Applicable Regulations/Citations section, include "
            "EVERY BNS/BNSS/BSA section that the CitationChecker marked VERIFIED or VERIFIED_INCOMPLETE. "
            "The CitationChecker's output contains a verification table with rows like: "
            "| BNS Section 103 | BNS_2023 | 103 | VERIFIED | Retained |. "
            "Scan ALL rows in that table — include every row where Verification Result is "
            "'VERIFIED' or 'VERIFIED_INCOMPLETE'. Do NOT omit any such row. "
            "Do NOT add section numbers from your own knowledge.\n"
            "YEAR-AS-SECTION GUARD: Never cite a section number that is a 4-digit year "
            "(2020–2026). These are not real section numbers — they are hallucinations. "
            "If the CitationChecker removed any such section, do NOT re-add it.\n"
            "CASE CITATIONS ANTI-HALLUCINATION RULE: List ONLY SC cases retained by CitationChecker "
            "as 'SC JUDGMENT — cited as precedent'. Do NOT write any case name from your own "
            "knowledge. If no SC cases survived, write: 'No SC precedents available for this query.'"
        ),
        expected_output=(
            "Professional compliance advisory in report format with risk assessment, "
            "regulatory citations, action items, and disclaimer."
        ),
        agent=response_formatter,
        context=[verify_task],
    )

    return Crew(
        agents=[query_analyst, retrieval_specialist, legal_reasoner, citation_checker, response_formatter],
        tasks=[classify_task, retrieval_task, irac_task, verify_task, format_task],
        process=Process.sequential,
        verbose=False,
        stream=stream,
    )


# ---------------------------------------------------------------------------
# Crew 4: Police Crew
# ---------------------------------------------------------------------------

def make_police_crew(stream: bool = False) -> Crew:
    """Crew for police legal procedure queries.

    Pipeline: QueryAnalyst → RetrievalSpecialist → CitationChecker → ResponseFormatter

    No LegalReasoner — police need procedural steps and applicable sections,
    not IRAC analysis. Output focused on IPC/BNS, CrPC/BNSS criminal law.

    Args:
        stream: If True, enables token-level SSE streaming via crew.akickoff().
    """
    query_analyst = make_query_analyst()
    retrieval_specialist = make_retrieval_specialist()
    citation_checker = make_citation_checker()
    response_formatter = make_response_formatter()

    classify_task = Task(
        description=(
            "Classify this police procedural query.\n\n"
            "Query: {query}\nUser Role: {user_role}\n\n"
            "Focus on: criminal law (BNS/IPC), criminal procedure (BNSS/CrPC), "
            "FIR registration, arrest powers, bail, cognizable offences. "
            "Call QueryClassifierTool. If old IPC/CrPC references: call StatuteNormalizationTool. "
            "CRITICAL: IPC 302 → BNS 103 for murder. CrPC 438 → BNSS 482 for anticipatory bail."
        ),
        expected_output=(
            "Classification with criminal domain focus, statute normalizations, "
            "and recommended search parameters for criminal procedural law."
        ),
        agent=query_analyst,
    )

    retrieval_task = Task(
        description=(
            "Retrieve criminal law sections for the police query.\n\n"
            "Query: {query}\nUser Role: {user_role}\n\n"
            "Steps:\n"
            "1. Normalize old references via StatuteNormalizationTool if needed.\n"
            "2. Search legal_sections via QdrantHybridSearchTool (top_k=3, use filters).\n"
            "3. Final Answer: Return ONLY the tool output verbatim."
        ),
        expected_output=(
            "Either: up to 5 relevant criminal law sections with procedural metadata — "
            "OR the exact string 'NO_RELEVANT_DOCUMENTS_FOUND' (only when tool returned 0 results)."
        ),
        agent=retrieval_specialist,
        context=[classify_task],
    )

    verify_task = Task(
        description=(
            "Verify all criminal law citations AND assess whether each section actually "
            "applies to the police query.\n\n"
            "Query: {query}\n\n"
            "Steps:\n"
            "1. Call CitationVerificationTool for each section. "
            "IMPORTANT: pass act_code as 'BNS_2023', 'BNSS_2023', or 'BSA_2023' — "
            "never the short form 'BNS', 'BNSS', or 'BSA'.\n"
            "2. The tool returns one of three statuses:\n"
            "   - VERIFIED: section exists and data is complete. Keep and use.\n"
            "   - VERIFIED_INCOMPLETE: section exists but procedural metadata "
            "(is_cognizable, is_bailable, triable_by) may be missing. "
            "Keep the citation but flag '(incomplete data — do not rely on "
            "cognizable/bailable classification)'. "
            "Police MUST NOT act on unconfirmed procedural classification.\n"
            "   - NOT_FOUND: section does not exist. Remove it entirely.\n"
            "3. Do NOT rename, renumber, or substitute a different section number.\n"
            "4. RELEVANCE ASSESSMENT — run for every VERIFIED or VERIFIED_INCOMPLETE section:\n"
            "   Read the section's legal text and the police query. "
            "Ask: does this section describe the offence or procedure the officer is asking about?\n"
            "   Classify each section as:\n"
            "   - RELEVANT: Directly defines the offence, punishment, or procedure queried.\n"
            "   - TANGENTIAL: Related criminal law concept but not what was asked "
            "(keep, label as '(contextual — not the primary applicable section)').\n"
            "   - NOT_APPLICABLE: Only matched due to keyword overlap — remove it. "
            "Police acting on wrong offence sections is operationally dangerous.\n"
            "5. Output verified citations with RELEVANT / TANGENTIAL / removed status. "
            "Police need to know EXACTLY which section governs — do not leave ambiguous sections."
        ),
        expected_output=(
            "Criminal law citations classified as RELEVANT (primary applicable section), "
            "TANGENTIAL (contextual only), or removed (NOT_FOUND / NOT_APPLICABLE). "
            "VERIFIED_INCOMPLETE citations flagged with incomplete data warning. "
            "Only RELEVANT sections should be used for operational police decisions."
        ),
        agent=citation_checker,
        context=[retrieval_task],
    )

    format_task = Task(
        description=(
            "Format the verified legal information for police use.\n\n"
            "Query: {query}\nUser Role: police\n\n"
            "CRITICAL FIRST CHECK: If the previous step contains 'NO_RELEVANT_DOCUMENTS_FOUND' "
            "or UNVERIFIED with zero RELEVANT citations, output ONLY the standard cannot-verify "
            "message (see your backstory). Do NOT answer from your own knowledge.\n\n"
            "Otherwise, format requirements:\n"
            "- Lead with the RELEVANT section number and act name\n"
            "- State whether the offence is: Cognizable / Non-Cognizable\n"
            "- State whether: Bailable / Non-Bailable\n"
            "- State which court: Magistrate / Sessions / High Court\n"
            "- List procedural steps in numbered order\n"
            "- Include FIR guidance if applicable\n"
            "- STATUTORY CITATIONS RULE:\n"
            "  * List RELEVANT sections as primary operative law\n"
            "  * List TANGENTIAL sections under 'Related Provisions' only if genuinely useful\n"
            "  * Do NOT include sections the CitationChecker removed as NOT_APPLICABLE\n"
            "  * Do NOT add section numbers from your own knowledge\n"
            "  * Police acting on unverified or inapplicable section numbers is dangerous\n"
            "- Note: 'For offences after July 1 2024, cite BNS/BNSS — not IPC/CrPC'\n"
            "- Disclaimer at end."
        ),
        expected_output=(
            "Police-formatted response with: applicable sections, cognizable/bailable status, "
            "court jurisdiction, numbered procedural steps, FIR guidance, and citations."
        ),
        agent=response_formatter,
        context=[verify_task],
    )

    return Crew(
        agents=[query_analyst, retrieval_specialist, citation_checker, response_formatter],
        tasks=[classify_task, retrieval_task, verify_task, format_task],
        process=Process.sequential,
        verbose=False,
        stream=stream,
    )


# ---------------------------------------------------------------------------
# Crew router
# ---------------------------------------------------------------------------

_CREW_MAP = {
    "citizen": make_layman_crew,
    "lawyer": make_lawyer_crew,
    "legal_advisor": make_advisor_crew,
    "police": make_police_crew,
}


def get_crew_for_role(user_role: str, stream: bool = False) -> Crew:
    """Return the appropriate crew for the given user role.

    Args:
        user_role: One of 'citizen', 'lawyer', 'legal_advisor', 'police'.
        stream:    If True, enables SSE streaming on the returned crew.
                   Pass stream=True only for the /query/ask/stream endpoint.

    Returns:
        A freshly constructed Crew instance.

    Raises:
        ValueError: If user_role is not recognised.
    """
    factory = _CREW_MAP.get(user_role)
    if factory is None:
        raise ValueError(
            f"Unknown user_role: {user_role!r}. "
            f"Must be one of: {list(_CREW_MAP.keys())}"
        )
    logger.info("get_crew_for_role: building %s crew (stream=%s)", user_role, stream)
    return factory(stream=stream)


# ---------------------------------------------------------------------------
# Document Analysis Crew (stub — requires PageIndex)
# ---------------------------------------------------------------------------

def make_document_analysis_crew(stream: bool = False) -> Crew:
    """Create a crew for document analysis using PageIndex.

    Pipeline: DocumentAnalyst → CitationChecker

    Currently a stub — the DocumentAnalyst agent has no tools until
    PageIndex API key is configured.
    """
    from backend.agents.agents.document_analyst import make_document_analyst

    analyst = make_document_analyst()
    checker = make_citation_checker()

    analysis_task = Task(
        description=(
            "Analyze the uploaded legal document.\n"
            "Extract key provisions, obligations, rights, deadlines, and risk areas.\n"
            "Provide a structured summary with references to specific clauses.\n\n"
            "Document context: {query}"
        ),
        expected_output=(
            "Structured document analysis including:\n"
            "1. Document type and purpose\n"
            "2. Key provisions and clauses\n"
            "3. Obligations and rights of each party\n"
            "4. Important dates and deadlines\n"
            "5. Risk areas and potential issues\n"
            "6. References to applicable statutory provisions"
        ),
        agent=analyst,
    )

    verification_task = Task(
        description=(
            "Verify all statutory references and citations in the document analysis.\n"
            "Check that every section number and act reference is accurate.\n"
            "Flag any unverified claims."
        ),
        expected_output=(
            "Verified document analysis with:\n"
            "- Verification status for each cited provision\n"
            "- Corrected section references where needed\n"
            "- Overall confidence assessment"
        ),
        agent=checker,
    )

    return Crew(
        agents=[analyst, checker],
        tasks=[analysis_task, verification_task],
        process=Process.sequential,
        verbose=False,
    )
