# Bail Application (Regular) Reference

## Statutory basis

Regular bail (post-arrest bail) is governed by the Bharatiya Nagarik
Suraksha Sanhita 2023, Section 480. This replaced the Code of Criminal
Procedure 1973, Section 437 (Magistrate bail) and Section 439 (Sessions
Court / High Court bail).

**Critical distinction from anticipatory bail:** Section 480 applies after
arrest. Anticipatory bail (pre-arrest) is under BNSS Section 482. The
existing documents.py router has a separate template for anticipatory bail
(`anticipatory_bail`). This reference file covers ONLY Section 480 regular
bail.

**THE CRITICAL FALSE FRIEND:**
BNSS 438 ≠ CrPC 438. BNSS 438 is Revision Powers (completely different).
CrPC 438 (Anticipatory Bail) maps to BNSS 482.
CrPC 439 (Special bail powers) maps to BNSS 483.
The system's adversarial assertions guard against this, but document
generation must also get this right.

---

## Court hierarchy for bail — determines addressee

This matters enormously for the document. Use the `triable_by` field from
BNSS Schedule I (already in `backend/db/seed_data/bnss_schedule_1.json`):

| triable_by | First bail application goes to |
|---|---|
| `Any Magistrate` | Chief Judicial Magistrate or Judicial Magistrate First Class |
| `Magistrate First Class` | Chief Judicial Magistrate |
| `Court of Sessions` | Sessions Judge or Additional Sessions Judge |

For Sessions Court-triable offences, the first application goes to the
Sessions Court. If refused there, the next application goes to the High Court.
The application must state which court it is addressed to and must not be filed
in the wrong court — it will be returned.

**Kerala specific courts:**
- Ernakulam: Court of the Sessions Judge, Ernakulam
- Thiruvananthapuram: Court of the Sessions Judge, Thiruvananthapuram
- For Kerala High Court bail: Kerala High Court, Ernakulam (jurisdiction
  over all of Kerala — only one High Court)

---

## Required fields

| Field | Notes |
|---|---|
| `accused_name` | Exact name as in FIR |
| `fir_number` | FIR No. / Case No. |
| `police_station` | Full name and district |
| `offence_sections` | BNS sections — system must verify these |
| `date_of_arrest` | Must be stated |
| `current_custody` | Sub-jail / Central Jail and location |
| `court_name` | The exact court being approached |
| `grounds` | Why bail should be granted — see grounds guidance below |

**Optional but strongly recommended:**
- `previous_bail_history` — Has bail been applied for and rejected before? If yes, must disclose
- `surety_details` — Name, relationship, property details of the proposed surety
- `medical_grounds` — If the accused has health conditions justifying bail
- `supporting_case_law` — Relevant Supreme Court / High Court bail precedents

---

## Grounds for bail — the most legally important section

These grounds must be drafted carefully. Generic grounds are rejected.
The grounds must address the specific presumptions the court will apply.

For **bailable offences** (BNSS Section 478): bail is a right, not a
discretion. State this explicitly. The application is more of a compliance
form than an adversarial petition.

For **non-bailable offences** (BNSS Section 480): the court exercises
discretion. The grounds must address:

1. **Prima facie case:** Whether the evidence against the accused
   is strong or weak. This requires the lawyer's assessment of the FIR
   and chargesheet. Leave a placeholder if this information is not provided.

2. **Nature and gravity of accusation:** Acknowledge the offence sections
   and note whether they involve violence, economic offences, etc.

3. **Antecedents and criminal history:** First offender status if applicable.

4. **Flight risk:** Strong roots in the community — family, employment,
   property. No reason to flee.

5. **Tampering with evidence / influencing witnesses:** Why the accused
   will not tamper. Address this directly.

6. **Health and humanitarian grounds:** If applicable.

7. **Prolonged custody:** If the accused has been in custody for an
   extended period without chargesheet being filed or trial progressing.

