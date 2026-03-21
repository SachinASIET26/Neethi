"""Skill-enhanced legal document drafting prompts.

Reads document-type-specific reference files and builds structured prompts
that replace the generic _template_prompt() in documents.py. The reference
files encode jurisdiction rules, mandatory fields, document structure, and
LLM guidance for each of the five supported templates.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Optional

_REFERENCES_DIR = Path(__file__).resolve().parent.parent.parent / "document_drafting" / "references"

# Mapping from template_id -> reference filename
_REFERENCE_FILES: dict[str, str] = {
    "fir_complaint": "fir_draft.md",
    "bail_application": "bail_application.md",
    "legal_notice": "legal_notice.md",
    "rti_application": "rti_application.md",
    "consumer_complaint": "consumer_complaint.md",
}

# Templates that have skill-enhanced prompts
SKILL_TEMPLATE_IDS = set(_REFERENCE_FILES.keys())


def _read_reference(template_id: str) -> Optional[str]:
    """Read and return reference file content for a template."""
    filename = _REFERENCE_FILES.get(template_id)
    if not filename:
        return None
    path = _REFERENCES_DIR / filename
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def _read_jurisdiction_rules() -> str:
    """Read the supplementary jurisdiction rules reference."""
    path = _REFERENCES_DIR / "jurisdiction_rules.md"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _determine_law_regime(fields: dict[str, str]) -> str:
    """Determine whether BNS/BNSS or IPC/CrPC applies based on incident date."""
    incident_date_str = fields.get("incident_date", "")
    if not incident_date_str:
        return (
            "The incident date has not been provided. If the incident occurred on or "
            "after 1st July 2024, cite BNS/BNSS/BSA sections. If before, cite IPC/CrPC/IEA."
        )

    try:
        # Try common date formats
        for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d %B %Y", "%B %d, %Y"):
            try:
                dt = datetime.strptime(incident_date_str.strip(), fmt)
                break
            except ValueError:
                continue
        else:
            return (
                f"Incident date '{incident_date_str}' — verify whether this is before or "
                "after 1st July 2024 to determine IPC vs BNS applicability."
            )

        cutoff = datetime(2024, 7, 1)
        if dt >= cutoff:
            return (
                f"Incident date is {incident_date_str} (on or after 1st July 2024). "
                "USE BNS/BNSS/BSA sections ONLY. Do NOT cite IPC, CrPC, or IEA."
            )
        else:
            return (
                f"Incident date is {incident_date_str} (before 1st July 2024). "
                "USE IPC/CrPC/IEA sections. Do NOT cite BNS, BNSS, or BSA."
            )
    except Exception:
        return (
            f"Incident date '{incident_date_str}' — verify whether this is before or "
            "after 1st July 2024 to determine IPC vs BNS applicability."
        )


def _determine_consumer_tier(fields: dict[str, str]) -> str:
    """Determine the consumer commission tier from claim amount."""
    amount_str = fields.get("total_claim_amount", "") or fields.get("amount_paid", "")
    if not amount_str:
        return "Claim amount not specified — ask the user to determine correct commission tier."

    # Extract numeric value (handle Rs., commas, lakhs, crores)
    cleaned = amount_str.replace(",", "").replace("Rs.", "").replace("Rs", "").replace("₹", "").strip()
    try:
        amount = float(cleaned)
    except ValueError:
        return f"Claim amount '{amount_str}' — determine correct commission tier based on value."

    if amount <= 5_000_000:  # 50 lakhs
        return (
            f"Claim amount Rs. {amount_str} is within Rs. 50 lakhs. "
            "File before the DISTRICT Consumer Disputes Redressal Commission."
        )
    elif amount <= 20_000_000:  # 2 crores
        return (
            f"Claim amount Rs. {amount_str} is between Rs. 50 lakhs and Rs. 2 crores. "
            "File before the STATE Consumer Disputes Redressal Commission."
        )
    else:
        return (
            f"Claim amount Rs. {amount_str} exceeds Rs. 2 crores. "
            "File before the NATIONAL Consumer Disputes Redressal Commission, New Delhi."
        )


def _build_fir_prompt(fields: dict[str, str], jurisdiction: str, reference: str) -> str:
    law_regime = _determine_law_regime(fields)
    fields_str = "\n".join(f"  {k}: {v}" for k, v in fields.items())

    return f"""You are a senior Indian advocate drafting a Written Complaint to be filed at a police station for conversion into an FIR.

## LAW REGIME DETERMINATION
{law_regime}

## USER-PROVIDED INFORMATION
{fields_str}

## JURISDICTION
{jurisdiction if jurisdiction else "Not specified — use central law defaults."}

## INSTRUCTIONS
Read the reference material below carefully. Follow the EXACT document structure specified in it.

