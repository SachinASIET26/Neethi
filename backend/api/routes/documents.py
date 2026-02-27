"""Document drafting routes — templates, draft, PDF export."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.dependencies import get_current_user
from backend.api.schemas.documents import (
    DraftRequest,
    DraftResponse,
    DraftUpdateRequest,
    TemplateInfo,
    TemplateListResponse,
)
from backend.db.database import get_db
from backend.db.models.user import Draft, User

router = APIRouter()

# ---------------------------------------------------------------------------
# Hardcoded template catalogue
# ---------------------------------------------------------------------------

_TEMPLATES: list[TemplateInfo] = [
    TemplateInfo(
        template_id="bail_application",
        template_name="Bail Application",
        description="Application for regular bail under BNSS Section 480",
        required_fields=["accused_name", "fir_number", "police_station", "offence_sections", "grounds"],
        optional_fields=["surety_details", "previous_bail_history", "court_name"],
        jurisdiction="all",
        language="en",
        access_roles=["lawyer", "legal_advisor"],
    ),
    TemplateInfo(
        template_id="anticipatory_bail",
        template_name="Anticipatory Bail Application",
        description="Application under BNSS Section 482 (anticipatory bail)",
        required_fields=["accused_name", "police_station", "anticipated_offence_sections", "grounds_for_anticipation"],
        optional_fields=["fir_number", "supporting_case_law", "court_name"],
        jurisdiction="all",
        language="en",
        access_roles=["lawyer", "legal_advisor"],
    ),
    TemplateInfo(
        template_id="legal_notice",
        template_name="Legal Notice",
        description="Formal legal notice for demand or grievance",
        required_fields=["sender_name", "receiver_name", "sender_address", "receiver_address", "subject", "demand", "notice_period_days"],
        optional_fields=["lawyer_name", "bar_council_id", "reference_number"],
        jurisdiction="all",
        language="en",
        access_roles=["citizen", "lawyer", "legal_advisor"],
    ),
    TemplateInfo(
        template_id="fir_complaint",
        template_name="FIR Draft / Written Complaint",
        description="Draft complaint to be converted to FIR at police station",
        required_fields=["complainant_name", "complainant_address", "incident_date", "incident_location", "accused_details", "incident_description"],
        optional_fields=["witnesses", "evidence_list", "police_station"],
        jurisdiction="all",
        language="en",
        access_roles=["citizen", "lawyer", "police"],
    ),
    TemplateInfo(
        template_id="power_of_attorney",
        template_name="Power of Attorney",
        description="General or Special Power of Attorney",
        required_fields=["principal_name", "principal_address", "agent_name", "agent_address", "powers_granted", "effective_date"],
        optional_fields=["expiry_date", "limitations", "notary_details"],
        jurisdiction="all",
        language="en",
        access_roles=["citizen", "lawyer", "legal_advisor"],
    ),
    TemplateInfo(
        template_id="vakalatnama",
        template_name="Vakalatnama",
        description="Authority to act — lawyer's power of attorney from client",
        required_fields=["client_name", "client_address", "lawyer_name", "bar_council_id", "case_details"],
        optional_fields=["court_name", "case_number"],
        jurisdiction="all",
        language="en",
        access_roles=["lawyer"],
    ),
    TemplateInfo(
        template_id="affidavit",
        template_name="General Affidavit",
        description="Sworn statement / affidavit for general use",
        required_fields=["deponent_name", "deponent_address", "deponent_age", "statement"],
        optional_fields=["purpose", "notary_details"],
        jurisdiction="all",
        language="en",
        access_roles=["citizen", "lawyer", "legal_advisor", "police"],
    ),
]

_TEMPLATE_MAP = {t.template_id: t for t in _TEMPLATES}


def _template_prompt(template: TemplateInfo, fields: dict, include_citations: bool) -> str:
    fields_str = "\n".join(f"  {k}: {v}" for k, v in fields.items())
    citation_instruction = (
        "Include verified BNS/BNSS/BSA section references where appropriate. "
        if include_citations else ""
    )
    return (
        f"You are a senior Indian advocate drafting a {template.template_name}.\n\n"
        f"Draft the complete document using the following information:\n{fields_str}\n\n"
        f"Requirements:\n"
        f"- Use standard Indian legal formatting and language\n"
        f"- Include all standard clauses and recitals for this document type\n"
        f"{citation_instruction}"
        f"- End with a DRAFT disclaimer\n"
        f"- Output only the document text, no commentary"
    )


# ---------------------------------------------------------------------------
# GET /documents/templates
# ---------------------------------------------------------------------------

@router.get("/templates", response_model=TemplateListResponse)
async def list_templates(current_user: User = Depends(get_current_user)):
    """List all available document templates accessible to the current user."""
    accessible = [
        t for t in _TEMPLATES if current_user.role in t.access_roles or current_user.role == "admin"
    ]
    return TemplateListResponse(templates=accessible)


# ---------------------------------------------------------------------------
# POST /documents/draft
# ---------------------------------------------------------------------------

@router.post("/draft", response_model=DraftResponse, status_code=201)
async def create_draft(
    request: DraftRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate a document draft from a template and user-provided fields."""
    template = _TEMPLATE_MAP.get(request.template_id)
    if not template:
        raise HTTPException(404, detail=f"Template '{request.template_id}' not found.")

    if current_user.role not in template.access_roles and current_user.role != "admin":
        raise HTTPException(
            403,
            detail=f"Template '{request.template_id}' is not available for role '{current_user.role}'.",
        )

    # Validate required fields
    missing = [f for f in template.required_fields if f not in request.fields]
    if missing:
        raise HTTPException(
            422,
            detail=[{"field": f, "error": f"Required field missing for template '{request.template_id}'"} for f in missing],
        )

    # Generate draft via LLM (Mistral Large preferred; DeepSeek Chat as fallback)
    try:
        import os

        import litellm

        mistral_key = os.getenv("MISTRAL_API_KEY", "").strip()
        deepseek_key = os.getenv("DEEPSEEK_API_KEY", "").strip()

        if mistral_key:
            model, api_key = "mistral/mistral-large-latest", mistral_key
        elif deepseek_key:
            model, api_key = "deepseek/deepseek-chat", deepseek_key
        else:
            raise HTTPException(
                503,
                detail="No LLM API key configured. Set MISTRAL_API_KEY or DEEPSEEK_API_KEY in .env.",
            )

        prompt = _template_prompt(template, request.fields, request.include_citations)
        resp = await litellm.acompletion(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=4096,
            api_key=api_key,
        )
        draft_text: str = resp.choices[0].message.content or ""
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, detail=f"Draft generation failed: {exc}") from exc

    # Append disclaimer
    disclaimer = (
        "\n\n---\nDRAFT ONLY — NOT LEGAL ADVICE. "
        "This document requires review by a qualified lawyer before filing or use."
    )
    draft_text = draft_text.rstrip() + disclaimer

    title = f"{template.template_name} — {request.fields.get('accused_name') or request.fields.get('sender_name') or request.fields.get('client_name') or 'Draft'}"
    word_count = len(draft_text.split())

    draft = Draft(
        user_id=current_user.id,
        template_id=request.template_id,
        title=title,
        draft_text=draft_text,
        fields_used=request.fields,
        verification_status="UNVERIFIED",
        language=request.language,
        word_count=word_count,
    )
    db.add(draft)
    await db.commit()
    await db.refresh(draft)

    return DraftResponse(
        draft_id=str(draft.id),
        template_id=draft.template_id,
        title=draft.title,
        draft_text=draft.draft_text,
        verification_status=draft.verification_status or "UNVERIFIED",
        created_at=draft.created_at,
        word_count=draft.word_count,
    )


