# Automatic Legal Document Drafting System Design

## Overview

The document drafting system enables users to generate first-copy drafts of standard Indian legal documents. It uses a **hybrid Template + LLM approach** where Jinja2 templates provide the structural skeleton and legal formatting, while an LLM generates contextually appropriate legal language for dynamic sections.

**Core Principle**: Every drafted document includes a `"DRAFT - FOR REFERENCE ONLY. NOT LEGAL ADVICE."` disclaimer.

---

## 1. Supported Document Types

| Document Type | Primary Users | Complexity | Template Fields |
|--------------|---------------|------------|-----------------|
| First Information Report (FIR) | Citizens, Police | Medium | Complainant info, incident details, accused details, witnesses |
| RTI Application | Citizens | Low | Applicant info, public authority, information sought, fee details |
| Complaint Letter (Consumer) | Citizens | Low-Medium | Consumer details, seller/service provider, complaint, relief sought |
| Complaint Letter (Police) | Citizens | Medium | Complainant info, incident, evidence, prayer |
| Legal Notice | Lawyers, Citizens | High | Sender, receiver, cause of action, demand, timeline |
| Affidavit (General) | All users | Medium | Deponent info, statements, verification |
| Affidavit (Court) | Lawyers | High | Court details, case details, deponent, statements |
| Power of Attorney | Citizens, Advisors | Medium | Principal, agent, powers granted, limitations |
| Bail Application | Lawyers | High | Accused details, case details, FIR info, grounds for bail |
| Written Statement / Petition | Lawyers | Very High | Court details, parties, facts, grounds, prayer |
| Demand Notice | Lawyers, Advisors | Medium | Creditor, debtor, amount, basis, demand, deadline |
| Rent/Lease Agreement | Citizens, Advisors | Medium | Landlord, tenant, property, terms, rent, duration |

---

## 2. Architecture

### 2.1 System Flow

```
User selects document type
    │
    ▼
Frontend fetches template schema (GET /api/v1/documents/templates/{type})
    │
    ▼
Frontend renders dynamic form based on schema
    │
    ▼
User fills in required + optional fields
    │
    ▼
Frontend submits to backend (POST /api/v1/documents/draft)
    │
    ▼
Backend validates fields against schema
    │
    ▼
Query Analyst Agent classifies and extracts legal context
    │
    ▼
Document Drafter Agent generates draft:
    ├── Load Jinja2 template for document structure
    ├── LLM generates legal language for dynamic sections
    ├── Merge template + LLM output
    └── Apply formatting
    │
    ▼
Citation Verifier Agent checks legal references in draft
    │
    ▼
Draft stored in database with status="draft"
    │
    ▼
User reviews, edits, approves
    │
    ▼
PDF generation (POST /api/v1/documents/draft/{id}/pdf)
    │
    ▼
Optional: Translate to regional language
```

### 2.2 Why Hybrid (Template + LLM) Over Pure LLM?

| Aspect | Pure LLM | Pure Template | Hybrid (Chosen) |
|--------|----------|---------------|-----------------|
| Structural consistency | Unreliable | Perfect | Perfect |
| Legal language quality | Good but variable | Rigid/generic | Natural + consistent |
| Handling edge cases | Good | Poor | Good |
| Hallucination risk | High | Zero | Low (limited scope) |
| Personalization | Excellent | None | Good |
| Speed | Slow (~5-10s) | Instant | Fast (~2-4s) |
| Maintenance | None | High | Moderate |

The hybrid approach uses templates for the **structure and boilerplate** (headings, formatting, mandatory clauses, jurisdiction headers) and LLM for the **dynamic legal language** (describing facts in legal terms, suggesting applicable sections, crafting prayer/relief clauses).

---

## 3. Template System

### 3.1 Template Schema Definition

Each document type has a JSON schema defining its fields:

```json
{
  "type": "fir",
  "name": "First Information Report",
  "description": "File a First Information Report at any police station under Section 154 CrPC / Section 173 BNSS",
  "jurisdiction_specific": false,
  "required_fields": [
    {
      "key": "complainant_name",
      "label": "Full Name of Complainant",
      "type": "text",
      "placeholder": "Enter your full legal name",
      "validation": "^[a-zA-Z\\s]{2,100}$"
    },
    {
      "key": "complainant_father_name",
      "label": "Father's/Husband's Name",
      "type": "text"
    },
    {
      "key": "complainant_address",
      "label": "Residential Address",
      "type": "textarea"
    },
    {
      "key": "complainant_phone",
      "label": "Phone Number",
      "type": "tel",
      "validation": "^[6-9]\\d{9}$"
    },
    {
      "key": "police_station",
      "label": "Police Station Name",
      "type": "text"
    },
    {
      "key": "district",
      "label": "District",
      "type": "text"
    },
    {
      "key": "state",
      "label": "State",
      "type": "select",
      "options": ["Andhra Pradesh", "Assam", "Bihar", "...", "West Bengal"]
    },
    {
      "key": "incident_date",
      "label": "Date of Incident",
      "type": "date"
    },
    {
      "key": "incident_time",
      "label": "Approximate Time of Incident",
      "type": "time"
    },
    {
      "key": "incident_location",
      "label": "Place of Incident (Full Address)",
      "type": "textarea"
    },
    {
      "key": "incident_description",
      "label": "Describe what happened in detail",
      "type": "textarea",
      "hint": "Include sequence of events, what you saw/heard, actions taken by accused",
      "min_length": 50,
      "max_length": 5000
    },
    {
      "key": "accused_known",
      "label": "Is the accused known to you?",
      "type": "boolean"
    },
    {
      "key": "accused_details",
      "label": "Details of Accused (Name, Description, Address if known)",
      "type": "textarea"
    }
  ],
  "optional_fields": [
    {
      "key": "witnesses",
      "label": "Witness Details",
      "type": "array",
      "items": {
        "name": {"type": "text", "label": "Witness Name"},
        "address": {"type": "text", "label": "Witness Address"},
        "phone": {"type": "tel", "label": "Witness Phone"}
      }
    },
    {
      "key": "evidence_description",
      "label": "Evidence Available (CCTV, photos, documents, etc.)",
      "type": "textarea"
    },
    {
      "key": "property_lost",
      "label": "Property Lost/Damaged (with estimated value)",
      "type": "textarea"
    },
    {
      "key": "injuries_sustained",
      "label": "Injuries Sustained (if any)",
      "type": "textarea"
    },
    {
      "key": "previous_complaints",
      "label": "Any previous complaints filed?",
      "type": "textarea"
    }
  ]
}
```

### 3.2 Jinja2 Template Example (FIR)

```jinja2
{# templates/fir.jinja2 #}
{% extends "base_legal_document.jinja2" %}

{% block document_title %}FIRST INFORMATION REPORT{% endblock %}
{% block document_subtitle %}(Under Section 154 Cr.P.C. / Section 173 BNSS){% endblock %}

{% block document_body %}
TO,
The Station House Officer,
{{ police_station }} Police Station,
{{ district }}, {{ state }}

Subject: First Information Report regarding {{ legal_sections.offense_category }}

Respected Sir/Madam,

I, {{ complainant_name }}, S/o (D/o, W/o) {{ complainant_father_name }}, aged about {{ complainant_age }} years, residing at {{ complainant_address }}, contact number {{ complainant_phone }}, do hereby lodge the following complaint:

**FACTS OF THE CASE:**

{{ legal_sections.facts_in_legal_language }}

**DATE AND TIME OF INCIDENT:**
The incident occurred on {{ incident_date | format_indian_date }} at approximately {{ incident_time }}, at {{ incident_location }}.

**DETAILS OF ACCUSED:**
{% if accused_known %}
The accused person(s) are known to me:
{{ accused_details }}
{% else %}
The accused person(s) are unknown to me. The following description may help in identification:
{{ accused_details }}
{% endif %}

{% if witnesses %}
**WITNESSES:**
{% for witness in witnesses %}
{{ loop.index }}. {{ witness.name }}, residing at {{ witness.address }}{% if witness.phone %}, Contact: {{ witness.phone }}{% endif %}
{% endfor %}
{% endif %}

{% if evidence_description %}
**EVIDENCE AVAILABLE:**
{{ evidence_description }}
{% endif %}

{% if property_lost %}
**PROPERTY LOST/DAMAGED:**
{{ property_lost }}
{% endif %}

{% if injuries_sustained %}
**INJURIES SUSTAINED:**
{{ injuries_sustained }}
{% endif %}

**APPLICABLE SECTIONS (Auto-suggested):**
{{ legal_sections.applicable_sections_text }}

**PRAYER:**
{{ legal_sections.prayer_text }}

I hereby declare that the above information is true and correct to the best of my knowledge and belief. I understand that filing a false FIR is punishable under Section 182/211 of the Indian Penal Code.

Date: {{ current_date | format_indian_date }}
Place: {{ district }}

Yours faithfully,

_________________________
{{ complainant_name }}
(Signature/Thumb Impression)

---
**DISCLAIMER: This is a computer-generated DRAFT for reference purposes only. This does NOT constitute legal advice. Please verify all details with the concerned police station before submission.**
{% endblock %}
```