Key rules:
- Write the factual narrative in FIRST PERSON, PAST TENSE. No legal conclusions in the facts section.
- Include all user-provided facts VERBATIM — do not paraphrase names, dates, or addresses.
- For section 5 (Offences Committed), use the correct law (BNS or IPC) based on the law regime above.
- ALWAYS include the right to a free FIR copy under BNSS Section 173(2) in the relief section.
- If any required information is missing, use [TO BE FILLED: description] placeholders.
- Do NOT cite BNS 302 for murder — BNS 302 is "uttering words wounding religious feelings." Murder is BNS 103.
- End with the DRAFT ONLY disclaimer.
- Output ONLY the document text, no commentary.

## REFERENCE MATERIAL
{reference}"""


def _build_bail_prompt(fields: dict[str, str], jurisdiction: str, reference: str) -> str:
    fields_str = "\n".join(f"  {k}: {v}" for k, v in fields.items())

    return f"""You are a senior Indian criminal defence advocate drafting a Bail Application under BNSS Section 480 (regular bail, post-arrest).

## CRITICAL SECTION NUMBER WARNINGS
- BNSS 438 ≠ CrPC 438. BNSS 438 is about Revision Powers. Do NOT use BNSS 438 for anticipatory bail.
- CrPC 438 (Anticipatory Bail) maps to BNSS 482.
- CrPC 439 (Special bail powers) maps to BNSS 483.
- This application is under BNSS 480 (regular bail). Verify you are citing the correct section.

## USER-PROVIDED INFORMATION
{fields_str}

## JURISDICTION
{jurisdiction if jurisdiction else "Not specified — determine correct court from offence sections."}

## COURT DETERMINATION
- If the offence is triable by "Any Magistrate" → address to Chief Judicial Magistrate or Judicial Magistrate First Class
- If triable by "Magistrate First Class" → address to Chief Judicial Magistrate
- If triable by "Court of Sessions" → address to Sessions Judge or Additional Sessions Judge
- BNS 303 (theft) is triable by Any Magistrate — do NOT address to Sessions Court

## INSTRUCTIONS
Read the reference material below carefully. Follow the EXACT document structure specified in it.

Key rules:
- For bailable offences, state explicitly that bail is a RIGHT under BNSS Section 478.
- Each ground for bail must be specific to the accused's circumstances — no generic statements.
- Do NOT fabricate family details, employment, or property if not provided. Use [TO BE FILLED] placeholders.
- Include previous bail application history. If none, state "No previous bail application has been filed."
- Calculate custody duration from date of arrest to today.
- End with the DRAFT ONLY disclaimer.
- Output ONLY the document text, no commentary.

## REFERENCE MATERIAL
{reference}"""


def _build_legal_notice_prompt(fields: dict[str, str], jurisdiction: str, reference: str) -> str:
    fields_str = "\n".join(f"  {k}: {v}" for k, v in fields.items())

    # Determine Type A (government) or Type B (private)
    receiver = (fields.get("receiver_name", "") + " " + fields.get("subject", "")).lower()
    govt_keywords = ["government", "ministry", "department", "corporation", "municipality",
                     "panchayat", "collector", "commissioner", "authority", "board"]
    is_government = any(kw in receiver for kw in govt_keywords)

    notice_type = (
        "Type A — Government notice under CPC Section 80. The 2-month mandatory waiting "
        "period before filing suit MUST be mentioned."
        if is_government else
        "Type B — Private party legal notice. No mandatory statutory waiting period, "
        "but a reasonable notice period (15-30 days) should be given."
    )

    # Kerala tenancy check
    kerala_tenancy_note = ""
    subject = fields.get("subject", "").lower() + " " + fields.get("demand", "").lower()
    if any(kw in subject for kw in ["tenant", "landlord", "rent", "evict", "lease", "security deposit"]):
        if jurisdiction and "kerala" in jurisdiction.lower():
            kerala_tenancy_note = (
                "\n## KERALA TENANCY LAW WARNING\n"
                "This appears to be a tenancy dispute in Kerala. The Kerala Buildings "
                "(Lease and Rent Control) Act 1965 (KBLRC Act) applies — NOT the Transfer "
                "of Property Act. The notice must comply with KBLRC Act provisions. "
                "Flag this prominently in the document."
            )

    return f"""You are a senior Indian advocate drafting a Legal Notice.

## NOTICE TYPE
{notice_type}

## USER-PROVIDED INFORMATION
{fields_str}

## JURISDICTION
{jurisdiction if jurisdiction else "Not specified — use central law defaults."}
{kerala_tenancy_note}

## INSTRUCTIONS
Read the reference material below carefully. Follow the EXACT document structure specified in it.

Key rules:
- Use formal legal English. Each grievance gets a separate numbered paragraph.
- State amounts in figures (Rs. 1,50,000), dates in full (1st January 2025), parties by full name.
- Do NOT use threatening or abusive language — firm but professional.
- Include all user-provided facts VERBATIM.
- For NI Act 138 (bounced cheque) matters, include cheque details, bank name, dishonour date.
- If sent through advocate, use advocate letterhead format. If personal, use "Notice from the desk of" format.
- End with the DRAFT ONLY disclaimer.
- Output ONLY the document text, no commentary.

