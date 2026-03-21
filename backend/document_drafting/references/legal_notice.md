# Legal Notice Reference

## Two distinct types — determine which applies first

Legal notices in India fall into two fundamentally different categories that
require different handling. Identify which type applies before drafting.

### Type A: Notice to Government under CPC Section 80

The Code of Civil Procedure 1908, Section 80 requires that before filing
a civil suit against the Government of India, a State Government, or a
public officer acting in their official capacity, the plaintiff must serve
a notice on the relevant authority and wait **two calendar months** before
filing the suit.

The notice must contain:
- Name, description, and place of residence of the plaintiff
- Statement of cause of action
- Relief sought

Failure to give this notice, or filing the suit before the two-month period
expires, renders the suit liable to be dismissed. This is a mandatory
procedural step, not optional.

**Exception under Section 80(2):** Urgent matters (e.g., where delay would
cause irreparable harm) can seek court permission to file without notice or
before the two-month period. Note this exception in the document if the
situation is urgent.

### Type B: Private Party Legal Notice

Between private parties (individual to individual, company to individual,
individual to company), there is no mandatory statutory notice requirement
for most civil disputes. However, sending a legal notice:
- Creates a formal record of the demand
- May be required before invoking specific remedies (e.g., cheque
  dishonour under Negotiable Instruments Act Section 138 requires a
  specific 15-day demand notice before filing a complaint)
- Is required before some arbitration clauses are invoked
- Is professionally expected before filing most civil suits

**NI Act Section 138 notices are a special sub-type** with mandatory
content requirements and the 30-day filing window. If the user is dealing
with a bounced cheque, flag this and note the specific requirements.

---

## Required fields

| Field | Government Notice (Type A) | Private Party (Type B) |
|---|---|---|
| `sender_name` | Required | Required |
| `sender_address` | Required | Required |
| `receiver_name` | Ministry / Department / Officer name | Individual / Company name |
| `receiver_address` | Official address of Ministry or officer | Registered / last known address |
| `subject` | Required | Required |
| `cause_of_action` | What wrong was done, when | What wrong was done, when |
| `demand` | What relief is sought | What is being demanded |
| `notice_period_days` | 60 days (mandatory under CPC 80) | Typically 15-30 days |

**Optional but valuable:**
- `lawyer_name` and `bar_council_id` — Professional legitimacy
- `reference_number` — For tracking in correspondence
- Previous correspondence dates if any

---

## Jurisdiction notes

**For Type A — which authority to address:**
- Dispute with Union Government departments → Secretary of the relevant Ministry
- Dispute with a State Government → Chief Secretary of the State, or the
  relevant Department Secretary
- Dispute with a Public Sector Undertaking → Varies; check if PSU qualifies
  as "Government" under CPC Section 79-80
- Kerala State Government notices → Principal Secretary, [Department Name],
  Government of Kerala, Thiruvananthapuram — 695 001

**For Type B — which address to use:**
- For companies: Registered office address (from MCA portal, not branch office)
- For individuals: Last known residential address
- Service by registered post with acknowledgement due (RPAD) is strongly
  preferred to create a paper trail of delivery

---

## Document structure

```
[LAWYER LETTERHEAD — if sent through advocate]
[OR: NOTICE FROM THE DESK OF (SENDER NAME) — if sent personally]

Reference No.: [REFERENCE NUMBER]
Date: [DATE]

LEGAL NOTICE

To,
[RECEIVER NAME]
[DESIGNATION — if Type A]
[FULL POSTAL ADDRESS]

[For Type A add:]
(Notice under Section 80 of the Code of Civil Procedure, 1908)

Sub: Legal Notice for [BRIEF SUBJECT — e.g., "Recovery of Security Deposit"
     / "Wrongful Termination" / "Non-payment of dues"]

Sir/Madam,

Under the instructions of and on behalf of my client, [CLIENT NAME], aged
[AGE], [Son/Daughter/Wife] of [PARENT/SPOUSE NAME], residing at [ADDRESS]
(hereinafter referred to as "my client"), I address you this legal notice
as follows:

1. BRIEF BACKGROUND:
[2-3 sentences establishing the relationship between the parties and the
 context of the dispute. E.g., "My client entered into an agreement with
 you dated [DATE] for [SUBJECT OF AGREEMENT]."]

2. ACTS OF OMISSION / COMMISSION:
[Numbered paragraphs, one per grievance. Each paragraph: what happened,
 on what date, what document or communication supports this. Factual only.
 No legal argument in this section.]

3. LEGAL POSITION:
[The legal basis for the claim. Which law applies. What obligation the
 addressee has violated. For Type A: which specific right or entitlement
 is being enforced. For NI Act 138: state the dishonour, the cheque details,
 the bank name, the amount, and the date of dishonour.]

4. DEMAND:
My client hereby demands that within [NOTICE PERIOD] days from the date of
receipt of this notice, you shall:

(a) [Specific demand 1]
(b) [Specific demand 2 if any]
(c) [Any other specific relief]

[For Type A — add:]
Please note that this notice is being served upon you as required under
Section 80(1) of the Code of Civil Procedure, 1908. My client shall be
constrained to initiate appropriate legal proceedings against you before the
competent court for recovery of damages, costs, and all other reliefs
available in law, after the expiry of two calendar months from the date of
service of this notice, if the aforesaid demands are not complied with.

[For Type B — add:]
In the event you fail to comply with the above demands within the stipulated
period, my client shall be constrained to initiate appropriate legal
proceedings before the competent forum/court, including for recovery of the
principal amount, interest, damages, and legal costs, without any further
notice to you.

Yours truly,

[ADVOCATE NAME]
Advocate — Bar Council of [STATE] Enrolment No. [NUMBER]
[ADDRESS]
[CONTACT / EMAIL]

For and on behalf of: [CLIENT NAME]

---
DRAFT ONLY — NOT LEGAL ADVICE. This document requires review by a qualified
lawyer before filing or use.
```

---

## LLM prompting guidance

For the cause of action section, instruct the LLM:

```
Draft the cause of action paragraphs for an Indian legal notice. Write in
formal legal English. Each grievance gets a separate numbered paragraph.
State facts precisely — amounts in figures (write Rs. 1,50,000 not "one
and a half lakh"), dates in full (1st January 2025), parties by full name
(not "the company" or "they"). Do not use threatening language — legal
notices are formal communications, not threats. The tone should be firm
but professional. Do not speculate about the addressee's motives.
If the user has mentioned specific documents (agreements, invoices, cheques),
reference them by their identifier if available.
```

---

## Common mistakes to avoid

1. Sending a Type A government notice to the wrong authority
   (must be the Secretary of the relevant Ministry / Department)
2. Filing suit before the 60-day period expires for Type A notices
3. Not serving by RPAD — oral or email notice alone is insufficient
   evidence for court purposes in most matters
4. Using threatening or abusive language — this can itself create
   legal liability
5. For NI Act 138 bounced cheque cases: missing the 30-day filing
   deadline after the 15-day demand notice period expires
6. Not specifying the exact amount claimed with a breakdown
7. Addressing the notice to a branch office instead of the registered
   office for companies
