# Consumer Complaint Reference

## Statutory basis

Consumer complaints are governed by the Consumer Protection Act 2019 and
the Consumer Protection (Consumer Disputes Redressal Commissions) Rules 2020.
Rule 6 of the 2020 Rules prescribes Form 1 as the format for consumer
complaints before all three commission tiers.

**The official Form 1 is available at:** consumerhelpline.gov.in
Users should be directed to the official portal for the final filing, as
online filing is now mandatory for claims above Rs. 5 lakhs.

---

## Commission tier — determine first based on claim amount

This is the most important routing decision. Filing in the wrong forum
results in return of the complaint.

| Claim Amount | Commission | Where to file |
|---|---|---|
| Up to Rs. 50 lakhs | District Consumer Disputes Redressal Commission | District Consumer Forum in complainant's district |
| Rs. 50 lakhs to Rs. 2 crores | State Consumer Disputes Redressal Commission | State Commission in the state capital |
| Above Rs. 2 crores | National Consumer Disputes Redressal Commission | NCDRC, New Delhi |

**Kerala Districts:** The District Commission in each Kerala district is
called the "District Consumer Disputes Redressal Commission, [District Name]."
The State Commission for Kerala is at Thiruvananthapuram.

**Important:** The complaint can be filed where the complainant resides,
works, or where the cause of action arose — the complainant's choice,
not the opposite party's location. This is a significant advantage
compared to civil courts.

---

## Who can be a complainant and who can be an opposite party

**Complainant:** Must be a "consumer" — a person who has bought goods or
availed services for personal use (not for commercial resale or for
earning livelihood through commercial activity — though the 2019 Act
provides some relief to small traders).

**Opposite party:** Any person against whom the complaint is filed —
manufacturer, seller, service provider, e-commerce platform.

**E-commerce:** The 2019 Act explicitly includes e-commerce platforms and
mandates they are liable. If the dispute is with an Amazon seller or
Flipkart product, both the platform and the seller can be named as
opposite parties.

---

## Required fields

| Field | Notes |
|---|---|
| `complainant_name` | Full legal name |
| `complainant_address` | District and state determine which commission |
| `complainant_contact` | Phone and email |
| `opposite_party_name` | Company name exactly as registered |
| `opposite_party_address` | Registered office address preferred |
| `product_or_service` | What was purchased / what service was availed |
| `purchase_date` | Date of transaction |
| `amount_paid` | Exact amount with proof |
| `deficiency_description` | What went wrong — specific and factual |
| `relief_sought` | Replacement / refund / compensation — be specific |
| `total_claim_amount` | Determines which commission has jurisdiction |

**Optional but valuable:**
- `order_number` / `invoice_number` — Proof of purchase
- `complaint_reference` — Company's own complaint tracking number
- `earlier_correspondence` — Emails, chat transcripts with customer service
- `expert_opinion` — For product defect claims (e.g., motor vehicle defects)

---

## What constitutes a valid consumer complaint

The complaint must establish one or more of:
1. **Defect in goods** — any fault, imperfection, or shortcoming in quality,
   quantity, potency, purity, or standard required by law or contract
2. **Deficiency in service** — any fault, imperfection, shortcoming or
   inadequacy in quality, nature, or manner of performance of a service
3. **Unfair trade practice** — misleading advertisements, false representation
4. **Restrictive trade practice** — price manipulation, denial of warranty service
5. **Overcharging** — charging above the maximum retail price

**Time limitation:** Consumer complaints must be filed within **two years**
from the date the cause of action arose. If filing after this period, the
complaint must include an application for condonation of delay with reasons.

---

## Document structure (based on Form 1 under CPA 2019 Rules)