## REFERENCE MATERIAL
{reference}"""


def _build_rti_prompt(fields: dict[str, str], jurisdiction: str, reference: str) -> str:
    fields_str = "\n".join(f"  {k}: {v}" for k, v in fields.items())

    # Determine central vs state
    target = (fields.get("target_department", "") + " " + (jurisdiction or "")).lower()
    kerala_keywords = ["kerala", "thrissur", "ernakulam", "kochi", "thiruvananthapuram",
                       "kozhikode", "kannur", "kollam", "alappuzha", "kottayam",
                       "palakkad", "malappuram", "wayanad", "idukki", "pathanamthitta",
                       "kasaragod", "kseb", "ksrtc", "kerala water", "panchayat",
                       "municipality", "corporation"]
    is_kerala = any(kw in target for kw in kerala_keywords)

    rti_type = (
        "KERALA STATE RTI — Fee: Rs. 10 by court fee stamp. Portal: crd.kerala.gov.in. "
        "First appeal to departmental Appellate Authority. Second appeal to Kerala State "
        "Information Commission (KSIC), Thiruvananthapuram. Do NOT use rtionline.gov.in."
        if is_kerala else
        "CENTRAL GOVERNMENT RTI — Fee: Rs. 10 by IPO, DD, or online. Portal: rtionline.gov.in. "
        "First appeal within same department. Second appeal to Central Information Commission (CIC)."
    )

    return f"""You are drafting an RTI (Right to Information) Application under the RTI Act 2005.

## RTI TYPE
{rti_type}

## USER-PROVIDED INFORMATION
{fields_str}

## JURISDICTION
{jurisdiction if jurisdiction else "Not specified — determine from target department."}

## INSTRUCTIONS
Read the reference material below carefully. Follow the EXACT document structure specified in it.

Key rules:
- Address to the Public Information Officer (PIO) of the specific department — NOT a Minister or elected official.
- Transform vague requests into SPECIFIC, actionable information requests.
- Each item of information sought should be a separately numbered paragraph.
- Use government record-keeping language: "certified copy", "file noting", "order sheet".
- Include the correct fee amount and payment method for the jurisdiction type.
- Mention the 30-day response timeline (or 48 hours if life/liberty is involved).
- Include information about the first appeal process.
- Do NOT ask questions ("Why did you...?") — request RECORDS ("A copy of the order dated...").
- End with the DRAFT ONLY disclaimer.
- Output ONLY the document text, no commentary.

## REFERENCE MATERIAL
{reference}"""


def _build_consumer_complaint_prompt(fields: dict[str, str], jurisdiction: str, reference: str) -> str:
    fields_str = "\n".join(f"  {k}: {v}" for k, v in fields.items())
    tier_determination = _determine_consumer_tier(fields)

    return f"""You are a senior Indian consumer rights advocate drafting a Consumer Complaint under the Consumer Protection Act, 2019.

## COMMISSION TIER
{tier_determination}

## USER-PROVIDED INFORMATION
{fields_str}

## JURISDICTION
{jurisdiction if jurisdiction else "Not specified — determine from complainant's district."}

## INSTRUCTIONS
Read the reference material below carefully. Follow the EXACT Form 1 document structure specified in it.

Key rules:
- Identify ALL opposite parties — both the seller AND the manufacturer/brand if applicable.
- Write facts in numbered paragraphs, one fact per paragraph, chronological order.
- Include any complaint reference numbers from the company VERBATIM.
- Be specific: dates, amounts, model numbers, order IDs.
- Avoid emotional characterisation — "the product did not match specifications" not "they cheated me."
- Include the VERIFICATION clause at the end — it is mandatory.
- The complaint can be filed where the complainant resides — this is the complainant's choice.
- Mention the 2-year limitation period for consumer complaints.
- For claims above Rs. 5 lakhs, note that online filing is mandatory.
- End with the DRAFT ONLY disclaimer.
- Output ONLY the document text, no commentary.

## REFERENCE MATERIAL
{reference}"""


# Dispatch table
_PROMPT_BUILDERS = {
    "fir_complaint": _build_fir_prompt,
    "bail_application": _build_bail_prompt,
    "legal_notice": _build_legal_notice_prompt,
    "rti_application": _build_rti_prompt,
    "consumer_complaint": _build_consumer_complaint_prompt,
}


def get_skill_prompt(
    template_id: str,
    fields: dict[str, str],
    jurisdiction: str = "",
) -> Optional[str]:
    """Build a skill-enhanced prompt for the given template.

    Returns None if no skill-enhanced prompt is available for this template_id,
    in which case the caller should fall back to the generic _template_prompt().
    """
    builder = _PROMPT_BUILDERS.get(template_id)
    if not builder:
        return None

    reference = _read_reference(template_id)
    if not reference:
        return None

    # Append jurisdiction rules as supplement if jurisdiction involves Kerala
    if jurisdiction and "kerala" in jurisdiction.lower():
        jurisdiction_rules = _read_jurisdiction_rules()
        if jurisdiction_rules:
            reference += "\n\n## SUPPLEMENTARY: JURISDICTION RULES\n" + jurisdiction_rules

    return builder(fields, jurisdiction, reference)