### 3.3 Base Template

```jinja2
{# templates/base_legal_document.jinja2 #}
<!DOCTYPE html>
<html>
<head>
    <style>
        body {
            font-family: 'Times New Roman', Times, serif;
            font-size: 12pt;
            line-height: 1.6;
            margin: 2.5cm;
            color: #000;
        }
        .document-title {
            text-align: center;
            font-size: 16pt;
            font-weight: bold;
            text-decoration: underline;
            margin-bottom: 5px;
        }
        .document-subtitle {
            text-align: center;
            font-size: 10pt;
            margin-bottom: 20px;
        }
        .disclaimer {
            border: 2px solid red;
            padding: 10px;
            margin-top: 30px;
            font-size: 9pt;
            color: red;
            text-align: center;
        }
        strong { font-weight: bold; }
    </style>
</head>
<body>
    <div class="document-title">{% block document_title %}{% endblock %}</div>
    <div class="document-subtitle">{% block document_subtitle %}{% endblock %}</div>

    <div class="document-body">
        {% block document_body %}{% endblock %}
    </div>

    <div class="disclaimer">
        DRAFT - FOR REFERENCE ONLY. NOT LEGAL ADVICE.
        Generated by Neethi AI on {{ current_date | format_indian_date }}.
        Please consult a qualified legal professional before using this document.
    </div>
</body>
</html>
```

---

## 4. LLM-Driven Dynamic Content Generation

### 4.1 What the LLM Generates

For each document type, the LLM is responsible for specific dynamic sections:

| Document | LLM-Generated Sections |
|----------|----------------------|
| FIR | Facts in legal language, offense categorization, applicable IPC/BNS sections, prayer text |
| RTI | Formal information request phrasing, legal basis citation (Section 6 RTI Act) |
| Legal Notice | Cause of action in legal terms, consequences/remedy clause, applicable act/section references |
| Bail Application | Grounds for bail (legal arguments), distinguishing precedents, conditions proposed |
| Affidavit | Statement conversion to legal affidavit language, verification clause |
| Written Statement | Legal issues framing, grounds/arguments in legal language, prayer/relief clause |

### 4.2 Generation Pipeline