```
BEFORE THE [DISTRICT / STATE / NATIONAL] CONSUMER DISPUTES
REDRESSAL COMMISSION

[DISTRICT / STATE / LOCATION]

Consumer Complaint No. _____ of [YEAR]

IN THE MATTER OF:

[COMPLAINANT NAME]
[Age] years, [Son/Daughter/Wife] of [PARENT/SPOUSE]
[Full address]
Email: [EMAIL] | Phone: [PHONE]                    ...Complainant

VERSUS

[OPPOSITE PARTY NAME — e.g., XYZ Company Pvt. Ltd.]
Through its [Managing Director / Authorised Representative]
[Registered Office Address]                         ...Opposite Party

CONSUMER COMPLAINT UNDER SECTION 35 / 47 / 58 OF THE CONSUMER
PROTECTION ACT, 2019

MOST RESPECTFULLY SHOWETH:

1. BRIEF INTRODUCTION:
The complainant is a consumer as defined under Section 2(7) of the Consumer
Protection Act, 2019, having purchased [PRODUCT/AVAILED SERVICE] from the
opposite party on [DATE] for personal use, for a consideration of
Rs. [AMOUNT] (Rupees [AMOUNT IN WORDS]).

2. FACTS OF THE COMPLAINT:

[Numbered paragraphs, one fact per paragraph. Include:]
2.1 [Date and nature of purchase / service booking]
2.2 [What the opposite party promised / represented]
2.3 [What actually happened — the specific defect or deficiency]
2.4 [When the complainant first complained to the opposite party]
2.5 [The opposite party's response or failure to respond]
2.6 [Any further attempts to resolve the issue and their outcome]

3. CAUSE OF ACTION:
The cause of action arose on [DATE] when [specific triggering event].
The cause of action is continuing. / The cause of action is within the
period of limitation prescribed under the Consumer Protection Act, 2019.

4. DETAILS OF DOCUMENTS RELIED UPON:
(i) Invoice/Receipt dated [DATE] for Rs. [AMOUNT]
(ii) Email correspondence with opposite party dated [DATE]
(iii) [Complaint reference number/ticket from company]
(iv) [Photographs of defective product / Expert report if any]
(v) [Warranty card / Terms of service]

5. GROUNDS OF COMPLAINT:
The opposite party is liable on the following grounds:

(i) That there is a clear defect/deficiency as defined under Section 2(11)
    of the Consumer Protection Act, 2019 in the [goods/service] provided.

(ii) That the opposite party engaged in [unfair trade practice / false
     representation] in violation of Section 2(47) of the Act.

(iii) [Any other specific ground with the relevant section of CPA 2019]

6. RELIEF CLAIMED:

In view of the foregoing, the complainant most respectfully prays that
this Hon'ble Commission may be pleased to direct the opposite party to:

(a) [Primary relief — e.g., "Replace the defective product with a new
     functional unit of the same model" / "Refund Rs. [AMOUNT] paid by
     the complainant"]

(b) Pay compensation of Rs. [AMOUNT] for mental agony, harassment, and
    loss caused to the complainant.

(c) Pay Rs. [AMOUNT] towards the costs of this litigation.

TOTAL CLAIM: Rs. [TOTAL AMOUNT]

(d) Pass such other and further orders as this Hon'ble Commission may
    deem fit in the interest of justice.

7. JURISDICTION:
This Hon'ble [Commission tier] has jurisdiction to entertain this
complaint as the total claim amount is Rs. [AMOUNT], which [is within
/ exceeds] the pecuniary limit. The complainant resides within the
territorial jurisdiction of this Commission. [/ The cause of action
partly arose within the territorial jurisdiction of this Commission.]

VERIFICATION:
I, [COMPLAINANT NAME], do hereby verify that the contents of the above
complaint are true and correct to the best of my knowledge and belief.
No part of it is false and nothing material has been concealed.

Verified at [PLACE] on [DATE].

[SIGNATURE]
[COMPLAINANT NAME]

List of Enclosures:
1. Proof of purchase (Invoice / Receipt)
2. Correspondence with opposite party
3. [Other documents]

---
DRAFT ONLY — NOT LEGAL ADVICE. This document requires review by a qualified
lawyer before filing or use.
```

---

## LLM prompting guidance

For the facts section, instruct the LLM:

```
Draft the facts section of an Indian consumer complaint under the Consumer
Protection Act 2019. Write in numbered paragraphs, one fact per paragraph.
Start from the purchase or service booking, move chronologically through
what went wrong, then the complainant's attempts to get resolution.
Be specific: include dates, amounts, model numbers, order IDs, reference
numbers from company correspondence. Avoid emotional characterisation —
instead of "the company cheated me", write "the product delivered did not
match the specification advertised" or "the service was not provided despite
full payment." Indian consumer forums respond better to documented facts
than emotional appeals. If the user mentions a specific chat transcript
or email, incorporate the substance of it rather than quoting it in full.
```

---

## Common mistakes to avoid

1. Filing in the wrong commission tier based on the claim amount
2. Claiming a very large compensation amount without basis — stick to
   actual loss plus reasonable compensation for harassment
3. Not enclosing proof of purchase — without this, the complaint will fail
4. Filing against the wrong opposite party (e.g., filing against a delivery
   agent instead of the seller/manufacturer)
5. Missing the two-year limitation period without filing a condonation
   of delay application
6. Claiming commercial losses from a business purchase — CPA 2019 covers
   personal consumers, not businesses (with limited exceptions)
7. Not including the verification statement at the end — it is mandatory
