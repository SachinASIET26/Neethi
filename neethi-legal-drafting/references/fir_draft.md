# FIR Draft / Written Complaint Reference

## Statutory basis

The First Information Report is governed by the Bharatiya Nagarik Suraksha
Sanhita 2023, Section 173. Key obligations under Section 173:
- The officer in charge of a police station **must** register every
  cognizable offence complaint as an FIR
- A free copy must be given to the complainant immediately
- If the officer refuses, the complainant can send the complaint directly
  to the Superintendent of Police under BNSS Section 173(4)
- Electronic filing (e-FIR) is now explicitly recognised under BNSS

**Important:** This is a **written complaint** that the citizen brings to the
police station to be converted into an FIR — not the FIR itself (which is a
police document). The distinction matters: the citizen writes a complaint; the
police register it as an FIR and assign it a number.

**Applicable criminal law:** For incidents on or after **1st July 2024**, cite
sections from the Bharatiya Nyaya Sanhita 2023 (BNS). For incidents **before**
1st July 2024, cite the Indian Penal Code 1860 (IPC). Both the incident date
and the filing date are relevant — do not conflate them.

---

## Required fields — do not generate without these

| Field | Why it matters | Placeholder if missing |
|---|---|---|
| `complainant_name` | Legal identity of complainant | Cannot be omitted |
| `complainant_address` | For service of notices | Cannot be omitted |
| `complainant_id_type` | Aadhaar / Voter ID / Passport | `[TO BE FILLED: ID proof type and number]` |
| `incident_date` | Determines IPC vs BNS | Cannot be omitted |
| `incident_time` | Establishes timeline | `[TO BE FILLED: approximate time]` |
| `incident_location` | Exact place of offence | Cannot be omitted |
| `accused_details` | Name, address, description | `[UNKNOWN — accused not identified]` |
| `incident_description` | Factual narrative | Cannot be omitted |
| `witnesses` | Names and addresses if any | `[None at this time]` |
| `offence_sections` | BNS/IPC sections | Skill supplies based on facts |

**Optional fields:**
- `evidence_list` — physical evidence, CCTV, documents, screenshots
- `police_station` — if known, include name and address
- `previous_complaints` — any prior reports filed

---

## Jurisdiction notes

**State of the police station:** Determines which state police's complaint
format is being used. The BNSS is central law, so the substantive content is
the same across states, but some states have their own police regulations that
add procedural requirements.

**Kerala specific:** The Kerala Police Act 2011 and the Kerala Police Regulations
apply. Complaints in Kerala can be filed in Malayalam — the police station is
required to accept complaints in the regional official language. If generating
for Kerala and the user's preferred language is Malayalam, note in the document
that the complainant can request a copy in Malayalam.

**Zero FIR:** Under BNSS Section 173(1), an FIR can be filed at **any** police
station regardless of where the incident occurred (this is the Zero FIR
provision, a new addition compared to old CrPC). The registering station then
transfers it to the station with territorial jurisdiction. If the incident
location is in a different district, flag this in the document.

---

## Section number guidance — most common offences

This is not exhaustive. Always verify through CitationVerificationTool.

| Offence | BNS Section (post July 2024) | IPC Section (pre July 2024) |
|---|---|---|
| Murder | 103 | 302 |
| Culpable homicide | 101 | 304 |
| Causing hurt | 115 | 323 |
| Grievous hurt | 117 | 325 |
| Assault | 131 | 352 |
| Robbery | 309 | 390 |
| Theft | 303 | 379 |
| Cheating | 318 | 420 — NOTE: BNS 420 does not exist |
| Criminal intimidation | 351 | 506 |
| Wrongful confinement | 127 | 342 |
| Domestic violence offences | Also invoke PWDVA 2005 separately |
| Sexual harassment | 75 | 354A |
| Stalking | 78 | 354D |
| Rape | 63–70 (split from IPC 376) | 376 |