```python
# document_drafting/engine.py

from jinja2 import Environment, FileSystemLoader
from pydantic import BaseModel
from typing import Dict, Any, Optional
import json

class LegalSections(BaseModel):
    """Structured output from LLM for document generation"""
    facts_in_legal_language: str
    offense_category: Optional[str] = None
    applicable_sections_text: str
    prayer_text: str
    legal_basis: Optional[str] = None
    grounds: Optional[list[str]] = None

DRAFTING_PROMPTS = {
    "fir": """You are an expert Indian legal document drafter. Based on the following incident details provided by a citizen, generate the legal sections for a First Information Report (FIR).

INCIDENT DETAILS:
{incident_description}

ACCUSED DETAILS:
{accused_details}

INJURIES/DAMAGE:
{injuries_sustained}
{property_lost}

Generate the following in proper legal language:

1. **facts_in_legal_language**: Rewrite the incident description in formal legal language suitable for an FIR. Keep all factual details but use appropriate legal terminology. Do NOT add any facts that were not provided.

2. **offense_category**: Classify the offense (e.g., "theft", "assault", "fraud", "cheating", "criminal intimidation", etc.)

3. **applicable_sections_text**: Based on the facts, suggest potentially applicable sections from:
   - Indian Penal Code (IPC) 1860 / Bharatiya Nyaya Sanhita (BNS) 2023
   - Include both old IPC and new BNS section numbers
   - Format: "Section X IPC (Section Y BNS) - [Description]"
   - ONLY suggest sections you are confident about. Mark any uncertain ones with "(to be verified)"

4. **prayer_text**: Generate the prayer/request paragraph asking the SHO to register the FIR and investigate.

IMPORTANT:
- Do NOT hallucinate or invent section numbers
- If unsure about a section, omit it rather than guess
- Keep facts exactly as provided, only rephrase in legal language
- Use formal Indian legal English

Return as JSON matching this schema:
{{"facts_in_legal_language": "...", "offense_category": "...", "applicable_sections_text": "...", "prayer_text": "..."}}""",

    "rti": """You are an expert at drafting RTI applications under the Right to Information Act, 2005.

APPLICANT REQUEST:
{information_sought}

PUBLIC AUTHORITY:
{public_authority}

Generate:
1. **facts_in_legal_language**: Formal phrasing of the information request
2. **applicable_sections_text**: "Under Section 6(1) of the Right to Information Act, 2005..."
3. **prayer_text**: Formal request paragraph
4. **legal_basis**: Brief statement of the applicant's right under RTI Act

Return as JSON.""",

    "legal_notice": """You are a senior Indian lawyer drafting a legal notice.

SENDER: {sender_name}, {sender_address}
RECEIVER: {receiver_name}, {receiver_address}
CAUSE OF ACTION: {cause_description}
RELIEF SOUGHT: {relief_sought}
RELEVANT FACTS: {relevant_facts}

Generate:
1. **facts_in_legal_language**: Facts stated in formal legal language
2. **applicable_sections_text**: All applicable legal provisions (Acts, Sections)
3. **prayer_text**: Formal demand with timeline (typically 15-30 days)
4. **legal_basis**: The legal right/obligation being invoked
5. **grounds**: List of grounds supporting the notice

IMPORTANT: Only cite sections you are confident exist. Use "(subject to verification)" for uncertain references.

Return as JSON.""",

    "bail_application": """You are a criminal defense lawyer drafting a bail application.

ACCUSED: {accused_name}
CASE DETAILS: {case_details}
FIR NUMBER: {fir_number}
POLICE STATION: {police_station}
SECTIONS CHARGED: {sections_charged}
CUSTODY SINCE: {custody_date}
GROUNDS FOR BAIL: {bail_grounds}

Generate:
1. **facts_in_legal_language**: Brief facts of the case in legal language
2. **applicable_sections_text**: Relevant bail provisions (Section 436/437/438/439 CrPC or corresponding BNSS sections)
3. **prayer_text**: Formal prayer for bail with proposed conditions
4. **grounds**: Detailed legal grounds for bail (each as a separate item):
   - Nature of accusation and severity of punishment
   - Applicant's antecedents (if no prior record)
   - Likelihood of tampering with evidence
   - Likelihood of influencing witnesses
   - Health/personal circumstances
   - Duration of custody already served
   - Any constitutional rights arguments (Article 21)

Return as JSON.""",
}


class DocumentDraftingEngine:
    def __init__(self, llm, template_dir: str = "backend/document_drafting/templates"):
        self.llm = llm
        self.env = Environment(
            loader=FileSystemLoader(template_dir),
            autoescape=False,  # Legal docs need raw text
        )
        self.env.filters["format_indian_date"] = self._format_indian_date

        # Load template schemas
        with open(f"{template_dir}/../schemas/template_schemas.json") as f:
            self.schemas = json.load(f)

    async def generate_draft(
        self,
        doc_type: str,
        fields: Dict[str, Any],
        language: str = "en"
    ) -> Dict[str, Any]:
        """Generate a complete document draft"""

        # 1. Validate required fields
        schema = self.schemas[doc_type]
        required_keys = [f["key"] for f in schema["required_fields"]]
        missing = [k for k in required_keys if k not in fields or not fields[k]]
        if missing:
            raise ValueError(f"Missing required fields: {missing}")

        # 2. Generate legal sections via LLM
        prompt_template = DRAFTING_PROMPTS.get(doc_type)
        if prompt_template:
            prompt = prompt_template.format(**fields)
            llm_response = await self.llm.ainvoke(prompt)
            legal_sections = self._parse_llm_response(llm_response)
        else:
            legal_sections = LegalSections(
                facts_in_legal_language=fields.get("description", ""),
                applicable_sections_text="",
                prayer_text="",
            )

        # 3. Render Jinja2 template
        template = self.env.get_template(f"{doc_type}.jinja2")
        rendered_content = template.render(
            **fields,
            legal_sections=legal_sections,
            current_date=datetime.now(),
        )

        # 4. Return draft data
        return {
            "content": rendered_content,
            "legal_sections": legal_sections.model_dump(),
            "document_type": doc_type,
            "language": language,
        }

    def _parse_llm_response(self, response) -> LegalSections:
        """Parse LLM JSON response into structured sections"""
        try:
            text = response.content if hasattr(response, 'content') else str(response)
            # Extract JSON from response (handle markdown code blocks)
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]
            data = json.loads(text.strip())
            return LegalSections(**data)
        except (json.JSONDecodeError, KeyError, IndexError):
            # Fallback: use raw response
            return LegalSections(
                facts_in_legal_language=str(response),
                applicable_sections_text="(Could not auto-detect sections. Please add manually.)",
                prayer_text="(Please draft prayer clause manually.)",
            )

    @staticmethod
    def _format_indian_date(value) -> str:
        """Format date as DD/MM/YYYY (Indian standard)"""
        if isinstance(value, str):
            return value
        from datetime import datetime
        if isinstance(value, datetime):
            return value.strftime("%d/%m/%Y")
        return str(value)
```

