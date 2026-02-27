"""Sections & Acts routes — direct statutory lookup (no LLM, no agent)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.dependencies import get_current_user
from backend.api.schemas.sections import (
    ActInfo,
    ActListResponse,
    NormalizeResponse,
    SectionDetail,
    SectionListResponse,
    SectionSummary,
    VerifyRequest,
    VerifyResponse,
    VerifyResult,
)
from backend.db.database import get_db
from backend.db.models.legal_foundation import Act, Section
from backend.db.models.user import User

router = APIRouter()

# ---------------------------------------------------------------------------
# Known act metadata (supplement what's in the DB)
# ---------------------------------------------------------------------------

_ACT_META: dict[str, dict] = {
    "BNS_2023":  {"short_name": "BNS",  "era": "naveen_sanhitas",  "effective_from": "2024-07-01", "replaces": ["IPC_1860"]},
    "BNSS_2023": {"short_name": "BNSS", "era": "naveen_sanhitas",  "effective_from": "2024-07-01", "replaces": ["CrPC_1973"]},
    "BSA_2023":  {"short_name": "BSA",  "era": "naveen_sanhitas",  "effective_from": "2024-07-01", "replaces": ["IEA_1872"]},
    "IPC_1860":  {"short_name": "IPC",  "era": "colonial_codes",   "effective_from": "1860-01-01", "superseded_by": ["BNS_2023"],  "superseded_on": "2024-07-01"},
    "CrPC_1973": {"short_name": "CrPC", "era": "colonial_codes",   "effective_from": "1973-04-01", "superseded_by": ["BNSS_2023"], "superseded_on": "2024-07-01"},
    "IEA_1872":  {"short_name": "IEA",  "era": "colonial_codes",   "effective_from": "1872-09-01", "superseded_by": ["BSA_2023"],  "superseded_on": "2024-07-01"},
}


# ---------------------------------------------------------------------------
# GET /sections/acts
# ---------------------------------------------------------------------------

@router.get("/acts", response_model=ActListResponse)
async def list_acts(
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all indexed acts with section counts."""
    result = await db.execute(select(Act).order_by(Act.year.desc()))
    acts = result.scalars().all()

    # Count indexed sections per act
    from sqlalchemy import func
    count_result = await db.execute(
        select(Section.act_code, func.count(Section.id).label("cnt"))
        .where(Section.qdrant_indexed == True)
        .group_by(Section.act_code)
    )
    indexed_counts = {row.act_code: row.cnt for row in count_result}

    total_result = await db.execute(
        select(Section.act_code, func.count(Section.id).label("cnt"))
        .group_by(Section.act_code)
    )
    total_counts = {row.act_code: row.cnt for row in total_result}

    act_list = []
    for act in acts:
        meta = _ACT_META.get(act.act_code, {})
        act_list.append(
            ActInfo(
                act_code=act.act_code,
                act_name=act.act_name,
                short_name=meta.get("short_name", act.short_name),
                era=meta.get("era"),
                effective_from=meta.get("effective_from"),
                superseded_by=meta.get("superseded_by"),
                superseded_on=meta.get("superseded_on"),
                replaces=meta.get("replaces"),
                total_sections=total_counts.get(act.act_code, 0),
                indexed_sections=indexed_counts.get(act.act_code, 0),
            )
        )

    return ActListResponse(acts=act_list)


# ---------------------------------------------------------------------------
# GET /sections/acts/{act_code}/sections
# ---------------------------------------------------------------------------