**THE MOST DANGEROUS FALSE FRIEND in this system:**
BNS 302 = Uttering words wounding religious feelings.
BNS 103 = Murder.
Never cite BNS 302 for a murder complaint. The system's adversarial assertions
guard against this, but you must also guard against it in document drafting.

---

## Document structure

Generate the complaint in this exact order:

```
[POLICE STATION NAME AND ADDRESS]

Date: [DATE OF FILING]

Subject: Written Complaint under Section 173 of the Bharatiya Nagarik
         Suraksha Sanhita, 2023

To,
The Officer-in-Charge / Station House Officer,
[POLICE STATION NAME],
[DISTRICT], [STATE]

Respected Sir/Madam,

I, [COMPLAINANT NAME], aged [AGE] years, son/daughter/wife of [PARENT/SPOUSE
NAME], residing at [FULL ADDRESS], do hereby lodge the following complaint:

1. FACTS OF THE COMPLAINT:
[Chronological factual narrative of what happened. No legal arguments here.
Pure facts: who did what, when, where, to whom. First person. Past tense.
Specific dates, times, locations. Avoid emotional language — keep it factual.]

2. ACCUSED PERSONS:
[Full details of accused if known. If unknown, describe physical appearance,
vehicle number if any, any other identifying information.]

3. WITNESSES:
[Names and addresses of persons who witnessed the incident, if any.]

4. EVIDENCE:
[List of documentary or physical evidence available: photographs, screenshots,
medical certificates, CCTV footage location, etc.]

5. OFFENCES COMMITTED:
The acts of the accused as narrated above constitute offences punishable under:
[List applicable BNS/IPC sections with section title]
[Any other applicable special laws — POCSO, PWDVA, SC/ST Prevention of
 Atrocities Act, IT Act, as relevant]

6. RELIEF SOUGHT:
I, therefore, request your good office to:
(a) Register this complaint as an FIR under the relevant sections of law;
(b) Investigate the matter and take appropriate action against the accused;
(c) Provide me with a copy of the FIR as mandated under Section 173(2) of
    the Bharatiya Nagarik Suraksha Sanhita, 2023.

[If the incident occurred in a different district/state:]
(d) Transfer this complaint to [STATION NAME] having territorial jurisdiction
    over the place of occurrence, after registering as a Zero FIR under
    Section 173(1) of BNSS.

Yours faithfully,

[SIGNATURE]
[COMPLAINANT NAME]
[DATE]
[CONTACT NUMBER]

Enclosures:
[LIST ANY DOCUMENTS ATTACHED]

---
DRAFT ONLY — NOT LEGAL ADVICE. This document requires review by a qualified
lawyer before filing or use.
```

---

## LLM prompting guidance for this template

When generating the narrative section (section 1 above), instruct the LLM:

```
You are drafting section 1 of an Indian police complaint on behalf of the
complainant. Write ONLY what the complainant witnessed or experienced directly.
Use first person, past tense, precise dates and times. Do not use legal
conclusions like "the accused illegally" or "unlawfully" in the facts section —
save legal characterisation for section 5. Do not speculate about motive.
If any fact is uncertain, write "on or around [date]" or "approximately [time]".
The narrative should be clear enough that a police officer unfamiliar with the
case can understand exactly what happened from reading it once.
Aim for 150-300 words for a straightforward incident, more for complex cases.
```

---

## Common mistakes to avoid

1. Citing BNS sections for a pre-July 2024 incident — use IPC instead
2. Citing BNS 302 for murder — it is BNS 103
3. Leaving the accused section completely blank when some description
   is available (vehicle number, approximate age, location where seen)
4. Writing the facts section as if arguing a case — it is a factual report,
   not a legal brief
5. Omitting the free copy entitlement under BNSS 173(2) from relief sought
6. Not mentioning Zero FIR provision when incident location is outside the
   police station's territorial jurisdiction