---

## 5. PDF Generation

### 5.1 Using WeasyPrint for Indian Legal Document Formatting

```python
# document_drafting/pdf_generator.py

from weasyprint import HTML, CSS
from weasyprint.text.fonts import FontConfiguration
import io

LEGAL_CSS = CSS(string="""
    @page {
        size: A4;
        margin: 2.5cm 2cm 2cm 3cm;  /* Indian legal margin standard */
        @top-center {
            content: "DRAFT - FOR REFERENCE ONLY";
            font-size: 8pt;
            color: #999;
        }
        @bottom-center {
            content: "Page " counter(page) " of " counter(pages);
            font-size: 8pt;
        }
    }
    body {
        font-family: 'Times New Roman', 'Noto Serif Devanagari', serif;
        font-size: 12pt;
        line-height: 1.8;
        text-align: justify;
    }
    h1 { text-align: center; font-size: 14pt; text-decoration: underline; }
    h2 { font-size: 12pt; text-decoration: underline; }
    .section-label { font-weight: bold; text-decoration: underline; }
    .signature-block { margin-top: 40px; }
    .disclaimer {
        border: 1px solid #c00;
        padding: 8px;
        margin-top: 30px;
        font-size: 9pt;
        color: #c00;
        text-align: center;
    }
""")

def generate_pdf(html_content: str, doc_type: str) -> bytes:
    """Generate PDF from rendered HTML legal document"""
    font_config = FontConfiguration()
    html = HTML(string=html_content)
    pdf_bytes = html.write_pdf(
        stylesheets=[LEGAL_CSS],
        font_config=font_config,
        presentational_hints=True,
    )
    return pdf_bytes


def generate_pdf_stream(html_content: str) -> io.BytesIO:
    """Generate PDF as a stream for FastAPI response"""
    pdf_bytes = generate_pdf(html_content, "")
    stream = io.BytesIO(pdf_bytes)
    stream.seek(0)
    return stream
```

### 5.2 FastAPI Endpoints for Document Drafting