@router.get("/acts/{act_code}/sections", response_model=SectionListResponse)
async def list_sections(
    act_code: str,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    chapter: str | None = Query(None),
    is_offence: bool | None = Query(None),
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List sections of a specific act (paginated)."""
    from sqlalchemy import func

    query = select(Section).where(Section.act_code == act_code.upper())
    if chapter:
        from backend.db.models.legal_foundation import Chapter
        chap_result = await db.execute(
            select(Chapter.id).where(
                Chapter.act_code == act_code.upper(),
                Chapter.chapter_number == chapter,
            )
        )
        chap_id = chap_result.scalar_one_or_none()
        if chap_id:
            query = query.where(Section.chapter_id == chap_id)
    if is_offence is not None:
        query = query.where(Section.is_offence == is_offence)

    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar_one()

    result = await db.execute(
        query.order_by(Section.section_number_int.nullslast(), Section.section_number)
        .limit(limit)
        .offset(offset)
    )
    sections = result.scalars().all()

    return SectionListResponse(
        act_code=act_code.upper(),
        total_sections=total,
        sections=[
            SectionSummary(
                section_number=s.section_number,
                section_title=s.section_title,
                is_offence=s.is_offence,
                is_cognizable=s.is_cognizable,
                is_bailable=s.is_bailable,
                triable_by=s.triable_by,
            )
            for s in sections
        ],
    )


# ---------------------------------------------------------------------------
# GET /sections/acts/{act_code}/sections/{section_number}
# ---------------------------------------------------------------------------

@router.get("/acts/{act_code}/sections/{section_number}", response_model=SectionDetail)
async def get_section(
    act_code: str,
    section_number: str,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the full text and metadata of a specific section."""
    result = await db.execute(
        select(Section).where(
            Section.act_code == act_code.upper(),
            Section.section_number == section_number,
        )
    )
    section = result.scalar_one_or_none()
    if not section:
        raise HTTPException(
            404,
            detail=f"Section {act_code.upper()}/{section_number} not found in database.",
        )

    # Get act name
    act_result = await db.execute(
        select(Act.act_name).where(Act.act_code == act_code.upper())
    )
    act_name = act_result.scalar_one_or_none() or act_code

    # Get chapter title
    chapter_title = None
    if section.chapter_id:
        from backend.db.models.legal_foundation import Chapter
        ch_result = await db.execute(
            select(Chapter).where(Chapter.id == section.chapter_id)
        )
        ch = ch_result.scalar_one_or_none()
        if ch:
            chapter_title = ch.chapter_title

    # Reverse-lookup old act mappings
    from backend.db.models.legal_foundation import LawTransitionMapping
    old_refs_result = await db.execute(
        select(LawTransitionMapping).where(
            LawTransitionMapping.new_act == act_code.upper(),
            LawTransitionMapping.new_section == section_number,
            LawTransitionMapping.is_active == True,
        )
    )
    old_refs = [
        {"act_code": m.old_act, "section_number": m.old_section}
        for m in old_refs_result.scalars().all()
    ]

    return SectionDetail(
        act_code=act_code.upper(),
        act_name=act_name,
        section_number=section.section_number,
        section_title=section.section_title,
        chapter=None,  # chapter_number would need join
        chapter_title=chapter_title,
        legal_text=section.legal_text,
        is_offence=section.is_offence,
        is_cognizable=section.is_cognizable,
        is_bailable=section.is_bailable,
        triable_by=section.triable_by,
        replaces=old_refs,
        verification_status="VERIFIED" if section.qdrant_indexed else "VERIFIED_INCOMPLETE",
        extraction_confidence=section.extraction_confidence,
    )


# ---------------------------------------------------------------------------
# GET /sections/normalize
# ---------------------------------------------------------------------------

@router.get("/normalize", response_model=NormalizeResponse)
async def normalize_statute(
    old_act: str = Query(..., description="e.g. IPC or IPC_1860"),
    old_section: str = Query(..., description="e.g. 302"),
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Convert an old statute reference to its new BNS/BNSS/BSA equivalent."""
    from backend.db.repositories.transition_repository import TransitionRepository

    repo = TransitionRepository(db)
    # Normalise act code
    act_map = {
        "IPC": "IPC_1860", "CrPC": "CrPC_1973", "IEA": "IEA_1872",
        "IPC_1860": "IPC_1860", "CrPC_1973": "CrPC_1973", "IEA_1872": "IEA_1872",
    }
    normalised_act = act_map.get(old_act.upper(), old_act.upper())
    mappings = await repo.lookup_transition(normalised_act, old_section)

    if not mappings:
        return NormalizeResponse(
            input={"act": normalised_act, "section": old_section},
            mapped_to=None,
            message=f"No mapping found. {old_act} {old_section} has no BNS/BNSS/BSA equivalent.",
        )

    # lookup_transition returns a list (one old section can split into many new ones).
    # Take the first (highest-confidence) mapping for the normalize endpoint.
    mapping = mappings[0]

    warning = None
    if normalised_act == "IPC_1860" and old_section == "302":
        warning = (
            "CRITICAL: IPC 302 → BNS 103. "
            "BNS 302 is Religious Offences — NOT murder. Never conflate these."
        )
    elif normalised_act == "CrPC_1973" and old_section == "438":
        warning = (
            "CRITICAL: CrPC 438 (Anticipatory Bail) → BNSS 482. "
            "BNSS 438 is Revision Powers — NOT anticipatory bail."
        )

    eff_date = "2024-07-01"

    return NormalizeResponse(
        input={"act": normalised_act, "section": old_section},
        mapped_to={"act": mapping.new_act, "section": mapping.new_section},
        new_section_title=mapping.new_section_title,
        transition_type=mapping.transition_type,
        warning=warning,
        effective_from=eff_date,
        source="database",
    )


# ---------------------------------------------------------------------------
# POST /sections/verify  (batch)
# ---------------------------------------------------------------------------

@router.post("/verify", response_model=VerifyResponse)
async def batch_verify(
    request: VerifyRequest,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Batch-verify multiple section citations against the database."""
    results: list[VerifyResult] = []
    _DANGER_MAP = {
        ("BNS_2023", "302"): "BNS 302 is Religious Offences — NOT murder. Murder is BNS 103.",
        ("BNSS_2023", "438"): "BNSS 438 is Revision Powers — NOT anticipatory bail. Use BNSS 482.",
    }

    for citation in request.citations:
        act = citation.act_code.upper()
        sec = citation.section_number

        row = (
            await db.execute(
                select(Section).where(
                    Section.act_code == act,
                    Section.section_number == sec,
                )
            )
        ).scalar_one_or_none()

        if row is None:
            results.append(VerifyResult(act_code=act, section_number=sec, status="NOT_FOUND"))
            continue

        incomplete = not row.legal_text or not row.section_title
        status = "VERIFIED_INCOMPLETE" if incomplete else "VERIFIED"
        warning = _DANGER_MAP.get((act, sec))

        results.append(
            VerifyResult(
                act_code=act,
                section_number=sec,
                status=status,
                section_title=row.section_title,
                warning=warning,
            )
        )

    return VerifyResponse(results=results)
