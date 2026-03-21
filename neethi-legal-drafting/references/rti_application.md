# RTI Application Reference

## Statutory basis

The Right to Information Act 2005, Section 6(1) gives every citizen the
right to request information from a "public authority." The Act does not
prescribe a mandatory national form — a simple written or typed application
in English, Hindi, or the official language of the area is sufficient.

However, good practice — and some states' optional guidelines — suggest
a structured format that ensures all necessary information is present
and avoids the common rejection ground of "vague or unclear request."

**Who can file:** Any citizen of India. Non-citizens cannot file RTI.
BPL (Below Poverty Line) cardholders are exempt from fees.

---

## Central vs State — the most important distinction

**Central Government RTI:**
- Fee: Rs. 10 (by Indian Postal Order, DD, or online through RTI portal)
- Fee exemption: BPL cardholders (attach BPL card copy)
- Portal: rtionline.gov.in (recommended for central ministries)
- Response time: 30 days from receipt (or 48 hours if life/liberty is involved)
- First appeal: Same department, within 30 days of rejection
- Second appeal: Central Information Commission (CIC)

**Kerala State RTI:**
- Fee: Rs. 10 (by court fee stamp, DD, or as specified by department)
- Fee exemption: BPL cardholders (attach BPL card copy)
- Response time: 30 days from receipt
- First appeal: Designated Appellate Authority in the same department
- Second appeal: Kerala State Information Commission (KSIC), Thiruvananthapuram
- Kerala RTI portal: crd.kerala.gov.in (for Kerala departments)

**The PIO (Public Information Officer):**
Every public authority must designate a PIO. The application must be
addressed to the PIO of the specific department — not a generic
"Government of India" or "Government of Kerala." If the user does not
know the PIO, advise them to address it to "The Public Information
Officer, [Department Name], [Address]" — the department is obligated
to route it to the correct person.

---

## What can be requested — and what cannot

**Requestable:**
- Records, documents, memos, emails, reports
- Opinions, advice, press releases, circulars, orders
- Contract details, bid documents, tender information
- Status of pending applications, complaints, licenses
- Inspection of government records (physical inspection request)

**Exempt under Section 8:**
- Information affecting sovereignty / national security
- Information relating to ongoing investigations (to the extent disclosure
  would prejudice the investigation)
- Cabinet papers and deliberations
- Personal information with no public interest justification
- Third-party commercial secrets
- Fiduciary information