```python
# api/routes/documents.py

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from typing import Optional
import uuid
from datetime import datetime

router = APIRouter()

@router.get("/templates")
async def list_templates():
    """List all available document templates"""
    return {
        "templates": [
            {"type": "fir", "name": "First Information Report", "category": "police"},
            {"type": "rti", "name": "RTI Application", "category": "citizen"},
            {"type": "complaint_letter", "name": "Complaint Letter", "category": "citizen"},
            {"type": "legal_notice", "name": "Legal Notice", "category": "legal"},
            {"type": "affidavit", "name": "Affidavit (General)", "category": "legal"},
            {"type": "bail_application", "name": "Bail Application", "category": "lawyer"},
            {"type": "power_of_attorney", "name": "Power of Attorney", "category": "legal"},
            {"type": "rent_agreement", "name": "Rent/Lease Agreement", "category": "property"},
            {"type": "demand_notice", "name": "Demand Notice", "category": "legal"},
        ]
    }

@router.get("/templates/{doc_type}")
async def get_template_schema(doc_type: str):
    """Get the field schema for a specific document type"""
    engine = get_drafting_engine()
    if doc_type not in engine.schemas:
        raise HTTPException(status_code=404, detail=f"Template '{doc_type}' not found")
    return engine.schemas[doc_type]

@router.post("/draft")
async def create_draft(
    request: DraftRequest,
    user = Depends(get_current_user),
    engine = Depends(get_drafting_engine),
):
    """Generate a document draft"""
    try:
        result = await engine.generate_draft(
            doc_type=request.document_type,
            fields=request.fields,
            language=request.language,
        )

        # Store draft in database
        draft_id = str(uuid.uuid4())
        draft = {
            "id": draft_id,
            "user_id": user.id,
            "document_type": request.document_type,
            "content": result["content"],
            "fields": request.fields,
            "legal_sections": result["legal_sections"],
            "status": "draft",
            "created_at": datetime.utcnow().isoformat(),
            "version": 1,
        }
        await db.drafts.insert_one(draft)

        return {
            "draft_id": draft_id,
            "content": result["content"],
            "legal_sections": result["legal_sections"],
            "status": "draft",
            "disclaimer": "DRAFT - FOR REFERENCE ONLY. NOT LEGAL ADVICE.",
        }
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

@router.post("/draft/{draft_id}/pdf")
async def export_draft_pdf(draft_id: str, user = Depends(get_current_user)):
    """Export a draft as PDF"""
    draft = await db.drafts.find_one({"id": draft_id, "user_id": user.id})
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")

    pdf_stream = generate_pdf_stream(draft["content"])

    return StreamingResponse(
        pdf_stream,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{draft["document_type"]}_{draft_id[:8]}.pdf"'
        },
    )

@router.put("/draft/{draft_id}")
async def update_draft(
    draft_id: str,
    request: DraftUpdateRequest,
    user = Depends(get_current_user),
):
    """Update an existing draft (user edits)"""
    draft = await db.drafts.find_one({"id": draft_id, "user_id": user.id})
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")

    update = {
        "content": request.content,
        "status": "edited",
        "version": draft["version"] + 1,
        "updated_at": datetime.utcnow().isoformat(),
    }
    await db.drafts.update_one({"id": draft_id}, {"$set": update})

    return {"draft_id": draft_id, "status": "edited", "version": update["version"]}
```

---

## 6. Jurisdiction-Specific Handling

Indian legal documents vary by state jurisdiction. Key variations:

### 6.1 Variations by State

| Aspect | Variation |
|--------|-----------|
| Court names | "Hon'ble High Court of Kerala" vs "Hon'ble High Court of Bombay" |
| Language of filing | Hindi (Hindi-belt states) vs English (South, NE) vs Bilingual |
| Stamp duty | Different rates per state for affidavits, agreements |
| Filing fees | Vary by court and state |
| Local laws | State-specific amendments to central acts |
| Police station format | Varies slightly by state police |

### 6.2 Implementation

```python
JURISDICTION_CONFIG = {
    "Kerala": {
        "court_language": "English",
        "stamp_duty_affidavit": 50,  # INR
        "high_court": "Hon'ble High Court of Kerala at Ernakulam",
        "notary_format": "kerala_standard",
    },
    "Maharashtra": {
        "court_language": "English/Marathi",
        "stamp_duty_affidavit": 100,
        "high_court": "Hon'ble High Court of Bombay",
        "notary_format": "maharashtra_standard",
    },
    "Delhi": {
        "court_language": "Hindi/English",
        "stamp_duty_affidavit": 10,
        "high_court": "Hon'ble High Court of Delhi",
        "notary_format": "delhi_standard",
    },
    # ... other states
}
```

---

## 7. Validation & Quality Assurance

### 7.1 Pre-Generation Validation

```python
class FieldValidator:
    """Validate user inputs before draft generation"""

    @staticmethod
    def validate_phone_india(phone: str) -> bool:
        """Indian mobile number: 10 digits starting with 6-9"""
        return bool(re.match(r'^[6-9]\d{9}$', phone))

    @staticmethod
    def validate_pin_code(pin: str) -> bool:
        """Indian PIN code: 6 digits, first digit 1-9"""
        return bool(re.match(r'^[1-9]\d{5}$', pin))

    @staticmethod
    def validate_aadhaar(aadhaar: str) -> bool:
        """Aadhaar: 12 digits (we don't store this, only validate format)"""
        return bool(re.match(r'^\d{12}$', aadhaar))

    @staticmethod
    def validate_date_not_future(date_str: str) -> bool:
        """Incident date should not be in the future"""
        from datetime import datetime, date
        try:
            d = datetime.strptime(date_str, "%Y-%m-%d").date()
            return d <= date.today()
        except ValueError:
            return False
```

