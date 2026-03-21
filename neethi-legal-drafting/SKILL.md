---
name: neethi-legal-drafting
description: >
  Automated Indian legal document drafting agent skill for Neethi AI.
  Use this skill whenever a user requests generation, drafting, or creation of
  any Indian legal document — including FIR complaints, bail applications, legal
  notices, RTI applications, or consumer complaints. Also triggers when the user
  describes a legal situation and needs a formal document produced from it, or
  when they ask "how do I write a complaint against...", "draft a notice to...",
  "help me file an RTI", or "I need a consumer complaint form". Handles
  jurisdiction-specific variations for central law and Kerala state law.
  Integrates with the existing Neethi AI documents.py router and LiteLLM pipeline.
---

# Neethi AI — Legal Document Drafting Skill

## Purpose and scope

This skill guides the drafting of five core Indian legal documents that citizens,
lawyers, and police officers most frequently need in the Neethi AI system. It
does not replace the existing documents.py router — it extends it with
document-type-aware prompting, mandatory field validation, and jurisdiction
awareness that the generic `_template_prompt()` function lacks.

**Documents covered in this version (start small, iterate):**
1. FIR Draft / Written Complaint
2. Bail Application (Regular — BNSS Section 480)
3. Legal Notice (Government under CPC Section 80, and private parties)
4. RTI Application (Central Government and Kerala State)
5. Consumer Complaint (Form 1 under Consumer Protection Act 2019)

**Documents deliberately excluded from this version** (build these later once
the first five are proven): Vakalatnama, Writ Petitions, POCSO complaints,
Domestic Violence applications, Maintenance applications. These have higher
jurisdiction specificity risk and need more validation infrastructure before
they should be generated automatically.

---

## Critical principles before you draft anything

**On legal accuracy:** You are generating a DRAFT document. Every document must
end with the disclaimer already in the system:
`DRAFT ONLY — NOT LEGAL ADVICE. This document requires review by a qualified
lawyer before filing or use.`
Do not remove this. Do not soften it. It exists because wrong legal documents
cause real harm to real people.

**On jurisdiction:** India is not one legal system. The same document type can
have different mandatory sections, different addressees, different fee structures,
and different statutory authorities depending on whether it goes to a central
government body, a Kerala state body, or a court. Always confirm jurisdiction
before drafting. When in doubt, default to the central law version and flag
the state-specific variation in a note.

**On the existing system:** The documents.py router already has template
definitions for `fir_complaint`, `bail_application`, and `legal_notice`. This
skill enhances how those templates are prompted — it does not create new API
endpoints. For RTI and consumer complaints, new template entries are needed
in the `_TEMPLATES` list in documents.py.

**On user emotional state:** Citizens requesting FIR drafts or domestic incident
reports are often distressed. The intent_classifier already detects
`emotional_tone`. When tone is `distressed` or `urgent`, acknowledge this briefly
before asking clarifying questions. Do not be clinical.

---

## Workflow — follow this for every drafting request

### Step 1: Identify the document type

Map the user's request to one of the five supported template IDs. Use the
table below. If the request does not map to any of these five, tell the user
honestly which document they need and that this version of the drafting agent
does not yet support it.

| User says... | Template ID | Reference file |
|---|---|---|
| FIR / complaint to police / first information | `fir_complaint` | `references/fir_draft.md` |
| Bail / release from custody / BNSS 480 | `bail_application` | `references/bail_application.md` |
| Legal notice / demand notice / Section 80 notice | `legal_notice` | `references/legal_notice.md` |
| RTI / right to information / information request | `rti_application` | `references/rti_application.md` |
| Consumer complaint / cheating by company / defective product | `consumer_complaint` | `references/consumer_complaint.md` |

### Step 2: Read the relevant reference file

Before generating anything, read the reference file for the identified
document type. Each reference file contains:
- The statutory source and what it mandates
- Required vs optional fields with validation rules
- Jurisdiction branches (central vs Kerala state)
- The actual document structure with section headings
- Specific LLM prompting guidance for narrative sections
- Common mistakes that make the document legally weak

### Step 3: Determine jurisdiction

Ask — or infer from context — the following:

```
For FIR:         Which state? Which police station district?
For bail:        Which court? Sessions Court or Magistrate Court?
                 (Use triable_by data from BNSS Schedule if available)
For legal notice: Government entity (→ CPC Section 80 applies) or private
                  party? Which state is the recipient in?
For RTI:         Central government department or Kerala state department?
                 (Different fee, different PIO address format)
For consumer:    District Commission / State Commission / National Commission?
                 (Determined by claim amount: <50L / 50L–2Cr / >2Cr)
```