**For NDPS, PMLA, POCSO, and serious offences:** These Acts impose
reverse burdens — the accused must prove entitlement to bail rather than
the prosecution proving grounds for refusal. The bail application for
these offences needs special handling that is outside the scope of this
version of the drafting skill. Flag this and recommend a lawyer.

---

## Document structure

```
IN THE COURT OF THE [SESSIONS JUDGE / CHIEF JUDICIAL MAGISTRATE / etc.]
[COURT LOCATION]

BAIL APPLICATION NO. _____ OF [YEAR]

IN THE MATTER OF:
FIR No. [FIR NUMBER] dated [FIR DATE]
Police Station: [POLICE STATION NAME], [DISTRICT]
Under Sections: [BNS SECTIONS]

APPLICANT/ACCUSED:
[ACCUSED NAME]
Age: [AGE] years
S/o D/o W/o: [FATHER/MOTHER/SPOUSE NAME]
Residing at: [FULL ADDRESS]
Presently lodged at: [JAIL NAME AND LOCATION]

APPLICATION FOR BAIL UNDER SECTION 480 OF THE BHARATIYA NAGARIK
SURAKSHA SANHITA, 2023

MOST RESPECTFULLY SHOWETH:

1. BRIEF FACTS OF THE CASE:
[Brief, objective statement of the FIR allegations — not the accused's
version. Just what the FIR says, in 3-5 sentences.]

2. DATE AND CIRCUMSTANCES OF ARREST:
The applicant was arrested on [DATE] by [POLICE STATION] in connection
with the above FIR. The applicant has been in custody since [DATE], a
period of [DURATION].

3. GROUNDS FOR BAIL:

(i) [Ground 1 — prima facie case weakness or bailable nature]

(ii) [Ground 2 — no flight risk, community roots]

(iii) [Ground 3 — no tampering risk]

(iv) [Ground 4 — any other specific ground]

4. PREVIOUS BAIL APPLICATIONS:
[Either: "No previous bail application has been filed in this matter."
 Or: Disclose previous applications, courts, and outcome. Non-disclosure
 of previous rejections is a serious ethical violation for advocates.]

5. SURETY:
The applicant is prepared to offer surety of Rs. [AMOUNT] and/or such
other conditions as this Hon'ble Court may deem fit.

PRAYER:
It is therefore most respectfully prayed that this Hon'ble Court may be
pleased to:

(a) Release the applicant on bail under Section 480 of the BNSS, 2023
    on such terms and conditions as this Hon'ble Court may deem just
    and proper;

(b) Pass such other and further orders as this Hon'ble Court may deem
    fit in the facts and circumstances of the case.

And for this act of kindness, the applicant as in duty bound shall ever pray.

Date: [DATE]
Place: [PLACE]

[ADVOCATE NAME]
[BAR COUNCIL ENROLMENT NUMBER]
[CONTACT]
Advocate for the Applicant

---
DRAFT ONLY — NOT LEGAL ADVICE. This document requires review by a qualified
lawyer before filing or use.
```

---

## LLM prompting guidance

For the grounds section, instruct the LLM:

```
You are drafting the grounds section of an Indian bail application on behalf
of an accused person's advocate. Each ground must be a numbered paragraph
with a specific legal argument — not a generic statement. Reference the
accused's actual circumstances provided. Do NOT fabricate family details,
employment, or property ownership if not provided by the user. Leave
[TO BE FILLED] placeholders instead. Where a legal principle is involved
(e.g., the right to bail for bailable offences), cite the specific BNSS
section. Do not cite IPC or CrPC for incidents after July 1 2024.
Grounds should be 2-4 sentences each. Avoid emotional pleading — Indian
courts prefer legal arguments over appeals to sympathy.
```

---

## Common mistakes to avoid

1. Filing in the wrong court — always match court to triable_by classification
2. Not disclosing previous bail rejections — this is an ethical violation
3. Generic grounds that do not address the specific offence
4. Citing BNSS 438 instead of BNSS 482 for anticipatory bail matters
5. Not converting custody duration to a specific number of days
6. Attempting to draft bail for NDPS/PMLA/POCSO without flagging
   the reverse burden provisions to the user