**Important phrasing guidance:** Vague requests ("send me all documents about
my case") are commonly rejected. Specific requests ("a certified copy of the
order dated [DATE] in File No. [NUMBER]") are harder to reject and easier to
comply with. The LLM should help the user make the request as specific as
possible.

---

## Required fields

| Field | Notes |
|---|---|
| `applicant_name` | Full legal name |
| `applicant_address` | For communication — must be complete |
| `applicant_contact` | Phone / email — not mandatory but useful |
| `target_department` | Specific department / ministry / office |
| `target_address` | Official address of the department |
| `information_sought` | The core of the application — be specific |
| `preferred_format` | Certified copy / inspection / electronic |
| `fee_payment_method` | IPO / DD / online / court fee stamp |

**Optional:**
- `bpl_card_number` — For fee exemption
- `urgency_grounds` — If life or liberty is involved (48-hour rule)
- `relevant_file_reference` — If the applicant already knows the file number

---

## Document structure

```
To,
The Public Information Officer,
[DEPARTMENT NAME],
[FULL OFFICIAL ADDRESS],
[CITY], [STATE] — [PIN CODE]

[For Kerala state departments:]
[Date]

APPLICATION UNDER THE RIGHT TO INFORMATION ACT, 2005

1. NAME OF THE APPLICANT: [FULL NAME]

2. ADDRESS FOR COMMUNICATION:
[FULL POSTAL ADDRESS]
Email (if any): [EMAIL]
Phone: [PHONE]

3. PARTICULARS OF INFORMATION SOUGHT:

[This is the most important section. Write each piece of information sought
as a separate numbered item. Be specific. Examples below:]

(i) [A certified copy of the file noting / order / sanction regarding
     [SUBJECT MATTER], bearing File No. [NUMBER] if known, for the period
     from [DATE] to [DATE].]

(ii) [The current status of my application dated [DATE] submitted to
      [OFFICE NAME] for [PURPOSE].]

(iii) [Action taken on complaint dated [DATE] filed by me with [DEPARTMENT]
       regarding [SUBJECT].]

[If inspection is requested:]
I also request permission to inspect the records relating to [SUBJECT] at
your office at a convenient date and time.

4. PERIOD TO WHICH INFORMATION RELATES:
[Specify the date range if applicable]

5. DETAILS OF FEE PAID:
Application fee of Rs. 10/- paid by:
[Indian Postal Order No. / DD No. / Online payment reference / Court fee
 stamp] dated [DATE], drawn on [BANK if DD] / issued at [POST OFFICE if IPO].

[OR if BPL:]
I am a Below Poverty Line cardholder and am exempted from payment of fees.
A copy of my BPL card No. [NUMBER] is enclosed.

[If life/liberty urgency applies:]
This information pertains to a matter involving life and liberty. I request
that this application be treated as urgent and information be provided within
48 hours as per Section 7(1) of the RTI Act, 2005.

6. STATEMENT:
I state that the information sought does not fall within the restrictions
contained in Section 8 of the RTI Act, 2005 and to the best of my knowledge
it pertains to your department.

Yours faithfully,

[APPLICANT SIGNATURE]
[APPLICANT NAME]
Date: [DATE]
Place: [PLACE]

Enclosures:
1. Fee payment [proof]
2. [BPL card copy if applicable]
3. [Any supporting documents]

---
DRAFT ONLY — NOT LEGAL ADVICE. This document requires review by a qualified
lawyer before filing or use.
```

---

## First appeal template (for rejection or non-response)

If no response is received within 30 days, or the response is unsatisfactory,
the first appeal goes to the Appellate Authority in the same department. It
must be filed within **30 days** of the deemed rejection or actual rejection.

```
To,
The First Appellate Authority,
[DEPARTMENT NAME],
[ADDRESS]

FIRST APPEAL UNDER SECTION 19(1) OF THE RIGHT TO INFORMATION ACT, 2005

1. Name of the Appellant: [NAME]
2. Address: [ADDRESS]
3. RTI Application No. / Reference No.: [NUMBER] dated [DATE]

4. GROUNDS OF APPEAL:
(a) [The PIO has not provided the information within the stipulated period
     of 30 days / has provided incomplete information / has wrongly denied
     information under Section 8.]

(b) [Specific ground for the appeal.]

5. RELIEF SOUGHT:
I pray that the Appellate Authority may:
(a) Direct the PIO to provide the information sought within 15 days;
(b) Impose penalty on the PIO for delay under Section 20 of the RTI Act.

[DATE AND SIGNATURE]
```

---

## LLM prompting guidance

For the information sought section, instruct the LLM:

```
Draft the information sought section of an Indian RTI application. Transform
the user's vague description of what they want into specific, actionable
information requests. Each item should be a separately numbered paragraph
that requests one type of information. Use the language of government record-
keeping: "certified copy", "file noting", "order sheet", "correspondence",
"inspection of records". Avoid emotional language. Make each request as
narrow and specific as possible — broad requests are commonly rejected as
being too wide or requiring disproportionate diversion of resources.
If the user wants "everything about" their case, break this down into:
the original application, any noting on the file, any communication sent,
any order passed, and the current status.
```

---

## Common mistakes to avoid

1. Not paying the correct fee or using an incorrect payment instrument
2. Addressing the application to a Minister or Chief Minister — it must
   go to the PIO, not elected officials
3. Requesting third-party personal information without clear public interest
   justification — will be rejected under Section 8(1)(j)
4. Making a single request that covers multiple departments — file separate
   applications to each department
5. Asking questions ("Why did you do X?") rather than requesting records
   ("A copy of the file noting dated X regarding decision Y")
6. Missing the 30-day window for first appeal
7. Using Kerala's portal for a central government department or vice versa