### 7.2 Post-Generation Verification

The Citation Verifier Agent checks the generated draft for:

1. **Section number accuracy**: Every section mentioned is verified against the `legal_sections` collection in Qdrant
2. **Act name accuracy**: Act names and years are verified
3. **Legal language appropriateness**: No informal language in formal documents
4. **Completeness check**: All mandatory sections of the document are present
5. **Disclaimer presence**: Ensures the draft disclaimer is included

---

## 8. Multilingual Document Drafting

### 8.1 Strategy

```
1. Generate draft in English (LLM is most accurate in English legal language)
2. Translate to target language using Sarvam AI
3. Preserve legal entities (section numbers, act names, case citations) in English
4. Bilingual output option: English + Regional language side by side
```

### 8.2 Implementation

```python
async def generate_bilingual_draft(
    engine: DocumentDraftingEngine,
    doc_type: str,
    fields: dict,
    target_language: str
) -> dict:
    """Generate a bilingual draft (English + target language)"""

    # Generate in English first
    english_draft = await engine.generate_draft(doc_type, fields, language="en")

    # Translate while preserving legal entities
    translated = await translation_service.translate_legal_document(
        text=english_draft["content"],
        target_language=target_language,
        preserve_entities=True,  # Keep section numbers, act names in English
    )

    return {
        "english": english_draft["content"],
        "translated": translated,
        "target_language": target_language,
        "legal_sections": english_draft["legal_sections"],
    }
```

---

## 9. Version History & Draft Management

```python
# Database model for drafts
class DraftDocument:
    id: str                    # UUID
    user_id: str               # Owner
    document_type: str         # fir, rti, etc.
    content: str               # Current rendered content
    fields: dict               # User-provided field values
    legal_sections: dict       # LLM-generated legal sections
    status: str                # draft, edited, reviewed, finalized
    version: int               # Increment on each edit
    versions: list[dict]       # Version history [{version, content, timestamp}]
    language: str              # en, hi, etc.
    created_at: datetime
    updated_at: datetime
    exported_pdf: bool         # Whether PDF was generated
    feedback: Optional[str]    # User feedback on draft quality
```

---

## 10. Template Directory Structure

```
backend/document_drafting/
├── engine.py                      # Main drafting engine
├── pdf_generator.py               # PDF generation
├── field_validator.py             # Input validation
├── templates/
│   ├── base_legal_document.jinja2 # Base template with common styling
│   ├── fir.jinja2                 # First Information Report
│   ├── rti_application.jinja2     # RTI Application
│   ├── complaint_letter.jinja2    # Complaint Letter
│   ├── legal_notice.jinja2        # Legal Notice
│   ├── affidavit_general.jinja2   # General Affidavit
│   ├── affidavit_court.jinja2     # Court Affidavit
│   ├── bail_application.jinja2    # Bail Application
│   ├── power_of_attorney.jinja2   # Power of Attorney
│   ├── demand_notice.jinja2       # Demand Notice
│   ├── rent_agreement.jinja2      # Rent/Lease Agreement
│   └── written_statement.jinja2   # Written Statement/Petition
├── schemas/
│   └── template_schemas.json      # Field definitions for all templates
├── prompts/
│   └── drafting_prompts.py        # LLM prompts per document type
└── jurisdiction/
    └── state_config.json          # State-specific configurations
```

---

## 11. Security Considerations

1. **No PII storage in logs**: User-provided personal details (Aadhaar, phone) are never logged
2. **Draft encryption**: All drafts encrypted at rest in database
3. **SSTI prevention**: Jinja2 sandboxed environment, user inputs are escaped
4. **Rate limiting**: Max 10 drafts per hour per user to prevent abuse
5. **Input sanitization**: All user inputs sanitized before template rendering
6. **Draft expiry**: Unfinalized drafts auto-deleted after 30 days
7. **Audit trail**: All draft operations logged (create, edit, export, delete)