Do not guess jurisdiction. If the user has not provided it, ask. One clear
question is better than a document with the wrong court name.

### Step 4: Collect required fields

Each document has mandatory fields that cannot be left blank or
invented. These are listed in the reference file. Collect them from the
user's description first. Only ask for fields not already provided.

**Never invent:** Names, FIR numbers, case numbers, dates of incidents,
addresses, section numbers, court names, or amounts. If a field is unknown,
leave a clearly marked placeholder: `[TO BE FILLED: Section number of offence]`

**Fields you can supply from system knowledge:** Correct BNS/BNSS/BSA section
numbers (always cite the new sanhitas for post-July 2024 incidents), correct
court hierarchy based on triable_by, correct commission tier for consumer
complaints based on claim amount.

### Step 5: Generate the document

Call the LLM with the document-type-specific prompt from the reference file.
The prompt must include:
- The exact statutory basis for this document type
- All user-provided fields verbatim (never paraphrase names or incident facts)
- The required structural sections in order
- The jurisdiction-specific elements
- An instruction to use formal Indian legal language appropriate to the
  user's role (citizen language for citizens; technical for lawyers)

### Step 6: Validate before returning

Before returning the draft, check:
- [ ] Does it contain the DRAFT ONLY disclaimer?
- [ ] Are all mandatory fields filled or clearly marked as placeholders?
- [ ] Are section numbers correct for post-July 2024 incidents?
  (BNS not IPC, BNSS not CrPC, BSA not IEA)
- [ ] Does the addressee match the jurisdiction?
- [ ] For government notices: is the 2-month notice period under CPC Section 80
  mentioned if applicable?
- [ ] For RTI: is the correct fee amount stated?
- [ ] For consumer complaints: is the correct commission tier stated?

---

## Integration with the existing documents.py router

### For templates already in `_TEMPLATES` (fir_complaint, bail_application, legal_notice)

The existing `_template_prompt()` function generates a generic prompt. This
skill replaces that generic prompt with the document-specific prompt from
the relevant reference file. The API contract (`DraftRequest` → `DraftResponse`)
does not change.

To integrate, in `backend/api/routes/documents.py`, modify the `create_draft`
endpoint to check if the template_id has a skill-enhanced prompt available,
and use it if so:

```python
# In create_draft(), before calling litellm.acompletion:
from backend.agents.skills.legal_drafting import get_skill_prompt
skill_prompt = get_skill_prompt(request.template_id, request.fields, jurisdiction)
prompt = skill_prompt if skill_prompt else _template_prompt(template, request.fields, request.include_citations)
```

### For new templates (rti_application, consumer_complaint)

Add these entries to the `_TEMPLATES` list in documents.py. See each reference
file for the exact field definitions to use. The `access_roles` for RTI and
consumer complaints should include `citizen` — these are citizen-facing documents.

### Language handling

The existing system supports the `language` field in `DraftRequest`. For
non-English drafts, the document structure and headings should remain in the
original language of that document type (most Indian court documents use English
headings even in regional language versions), but the narrative sections can
be in the user's preferred language. The Sarvam AI translation in
`backend/api/routes/translate.py` handles the final translation step.

---

## What to do when something goes wrong

**User wants a document this skill does not support:** Name the document they
need, explain it is not in this version, and offer the closest available
alternative. Do not attempt to generate an unsupported document type by
improvising.

**Jurisdiction is ambiguous:** Ask one clear question. Do not assume.

**User provides conflicting information** (e.g., incident in 2023 but wants
IPC sections): Flag the conflict explicitly. For incidents before July 1 2024,
IPC/CrPC still applies. For incidents after July 1 2024, BNS/BNSS/BSA applies.
This distinction is legally critical and must be stated in the document.

**Citation verification fails:** The CitationVerificationTool in the existing
pipeline will catch incorrect section numbers. Trust it. If a section comes back
NOT_FOUND, use the correct section from the StatuteNormalizationTool output.

---

## Reference files — when to read each

Read reference files on demand, not all at once:

- `references/fir_draft.md` — Only when template_id is `fir_complaint`
- `references/bail_application.md` — Only when template_id is `bail_application`
- `references/legal_notice.md` — Only when template_id is `legal_notice`
- `references/rti_application.md` — Only when template_id is `rti_application`
- `references/consumer_complaint.md` — Only when template_id is `consumer_complaint`
- `references/jurisdiction_rules.md` — When the user's jurisdiction introduces
  questions not answered in the document-specific reference file. Read this
  as a supplement, not instead of the document-specific file.
