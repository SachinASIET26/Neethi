"""SC Judgment Ingestion Pipeline — Neethi AI.

Ingests Supreme Court judgments from the Vanga AWS S3 open dataset into:
  - Qdrant `sc_judgments` collection (hybrid dense+sparse search)
  - Supabase `ingested_judgments` table (audit trail + deduplication)

Data source: s3://indian-supreme-court-judgments (CC BY 4.0, no AWS auth needed)
  Parquet: s3://indian-supreme-court-judgments/metadata/parquet/year=YYYY/metadata.parquet
  PDFs:    s3://indian-supreme-court-judgments/data/tar/year=YYYY/english/english.tar

Run on Lightning AI GPU session for BGE-M3 embedding (batch processing).
For incremental daily updates (5-20 judgments), CPU inference is acceptable.

Usage:
    # Download and process 2024–2025 (most recent first)
    python -m backend.preprocessing.sc_judgment_ingester --years 2025 2024

    # Process a specific year range
    python -m backend.preprocessing.sc_judgment_ingester --year-range 2018 2025

    # Dry run: preprocess metadata only, no embedding or Qdrant upsert
    python -m backend.preprocessing.sc_judgment_ingester --years 2024 --dry-run

    # Resume interrupted run (skips already-ingested diary_nos)
    python -m backend.preprocessing.sc_judgment_ingester --years 2024 --resume

Architecture:
    Phase A: Download Parquet metadata + PDF tar from Vanga S3
    Phase B: Preprocess metadata (century-bug fix, domain inference, dedup check)
    Phase C: PDF text extraction (PyMuPDF → Tesseract OCR fallback)
    Phase D: Paragraph-aware chunking (400–500 tokens, 50-token overlap)
    Phase E: BGE-M3 embedding + Qdrant upsert (batch_size=32)
    Phase F: Update ingested_judgments in Supabase

Critical notes from architecture report (docs/neethi_architecture_report.md):
  - Process in REVERSE chronological order (most recent = most legally relevant)
  - Century-bug: judgment_dates < 1950 with partition_year > 1993 → add 100 years
  - Dedup key: diary_no (UNIQUE constraint in ingested_judgments)
  - Point UUID: uuid5(NAMESPACE_URL, f"{diary_no}__chunk{idx}") — deterministic, idempotent
  - ik_url stored as empty string initially; back-filled when Indian Kanoon API available
  - BNSS/BNS judgments (post-2024) are indexed alongside older ones for jurisprudence coverage
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Iterator, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

S3_BASE = "s3://indian-supreme-court-judgments"
S3_PARQUET_TEMPLATE = f"{S3_BASE}/metadata/parquet/year={{year}}/metadata.parquet"
S3_TAR_TEMPLATE = f"{S3_BASE}/data/tar/year={{year}}/english/english.tar"

UUID_NAMESPACE = uuid.NAMESPACE_URL  # namespace for deterministic uuid5 generation

# Chunking parameters (architecture report §9 Phase D)
CHUNK_TARGET_TOKENS = 450    # aim for 400-500 tokens per chunk
CHUNK_MAX_TOKENS = 500       # hard max before forced split
CHUNK_OVERLAP_TOKENS = 50    # tail overlap for context continuity
MIN_PARA_TOKENS = 100        # merge short paragraphs with the next

# BGE-M3 embedding batch size (Lightning AI GPU: 32; CPU incremental: 8)
EMBED_BATCH_SIZE = int(os.getenv("EMBED_BATCH_SIZE", "32"))

# OCR: flag document as needing OCR if PyMuPDF extracts < 200 chars on > 2 pages
OCR_CHAR_THRESHOLD = 200
OCR_PAGE_THRESHOLD = 2

# Case-no prefix → legal domain mapping
_DOMAIN_MAP = {
    "C.A.": "civil",        # Civil Appeal
    "Crl.A.": "criminal",   # Criminal Appeal
    "Crl.M.A.": "criminal", # Criminal Misc. Application
    "W.P.": "constitutional",  # Writ Petition
    "S.L.P.": "civil",      # Special Leave Petition (domain varies; default civil)
    "T.P.": "civil",        # Transfer Petition
    "O.P.": "civil",        # Original Petition
    "Cont.": "constitutional", # Contempt Petition
    "R.P.": "civil",        # Review Petition
    "Curative": "constitutional",
}

# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ingest Vanga S3 SC judgments into Qdrant sc_judgments collection."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--years",
        nargs="+",
        type=int,
        metavar="YYYY",
        help="Specific year(s) to process, e.g. --years 2025 2024 2023",
    )
    group.add_argument(
        "--year-range",
        nargs=2,
        type=int,
        metavar=("FROM", "TO"),
        help="Year range (inclusive) in reverse order, e.g. --year-range 2018 2025",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Download and preprocess metadata only — no embedding or Qdrant upsert.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        default=True,
        help="Skip already-ingested diary_nos (default: True).",
    )
    parser.add_argument(
        "--no-resume",
        dest="resume",
        action="store_false",
        help="Re-process all judgments even if already ingested.",
    )
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=Path("data/raw/judgments"),
        help="Working directory for downloaded tarballs and PDFs.",
    )
    parser.add_argument(
        "--keep-pdfs",
        action="store_true",
        help="Keep extracted PDFs after processing (default: delete to save disk).",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Phase A: Download from Vanga S3
# ---------------------------------------------------------------------------

def download_parquet(year: int, dest_dir: Path) -> Path:
    """Download the Parquet metadata file for a given year from Vanga S3.

    No AWS authentication required — the dataset is an open data registry.

    Args:
        year:     The year partition to download.
        dest_dir: Local directory to save the file.

    Returns:
        Path to the downloaded .parquet file.

    Raises:
        RuntimeError: If aws CLI is not available or download fails.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_file = dest_dir / f"metadata_{year}.parquet"

    if dest_file.exists():
        logger.info("parquet_exists_skipping: %s", dest_file)
        return dest_file

    s3_url = S3_PARQUET_TEMPLATE.format(year=year)
    logger.info("download_parquet: %s → %s", s3_url, dest_file)

    result = subprocess.run(
        ["aws", "s3", "cp", s3_url, str(dest_file), "--no-sign-request"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"aws s3 cp failed for year {year} parquet:\n{result.stderr}"
        )
    return dest_file


def download_tar(year: int, dest_dir: Path) -> Path:
    """Download the English PDF tar archive for a given year from Vanga S3.

    Tarballs are typically 2–4 GB for recent years. The file is kept locally
    only until all PDFs within it are processed, then deleted to free disk.

    Args:
        year:     The year partition to download.
        dest_dir: Local directory to save the tarball.

    Returns:
        Path to the downloaded .tar file.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_file = dest_dir / f"english_{year}.tar"

    if dest_file.exists():
        logger.info("tar_exists_skipping: %s", dest_file)
        return dest_file

    s3_url = S3_TAR_TEMPLATE.format(year=year)
    logger.info("download_tar: %s → %s (this may take several minutes)", s3_url, dest_file)

    result = subprocess.run(
        ["aws", "s3", "cp", s3_url, str(dest_file), "--no-sign-request"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"aws s3 cp failed for year {year} tar:\n{result.stderr}"
        )
    return dest_file


# ---------------------------------------------------------------------------
# Phase B: Metadata preprocessing
# ---------------------------------------------------------------------------

def load_parquet_metadata(parquet_path: Path) -> list[dict]:
    """Load SC judgment Parquet metadata and apply corrections.

    Supports two schema variants:
    - Vanga S3 legacy schema: diary_no, pet, res, judgment_dates, case_no, temp_link
    - eCourts/SCR schema:     cnr, petitioner, respondent, decision_date, case_id, path

    Corrections applied:
    1. Century-bug fix for legacy schema (judgment_dates < 1950 with partition_year > 1993)
    2. legal_domain inference from title/case_no
    3. case_name construction from petitioner/respondent fields

    Args:
        parquet_path: Path to the downloaded .parquet file.

    Returns:
        List of dicts with cleaned metadata fields.
    """
    try:
        import pandas as pd
    except ImportError:
        raise ImportError("pandas is required for Parquet loading: pip install pandas pyarrow")

    df = pd.read_parquet(parquet_path)
    logger.info("parquet_loaded: %d rows, columns=%s", len(df), df.columns.tolist())

    cols = set(df.columns.tolist())

    # Detect schema variant
    is_ecourts_schema = "cnr" in cols or "petitioner" in cols

    records = []
    for _, row in df.iterrows():
        if is_ecourts_schema:
            # ── eCourts/SCR schema ────────────────────────────────────────────
            # cnr = eCourts case reference number (unique dedup key)
            diary_no = str(row.get("cnr", "") or "").strip()
            if not diary_no:
                diary_no = str(row.get("case_id", "") or "").strip()
            if not diary_no:
                continue

            case_no = str(row.get("case_id", "") or "").strip()  # e.g. "2024 INSC 735"
            pet = str(row.get("petitioner", "") or "").strip()
            res = str(row.get("respondent", "") or "").strip()

            # PDF path field contains the SCR path key (e.g. "2024_10_108_125")
            path_field = str(row.get("path", "") or "").strip()
            pdf_filename = path_field + "_EN.pdf" if path_field else None

            # decision_date already in DD-MM-YYYY or YYYY-MM-DD — no century bug
            raw_date = str(row.get("decision_date", "") or "").strip()
            year = int(row.get("year", 0) or 0)
            decision_date = _parse_decision_date(raw_date, partition_year=year)

            # Infer domain from title (more reliable than case_no in this schema)
            title = str(row.get("title", "") or "").upper()
            legal_domain = _infer_legal_domain_from_title(title)

        else:
            # ── Vanga S3 legacy schema ────────────────────────────────────────
            diary_no = str(row.get("diary_no", "") or "").strip()
            if not diary_no:
                continue

            case_no = str(row.get("case_no", "") or "").strip()
            pet = str(row.get("pet", "") or "").strip()
            res = str(row.get("res", "") or "").strip()

            year = int(row.get("year", 0) or 0)
            raw_date = str(row.get("judgment_dates", "") or "").strip()
            decision_date = _parse_decision_date(raw_date, partition_year=year)

            legal_domain = _infer_legal_domain(case_no)

            temp_link = str(row.get("temp_link", "") or "").strip()
            pdf_filename = _extract_pdf_filename(temp_link)

        case_name = f"{pet} v. {res}" if pet and res else (pet or res or "")

        disposal = str(
            row.get("disposal_nature", "") or row.get("Disposal_Nature", "") or ""
        ).strip()

        records.append({
            "diary_no": diary_no,
            "case_no": case_no,
            "case_name": case_name,
            "year": year,
            "decision_date": decision_date,
            "disposal_nature": disposal or None,
            "legal_domain": legal_domain,
            "pdf_filename": pdf_filename,
        })

    logger.info("parquet_preprocessed: %d valid records", len(records))
    return records


def _parse_decision_date(raw_date: str, partition_year: int) -> Optional[date]:
    """Parse and correct judgment date with century-bug fix.

    The eCourts legacy system stored two-digit years, causing dates in the
    ~1994–2003 window to appear as 1894–1903. Correction: if the parsed year
    is < 1950 but the partition_year (from S3 tarball) is > 1993, add 100 years.

    Args:
        raw_date:       Raw date string from Vanga data (e.g. "17-02-1902").
        partition_year: The year of the S3 tarball partition (always correct).

    Returns:
        Corrected date object, or None if parsing fails.
    """
    if not raw_date:
        return None

    # Try multiple date formats used in Vanga data
    for fmt in ("%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            d = datetime.strptime(raw_date, fmt).date()
            # Century-bug correction
            if d.year < 1950 and partition_year > 1993:
                d = d.replace(year=d.year + 100)
            return d
        except ValueError:
            continue

    logger.debug("decision_date_parse_failed: %r (partition_year=%d)", raw_date, partition_year)
    return None


def _infer_legal_domain(case_no: str) -> Optional[str]:
    """Infer legal_domain from the case_no prefix.

    The eCourts case_no field encodes the petition type as a prefix:
      C.A.     → Civil Appeal        → civil
      Crl.A.   → Criminal Appeal     → criminal
      W.P.     → Writ Petition       → constitutional
      S.L.P.   → Special Leave Petition → civil (varies, default civil)

    Args:
        case_no: Formal case number, e.g. "C.A. No.-004292-004292 - 2002".

    Returns:
        Domain string or None if prefix not recognised.
    """
    if not case_no:
        return None
    for prefix, domain in _DOMAIN_MAP.items():
        if case_no.upper().startswith(prefix.upper()):
            return domain
    return None


def _infer_legal_domain_from_title(title_upper: str) -> Optional[str]:
    """Infer legal domain from judgment title text (eCourts schema).

    Used when case_no prefix is not available (e.g. 'C.A.' prefix absent).
    Matches on keywords in the uppercased title string.
    """
    if any(w in title_upper for w in ["CRIMINAL APPEAL", "CRIMINAL MISC", "CRL.", "BAIL"]):
        return "criminal"
    if any(w in title_upper for w in ["CIVIL APPEAL", "CIVIL MISC", "C.A. NO"]):
        return "civil"
    if any(w in title_upper for w in ["WRIT PETITION", "HABEAS CORPUS", "MANDAMUS", "CONTEMPT"]):
        return "constitutional"
    if any(w in title_upper for w in ["SPECIAL LEAVE", "SLP", "TRANSFER PETITION"]):
        return "civil"
    if any(w in title_upper for w in ["INCOME TAX", "GST", "CUSTOMS", "COMPANY"]):
        return "corporate"
    return None


def _extract_pdf_filename(temp_link: str) -> Optional[str]:
    """Extract just the PDF filename from a Vanga temp_link field.

    temp_link format: "jonew/judis/18613.pdf (English)"
    Returns: "18613.pdf" (basename only, no language suffix)
    """
    if not temp_link:
        return None
    # Strip language annotation in parentheses
    clean = re.sub(r"\s*\(.*?\)\s*$", "", temp_link).strip()
    return Path(clean).name if clean else None


# Keyword lists for text-based domain inference
# Checked in order: criminal → constitutional → civil (default)
_CRIMINAL_TEXT_SIGNALS = [
    # SC jurisdictional headers (appear on page 1, stripped by cleaner — use raw_text)
    "CRIMINAL APPELLATE JURISDICTION",
    # Case-type phrases in the opening paragraph
    "CRIMINAL APPEAL NO",
    "CRIMINAL APPEAL NO.",
    "CRL. APPEAL",
    "CRIMINAL MISC. PETITION",
    "CRIMINAL MISC. APPLICATION",
    "CRIMINAL MISC PETITION",
    "CRIMINAL MISC APPLICATION",
    "BAIL APPLICATION",
    "BAIL APPLN",
    # Opening sentence patterns
    "THIS CRIMINAL APPEAL",
    "PRESENT CRIMINAL APPEAL",
    "THESE CRIMINAL APPEALS",
    "THIS IS A CRIMINAL APPEAL",
    # Outcome/party language unique to criminal matters
    "CONVICTED BY THE SESSIONS",
    "ACQUITTED BY THE SESSIONS",
    "SESSIONS JUDGE",
    "SESSIONS COURT",
    # New criminal code (post-2024 judgments)
    "BHARATIYA NYAYA SANHITA",
    "BHARATIYA NAGARIK SURAKSHA SANHITA",
]

_CONSTITUTIONAL_TEXT_SIGNALS = [
    # SC jurisdictional headers (page 1, stripped by cleaner — use raw_text)
    "ORIGINAL JURISDICTION",
    "WRIT JURISDICTION",
    # Petition-type phrases
    "WRIT PETITION",
    "HABEAS CORPUS",
    "MANDAMUS",
    "CERTIORARI",
    # Article references
    "ARTICLE 32 OF THE CONSTITUTION",
    "ARTICLE 32 OF CONSTITUTION",
    "ARTICLE 226 OF THE CONSTITUTION",
    "ARTICLE 226 OF CONSTITUTION",
    "ART. 32",
    # Opening sentence patterns
    "THIS WRIT PETITION",
    "THE PRESENT WRIT PETITION",
    "THESE WRIT PETITIONS",
    # Other constitutional jurisdiction markers
    "FUNDAMENTAL RIGHT",
    "FUNDAMENTAL RIGHTS",
    "CONTEMPT OF COURT",
    "CURATIVE PETITION",
]


def _infer_domain_from_text(opening_text: str) -> str:
    """Infer legal domain from the opening section of a judgment PDF.

    Supreme Court judgments always begin with jurisdictional headings and an
    introductory sentence that explicitly names the case type.  Reading the
    first ~3 000 characters of the **raw** extracted text (before
    ``clean_judgment_text`` strips boilerplate headers) is far more reliable
    than case_no prefix matching, which fails entirely for INSC neutral-
    citation format (e.g. "2023 INSC 2").

    Signal priority:
      1. Jurisdictional headers  — "CRIMINAL APPELLATE JURISDICTION", etc.
         (present in raw text; removed by the text cleaner)
      2. Opening-sentence keywords — "criminal appeal", "writ petition", etc.
      3. Article / code references — "Article 32", "Bharatiya Nyaya Sanhita"
      4. Default → "civil"  (civil appeals, SLPs, service matters, property)

    Args:
        opening_text: First ~3 000 characters of the raw extracted PDF text
                      (i.e. *before* ``clean_judgment_text`` is applied).

    Returns:
        'criminal', 'constitutional', or 'civil' (never None).
    """
    text = opening_text.upper()

    # Check criminal signals first — they are unambiguous in SC proceedings
    for signal in _CRIMINAL_TEXT_SIGNALS:
        if signal in text:
            return "criminal"

    # Check constitutional signals
    for signal in _CONSTITUTIONAL_TEXT_SIGNALS:
        if signal in text:
            return "constitutional"

    # Default: civil (civil appeals, SLPs, service, property, family, commercial)
    return "civil"


# ---------------------------------------------------------------------------
# Phase C: PDF text extraction
# ---------------------------------------------------------------------------

def extract_pdf_text(pdf_path: Path) -> tuple[str, bool]:
    """Extract text from a PDF using PyMuPDF with Tesseract OCR fallback.

    Extraction strategy:
    1. Try PyMuPDF (fitz) text extraction
    2. If extracted text < OCR_CHAR_THRESHOLD for a multi-page document,
       flag ocr_required=True and use Tesseract OCR via pytesseract

    Args:
        pdf_path: Path to the PDF file.

    Returns:
        (extracted_text, ocr_required) tuple.
    """
    import fitz  # PyMuPDF

    try:
        doc = fitz.open(str(pdf_path))
        page_count = len(doc)

        # Attempt native text extraction
        text_parts = []
        for page in doc:
            text_parts.append(page.get_text())
        raw_text = "\n".join(text_parts)
        doc.close()

        # Check if extraction quality is sufficient
        if (
            len(raw_text.strip()) < OCR_CHAR_THRESHOLD
            and page_count > OCR_PAGE_THRESHOLD
        ):
            logger.info(
                "pdf_ocr_fallback: %s (chars=%d, pages=%d)",
                pdf_path.name, len(raw_text.strip()), page_count,
            )
            ocr_text = _ocr_pdf(pdf_path)
            return ocr_text, True

        return raw_text, False

    except Exception as exc:
        logger.warning("pdf_extract_failed: %s — %s", pdf_path.name, exc)
        return "", False


def _ocr_pdf(pdf_path: Path) -> str:
    """Tesseract OCR fallback for scanned PDFs.

    Converts each page to an image and runs pytesseract on it.
    Much slower than native extraction — used only when necessary.
    """
    try:
        import fitz
        import pytesseract
        from PIL import Image
        import io

        doc = fitz.open(str(pdf_path))
        text_parts = []
        for page in doc:
            # Render page at 200 DPI for good OCR quality
            pix = page.get_pixmap(dpi=200)
            img_bytes = pix.tobytes("png")
            img = Image.open(io.BytesIO(img_bytes))
            text_parts.append(pytesseract.image_to_string(img, lang="eng"))
        doc.close()
        return "\n".join(text_parts)
    except Exception as exc:
        logger.warning("ocr_failed: %s — %s", pdf_path.name, exc)
        return ""


def clean_judgment_text(raw_text: str) -> str:
    """Clean extracted text: remove headers, footers, boilerplate.

    Common noise in SC judgment PDFs:
    - Supreme Court of India letterhead on page 1
    - Page numbers (standalone digits at line boundaries)
    - Repetitive "IN THE SUPREME COURT OF INDIA" headers
    - "REPORTABLE" / "NOT REPORTABLE" stamps
    - Case number headers that repeat on each page

    Args:
        raw_text: Raw extracted text from PyMuPDF or Tesseract.

    Returns:
        Cleaned text with noise patterns removed.
    """
    if not raw_text:
        return ""

    lines = raw_text.split("\n")
    cleaned = []
    for line in lines:
        stripped = line.strip()
        # Skip standalone page numbers
        if re.fullmatch(r"\d{1,4}", stripped):
            continue
        # Skip repetitive SC header lines
        if stripped.upper() in (
            "IN THE SUPREME COURT OF INDIA",
            "SUPREME COURT OF INDIA",
            "REPORTABLE",
            "NOT REPORTABLE",
            "NON-REPORTABLE",
            "CIVIL APPELLATE JURISDICTION",
            "CRIMINAL APPELLATE JURISDICTION",
            "ORIGINAL JURISDICTION",
            "WRIT JURISDICTION",
        ):
            continue
        # Skip lines that are just underscores or dashes (page dividers)
        if re.fullmatch(r"[-_]{3,}", stripped):
            continue
        cleaned.append(line)

    text = "\n".join(cleaned)
    # Collapse runs of 3+ blank lines to at most 2
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ---------------------------------------------------------------------------
# Phase D: Paragraph-aware chunking
# ---------------------------------------------------------------------------

def _token_count(text: str) -> int:
    """Approximate token count using whitespace split (fast, good enough for chunking)."""
    return len(text.split())


def chunk_judgment_text(
    text: str,
    target_tokens: int = CHUNK_TARGET_TOKENS,
    max_tokens: int = CHUNK_MAX_TOKENS,
    overlap_tokens: int = CHUNK_OVERLAP_TOKENS,
    min_para_tokens: int = MIN_PARA_TOKENS,
) -> list[str]:
    """Split judgment text into paragraph-aware chunks for embedding.

    Strategy:
    1. Split on double-newline paragraph boundaries
    2. Merge short paragraphs (< min_para_tokens) with the following paragraph
       until the chunk reaches target_tokens
    3. If a single paragraph exceeds max_tokens, split at nearest sentence
       boundary before max_tokens, with overlap_tokens carried to next chunk

    Args:
        text:           Cleaned judgment text.
        target_tokens:  Target chunk size in tokens (default 450).
        max_tokens:     Hard maximum before forced sentence split (default 500).
        overlap_tokens: Tokens to repeat at start of next chunk (default 50).
        min_para_tokens: Paragraphs shorter than this are merged (default 100).

    Returns:
        List of text chunks (each 400–500 tokens, preserving paragraph integrity).
    """
    if not text.strip():
        return []

    # Split into paragraphs
    raw_paragraphs = [p.strip() for p in re.split(r"\n{2,}", text)]
    paragraphs = [p for p in raw_paragraphs if p]

    chunks: list[str] = []
    current_parts: list[str] = []
    current_tokens = 0
    pending_overlap: str = ""

    for para in paragraphs:
        para_tokens = _token_count(para)

        if para_tokens > max_tokens:
            # Paragraph is too large — split at sentence boundaries
            # Flush current accumulated parts first
            if current_parts:
                chunk_text = " ".join(current_parts)
                if pending_overlap:
                    chunk_text = pending_overlap + " " + chunk_text
                chunks.append(chunk_text.strip())
                # Keep last overlap_tokens words as pending overlap for next chunk
                words = chunk_text.split()
                pending_overlap = " ".join(words[-overlap_tokens:]) if len(words) > overlap_tokens else ""
                current_parts = []
                current_tokens = 0

            # Split the long paragraph into sentence-boundary sub-chunks
            sub_chunks = _split_at_sentences(para, max_tokens, overlap_tokens)
            for sc in sub_chunks[:-1]:
                if pending_overlap:
                    sc = pending_overlap + " " + sc
                chunks.append(sc.strip())
                words = sc.split()
                pending_overlap = " ".join(words[-overlap_tokens:]) if len(words) > overlap_tokens else ""

            # The last sub-chunk becomes the start of the next accumulation
            if sub_chunks:
                last = sub_chunks[-1]
                current_parts = [last]
                current_tokens = _token_count(last)

        elif current_tokens + para_tokens >= target_tokens and current_tokens >= min_para_tokens:
            # Adding this paragraph would exceed target — flush current and start new chunk
            chunk_text = " ".join(current_parts)
            if pending_overlap:
                chunk_text = pending_overlap + " " + chunk_text
            chunks.append(chunk_text.strip())
            words = chunk_text.split()
            pending_overlap = " ".join(words[-overlap_tokens:]) if len(words) > overlap_tokens else ""
            current_parts = [para]
            current_tokens = para_tokens

        else:
            # Accumulate paragraph into current chunk
            current_parts.append(para)
            current_tokens += para_tokens

    # Flush remaining text
    if current_parts:
        chunk_text = " ".join(current_parts)
        if pending_overlap:
            chunk_text = pending_overlap + " " + chunk_text
        chunks.append(chunk_text.strip())

    return [c for c in chunks if c.strip()]


def _split_at_sentences(text: str, max_tokens: int, overlap_tokens: int) -> list[str]:
    """Split text at sentence boundaries to stay under max_tokens.

    Uses a simple heuristic: split after ". " or ".\n" patterns.
    """
    sentences = re.split(r"(?<=[.!?])\s+", text)
    sub_chunks: list[str] = []
    current: list[str] = []
    current_tokens = 0
    overlap_text = ""

    for sentence in sentences:
        sent_tokens = _token_count(sentence)
        if current_tokens + sent_tokens >= max_tokens and current:
            chunk = overlap_text + " " + " ".join(current) if overlap_text else " ".join(current)
            sub_chunks.append(chunk.strip())
            words = chunk.split()
            overlap_text = " ".join(words[-overlap_tokens:]) if len(words) > overlap_tokens else ""
            current = [sentence]
            current_tokens = sent_tokens
        else:
            current.append(sentence)
            current_tokens += sent_tokens

    if current:
        chunk = overlap_text + " " + " ".join(current) if overlap_text else " ".join(current)
        sub_chunks.append(chunk.strip())

    return sub_chunks


def assign_section_types(chunks: list[str]) -> list[str]:
    """Assign section_type label to each chunk based on its position.

    Heuristic from architecture report §7.3:
      - "background":  first 2 chunks (procedural facts, case summary)
      - "analysis":    middle chunks (ratio decidendi, legal reasoning)
      - "conclusion":  last 2 chunks (final order, outcome)

    Args:
        chunks: List of text chunks for one judgment.

    Returns:
        List of section_type strings, same length as chunks.
    """
    total = len(chunks)
    if total == 0:
        return []
    if total == 1:
        return ["conclusion"]
    if total == 2:
        return ["background", "conclusion"]
    if total == 3:
        return ["background", "analysis", "conclusion"]

    types = []
    for i in range(total):
        if i < 2:
            types.append("background")
        elif i >= total - 2:
            types.append("conclusion")
        else:
            types.append("analysis")
    return types


# ---------------------------------------------------------------------------
# Phase E: Embedding + Qdrant upsert
# ---------------------------------------------------------------------------

def embed_and_upsert_judgment(
    diary_no: str,
    case_name: str,
    case_no: str,
    year: int,
    decision_date: Optional[date],
    disposal_nature: Optional[str],
    legal_domain: Optional[str],
    chunks: list[str],
    qdrant_client,
    embedder,
) -> list[str]:
    """Embed judgment chunks and upsert to Qdrant sc_judgments collection.

    Each chunk becomes one Qdrant point. Point UUID is deterministic:
        uuid5(NAMESPACE_URL, f"{diary_no}__chunk{idx}")
    This makes the pipeline fully idempotent — re-running overwrites
    existing points with identical data, no duplicates accumulate.

    Args:
        diary_no:       Primary dedup key.
        case_name:      "Petitioner v. Respondent".
        case_no:        Formal eCourts case number.
        year:           Year of judgment.
        decision_date:  Corrected decision date.
        disposal_nature: Disposal category.
        legal_domain:   Inferred legal domain.
        chunks:         List of text chunks to embed.
        qdrant_client:  Connected Qdrant client (sync).
        embedder:       Loaded BGEM3Embedder instance.

    Returns:
        List of point UUID strings (one per chunk) for storage in ingested_judgments.
    """
    from qdrant_client.models import PointStruct, SparseVector
    from backend.rag.embeddings import sparse_dict_to_qdrant
    from backend.rag.qdrant_setup import COLLECTION_SC_JUDGMENTS

    section_types = assign_section_types(chunks)
    total_chunks = len(chunks)
    point_ids: list[str] = []

    # Process in batches for memory efficiency
    for batch_start in range(0, total_chunks, EMBED_BATCH_SIZE):
        batch = chunks[batch_start: batch_start + EMBED_BATCH_SIZE]
        batch_indices = list(range(batch_start, batch_start + len(batch)))

        # Generate deterministic UUIDs for this batch
        batch_uuids = [
            str(uuid.uuid5(UUID_NAMESPACE, f"{diary_no}__chunk{idx}"))
            for idx in batch_indices
        ]

        # Embed: dense + sparse in one BGE-M3 forward pass
        dense_vecs = embedder.encode_dense(batch)
        sparse_dicts = embedder.encode_sparse(batch)

        # Build Qdrant PointStructs
        points = []
        for i, (chunk_text, chunk_idx, point_uuid) in enumerate(
            zip(batch, batch_indices, batch_uuids)
        ):
            sv = sparse_dict_to_qdrant(sparse_dicts[i])
            points.append(
                PointStruct(
                    id=point_uuid,
                    vector={
                        "dense": dense_vecs[i],
                        "sparse": SparseVector(**sv),
                    },
                    payload={
                        "text": chunk_text,
                        "chunk_index": chunk_idx,
                        "total_chunks": total_chunks,
                        "section_type": section_types[chunk_idx],
                        "case_name": case_name,
                        "case_no": case_no,
                        "diary_no": diary_no,
                        "disposal_nature": disposal_nature or "",
                        "year": year,
                        "decision_date": decision_date.isoformat() if decision_date else "",
                        "legal_domain": legal_domain or "",
                        "ik_url": "",   # populated in future IK enrichment pass
                        "language": "en",
                    },
                )
            )

        qdrant_client.upsert(
            collection_name=COLLECTION_SC_JUDGMENTS,
            points=points,
            wait=True,
        )
        point_ids.extend(batch_uuids)
        logger.debug(
            "upserted_batch: diary_no=%s chunks=%d/%d",
            diary_no, batch_start + len(batch), total_chunks,
        )

    return point_ids


# ---------------------------------------------------------------------------
# Phase F: Update ingested_judgments in Supabase
# ---------------------------------------------------------------------------

def _compute_pdf_hash(pdf_path: Path) -> str:
    """Return SHA-256 hex digest of a PDF file for change detection."""
    h = hashlib.sha256()
    with open(pdf_path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Main pipeline orchestration
# ---------------------------------------------------------------------------

def process_year(
    year: int,
    work_dir: Path,
    dry_run: bool = False,
    resume: bool = True,
    keep_pdfs: bool = False,
) -> dict:
    """Full pipeline for one year of SC judgments.

    Args:
        year:     Year to process (e.g. 2024).
        work_dir: Working directory for downloads.
        dry_run:  If True, preprocess metadata only (no embedding/upsert).
        resume:   If True, skip already-ingested diary_nos.
        keep_pdfs: If True, do not delete extracted PDFs after processing.

    Returns:
        Stats dict: {processed, skipped, failed, total}.
    """
    import os

    logger.info("=" * 60)
    logger.info("process_year: START year=%d", year)
    logger.info("=" * 60)

    stats = {"year": year, "processed": 0, "skipped": 0, "failed": 0, "total": 0}

    # ── Phase A: Download ────────────────────────────────────────────────────
    try:
        parquet_path = download_parquet(year, work_dir)
    except RuntimeError as exc:
        logger.error("download_parquet_failed: year=%d — %s", year, exc)
        return stats

    # ── Phase B: Load and preprocess metadata ────────────────────────────────
    records = load_parquet_metadata(parquet_path)
    stats["total"] = len(records)

    if dry_run:
        logger.info("dry_run: metadata_only — %d records loaded, no embedding", len(records))
        return stats

    # ── Set up database session ──────────────────────────────────────────────
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    db_url = os.getenv("DATABASE_URL", "").replace("+asyncpg", "+psycopg2")
    if not db_url:
        logger.error("process_year: DATABASE_URL not set in environment")
        return stats

    sync_engine = create_engine(db_url, pool_pre_ping=True)

    # ── Set up Qdrant client and embedder ────────────────────────────────────
    from backend.rag.qdrant_setup import get_qdrant_client
    from backend.rag.embeddings import BGEM3Embedder

    qdrant_client = get_qdrant_client()
    logger.info("loading_embedder: BGEM3Embedder (BGE-M3, ~2GB model)...")
    embedder = BGEM3Embedder()
    logger.info("embedder_loaded")

    # ── Download and extract PDF tar ─────────────────────────────────────────
    try:
        tar_path = download_tar(year, work_dir)
    except RuntimeError as exc:
        logger.error("download_tar_failed: year=%d — %s", year, exc)
        sync_engine.dispose()
        return stats

    extract_dir = work_dir / f"pdfs_{year}"
    extract_dir.mkdir(parents=True, exist_ok=True)

    logger.info("extracting_tar: %s → %s", tar_path, extract_dir)
    with tarfile.open(tar_path, "r") as tf:
        tf.extractall(extract_dir)
    logger.info("tar_extracted: %s", extract_dir)

    # ── Process each judgment ────────────────────────────────────────────────
    from backend.db.repositories.judgment_repository import (
        is_already_ingested,
        upsert_judgment_record,
    )

    with Session(sync_engine) as session:
        for i, record in enumerate(records):
            diary_no = record["diary_no"]
            stats["total"] = len(records)

            # Skip already-ingested (if resume mode)
            if resume and is_already_ingested(diary_no, session):
                logger.debug("skip_already_ingested: %s", diary_no)
                stats["skipped"] += 1
                continue

            # Find the PDF file
            pdf_filename = record.get("pdf_filename")
            if not pdf_filename:
                logger.warning("no_pdf_filename: diary_no=%s", diary_no)
                stats["failed"] += 1
                continue

            # PDFs may be nested in subdirectories within the tar
            pdf_candidates = list(extract_dir.rglob(pdf_filename))
            if not pdf_candidates:
                logger.warning("pdf_not_found: %s in %s", pdf_filename, extract_dir)
                stats["failed"] += 1
                continue

            pdf_path = pdf_candidates[0]

            try:
                # ── Phase C: Extract text ───────────────────────────────────
                raw_text, ocr_required = extract_pdf_text(pdf_path)
                if not raw_text.strip():
                    logger.warning("empty_pdf: %s", pdf_path.name)
                    stats["failed"] += 1
                    continue

                # Derive domain from actual PDF content BEFORE cleaning —
                # the raw text retains jurisdictional headers
                # ("CRIMINAL APPELLATE JURISDICTION", "ORIGINAL JURISDICTION")
                # that clean_judgment_text() strips.  This is far more reliable
                # than the case_no prefix approach, which fails for INSC
                # neutral citations ("2023 INSC 2").
                record["legal_domain"] = _infer_domain_from_text(raw_text[:3000])
                logger.debug(
                    "domain_from_text: diary_no=%s domain=%s",
                    diary_no, record["legal_domain"],
                )

                clean_text = clean_judgment_text(raw_text)
                pdf_hash = _compute_pdf_hash(pdf_path)

                # ── Phase D: Chunk ──────────────────────────────────────────
                chunks = chunk_judgment_text(clean_text)
                if not chunks:
                    logger.warning("no_chunks: %s", diary_no)
                    stats["failed"] += 1
                    continue

                # ── Phase E: Embed + Qdrant upsert ──────────────────────────
                point_ids = embed_and_upsert_judgment(
                    diary_no=diary_no,
                    case_name=record["case_name"],
                    case_no=record["case_no"],
                    year=record["year"],
                    decision_date=record["decision_date"],
                    disposal_nature=record["disposal_nature"],
                    legal_domain=record["legal_domain"],
                    chunks=chunks,
                    qdrant_client=qdrant_client,
                    embedder=embedder,
                )

                # ── Phase F: Update Supabase ─────────────────────────────────
                upsert_judgment_record(
                    diary_no=diary_no,
                    case_no=record["case_no"],
                    case_name=record["case_name"],
                    year=record["year"],
                    decision_date=record["decision_date"],
                    disposal_nature=record["disposal_nature"],
                    legal_domain=record["legal_domain"],
                    qdrant_point_ids=point_ids,
                    chunk_count=len(chunks),
                    pdf_hash=pdf_hash,
                    ocr_required=ocr_required,
                    sync_session=session,
                )

                stats["processed"] += 1
                if (i + 1) % 100 == 0:
                    logger.info(
                        "progress: year=%d %d/%d (processed=%d skipped=%d failed=%d)",
                        year, i + 1, len(records),
                        stats["processed"], stats["skipped"], stats["failed"],
                    )

            except Exception as exc:
                logger.exception("judgment_failed: %s — %s", diary_no, exc)
                stats["failed"] += 1
                continue
            finally:
                # Delete PDF if not keeping them (save disk space)
                if not keep_pdfs and pdf_path.exists():
                    pdf_path.unlink()

    # ── Cleanup ───────────────────────────────────────────────────────────────
    if not keep_pdfs and extract_dir.exists():
        import shutil
        shutil.rmtree(extract_dir, ignore_errors=True)
        logger.info("cleaned_up: %s", extract_dir)

    sync_engine.dispose()

    logger.info(
        "process_year: DONE year=%d processed=%d skipped=%d failed=%d total=%d",
        year, stats["processed"], stats["skipped"], stats["failed"], stats["total"],
    )
    return stats


def main() -> None:
    """CLI entry point."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    args = _parse_args()

    # Determine years to process
    if args.years:
        years = sorted(args.years, reverse=True)  # most recent first
    else:
        from_year, to_year = args.year_range
        years = list(range(max(from_year, to_year), min(from_year, to_year) - 1, -1))

    logger.info("sc_judgment_ingester: years=%s dry_run=%s resume=%s", years, args.dry_run, args.resume)

    all_stats = []
    for year in years:
        stats = process_year(
            year=year,
            work_dir=args.work_dir,
            dry_run=args.dry_run,
            resume=args.resume,
            keep_pdfs=args.keep_pdfs,
        )
        all_stats.append(stats)

    # Summary
    total_processed = sum(s["processed"] for s in all_stats)
    total_skipped = sum(s["skipped"] for s in all_stats)
    total_failed = sum(s["failed"] for s in all_stats)
    logger.info(
        "INGESTION COMPLETE: years=%s total_processed=%d total_skipped=%d total_failed=%d",
        years, total_processed, total_skipped, total_failed,
    )


if __name__ == "__main__":
    main()