# ---------------------------------------------------------------------------
# GET /documents/draft/{draft_id}
# ---------------------------------------------------------------------------

@router.get("/draft/{draft_id}", response_model=DraftResponse)
async def get_draft(
    draft_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve a previously generated draft."""
    result = await db.execute(
        select(Draft).where(
            Draft.id == draft_id,
            Draft.user_id == current_user.id,
        )
    )
    draft = result.scalar_one_or_none()
    if not draft:
        raise HTTPException(404, detail="Draft not found.")

    return DraftResponse(
        draft_id=str(draft.id),
        template_id=draft.template_id,
        title=draft.title,
        draft_text=draft.draft_text,
        verification_status=draft.verification_status or "UNVERIFIED",
        created_at=draft.created_at,
        word_count=draft.word_count,
    )


# ---------------------------------------------------------------------------
# PUT /documents/draft/{draft_id}
# ---------------------------------------------------------------------------

@router.put("/draft/{draft_id}", response_model=DraftResponse)
async def update_draft(
    draft_id: str,
    request: DraftUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a draft by providing new/changed field values and regenerating."""
    result = await db.execute(
        select(Draft).where(Draft.id == draft_id, Draft.user_id == current_user.id)
    )
    draft = result.scalar_one_or_none()
    if not draft:
        raise HTTPException(404, detail="Draft not found.")

    template = _TEMPLATE_MAP.get(draft.template_id)
    if not template:
        raise HTTPException(404, detail="Template no longer available.")

    # Merge new fields over existing
    merged_fields = {**(draft.fields_used or {}), **request.fields}

    # Regenerate
    try:
        import litellm
        from backend.config.llm_config import _CLAUDE_SONNET, _MISTRAL_LARGE, _mistral_fallback_active
        import os

        model = _MISTRAL_LARGE if _mistral_fallback_active else _CLAUDE_SONNET
        api_key = os.getenv("ANTHROPIC_API_KEY") if not _mistral_fallback_active else os.getenv("MISTRAL_API_KEY")

        prompt = _template_prompt(template, merged_fields, True)
        resp = await litellm.acompletion(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=4096,
            api_key=api_key,
        )
        new_text: str = resp.choices[0].message.content or ""
    except Exception as exc:
        raise HTTPException(500, detail=f"Draft regeneration failed: {exc}") from exc

    disclaimer = (
        "\n\n---\nDRAFT ONLY — NOT LEGAL ADVICE. "
        "This document requires review by a qualified lawyer before filing or use."
    )
    new_text = new_text.rstrip() + disclaimer

    draft.draft_text = new_text
    draft.fields_used = merged_fields
    draft.word_count = len(new_text.split())
    await db.commit()
    await db.refresh(draft)

    return DraftResponse(
        draft_id=str(draft.id),
        template_id=draft.template_id,
        title=draft.title,
        draft_text=draft.draft_text,
        verification_status=draft.verification_status or "UNVERIFIED",
        created_at=draft.created_at,
        word_count=draft.word_count,
    )


# ---------------------------------------------------------------------------
# POST /documents/draft/{draft_id}/pdf
# ---------------------------------------------------------------------------

@router.post("/draft/{draft_id}/pdf")
async def export_pdf(
    draft_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Export a draft as a formatted PDF file."""
    result = await db.execute(
        select(Draft).where(Draft.id == draft_id, Draft.user_id == current_user.id)
    )
    draft = result.scalar_one_or_none()
    if not draft:
        raise HTTPException(404, detail="Draft not found.")

    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
        from reportlab.lib.enums import TA_CENTER, TA_LEFT
        import io

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            rightMargin=2.5 * cm,
            leftMargin=2.5 * cm,
            topMargin=2.5 * cm,
            bottomMargin=2.5 * cm,
        )
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            "title", parent=styles["Heading1"], alignment=TA_CENTER, fontSize=14
        )
        watermark_style = ParagraphStyle(
            "watermark", parent=styles["Normal"], alignment=TA_CENTER,
            fontSize=10, textColor="grey"
        )
        body_style = ParagraphStyle(
            "body", parent=styles["Normal"], fontSize=10, leading=16
        )

        story = [
            Paragraph("DRAFT — NOT FOR OFFICIAL USE", watermark_style),
            Spacer(1, 0.5 * cm),
            Paragraph(draft.title, title_style),
            Spacer(1, 0.5 * cm),
        ]
        for line in draft.draft_text.split("\n"):
            line = line.strip()
            if line:
                story.append(Paragraph(line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"), body_style))
                story.append(Spacer(1, 0.2 * cm))

        doc.build(story)
        pdf_bytes = buffer.getvalue()

    except ImportError:
        # reportlab not installed — return plain text as fallback
        safe_name = "".join(c if ord(c) < 128 else "_" for c in draft.title.replace(" ", "_"))[:50].strip("_") or "draft"
        return Response(
            content=draft.draft_text.encode("utf-8"),
            media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{safe_name}.txt"'},
        )

    # Strip non-ASCII chars — HTTP headers use latin-1 encoding; em dash etc. crash starlette
    safe_name = "".join(c if ord(c) < 128 else "_" for c in draft.title.replace(" ", "_"))[:50].strip("_") or "draft"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}.pdf"'},
    )


# ---------------------------------------------------------------------------
# DELETE /documents/draft/{draft_id}
# ---------------------------------------------------------------------------

@router.delete("/draft/{draft_id}", status_code=204)
async def delete_draft(
    draft_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a draft."""
    result = await db.execute(
        select(Draft).where(Draft.id == draft_id, Draft.user_id == current_user.id)
    )
    draft = result.scalar_one_or_none()
    if not draft:
        raise HTTPException(404, detail="Draft not found.")
    await db.delete(draft)
    await db.commit()
    return None
