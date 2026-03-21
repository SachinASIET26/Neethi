# Jurisdiction Rules Reference

## When to read this file

Read this file as a **supplement** when the document-specific reference file
does not fully answer a jurisdiction question. This is not a comprehensive
guide — it covers the jurisdictional questions most likely to arise when
drafting the five supported templates for Neethi AI's primary user base
(Kerala + central government matters).

---

## The fundamental rule about jurisdiction in Neethi AI

The system serves users across India but has its strongest ground truth for
Kerala and central government documents. For other states:

1. The **central law** version of a document is always the safe default
2. State-specific variations should be flagged as "please verify locally"
3. Do not invent state-specific rules — flag uncertainty honestly

---

## Kerala-specific rules for the five templates

### FIR / Police Complaint in Kerala

- Kerala Police Act 2011 applies alongside BNSS
- Language: Complaints can be filed in Malayalam — the police must accept them
- Kerala police station hierarchy: Beat Officer → Station House Officer →
  Circle Inspector → Dy. SP → SP → DIG → IG
- Women's complaints: Kerala Police has Women Helpline (1091) and Women's
  Police Stations in major districts — recommend these for domestic violence,
  sexual harassment, and women-specific offences
- Human Rights Commission: For complaints against police excess, file before
  the Kerala Human Rights Commission, Thiruvananthapuram, in addition to the
  regular complaint

### Bail Applications in Kerala

- Kerala High Court has a single bench at Ernakulam (Kochi)
  Full address: Kerala High Court, High Court Road, Ernakulam — 682 031
- Sessions Courts: One per district (14 districts in Kerala as of 2024)
- Fast Track Special Courts for POCSO matters exist in each district
- Kerala Legal Services Authority (KeLSA) at Ernakulam provides free legal
  aid services — relevant when the bail applicant cannot afford legal
  representation. The SKILL should flag this for citizens.

### Legal Notices in Kerala

- Kerala-based government departments: Address to the Principal Secretary,
  [Department], Government of Kerala, Secretariat, Thiruvananthapuram — 695 001
- Local Self Government (Panchayat / Municipality / Corporation) disputes:
  The Kerala Municipality Act 1994 and Kerala Panchayati Raj Act 1994 apply;
  notice to the Secretary of the relevant LSG body
- Landlord-tenant disputes in Kerala: The Kerala Buildings (Lease and Rent
  Control) Act 1965 is the primary law — NOT the Transfer of Property Act.
  Eviction notices and rent-related notices must comply with the KBLRC Act.
  This is a significant departure from general law and means a legal notice
  for Kerala tenancy matters is **not** the same as a general legal notice.
  Flag this clearly — do not draft a TPA-based notice for a Kerala tenancy
  dispute without flagging the KBLRC Act issue.

### RTI in Kerala

- Kerala RTI portal: crd.kerala.gov.in
- Fee: Rs. 10 by court fee stamp (commonly), or as specified by the department
- State Information Commission: Kerala State Information Commission,
  Thiruvananthapuram — 695 001, Phone: 0471-2517801
- For Kerala PSUs (KSEB, KSRTC, Kerala Water Authority, etc.): The Kerala
  State Public Information Commission has jurisdiction
- For Panchayat / Municipality RTI: Filed with the Secretary of that body
  as PIO, appeal to District Collector as First Appellate Authority

### Consumer Complaints in Kerala

District Consumer Disputes Redressal Commissions exist in all 14 districts.
The most frequently used:

| District | Commission Location |
|---|---|
| Ernakulam | Consumer Disputes Redressal Commission, Ernakulam, Kochi |
| Thiruvananthapuram | Consumer Disputes Redressal Commission, Thiruvananthapuram |
| Kozhikode | Consumer Disputes Redressal Commission, Kozhikode |
| Thrissur | Consumer Disputes Redressal Commission, Thrissur |

State Consumer Commission: Kerala State Consumer Disputes Redressal Commission,
Thiruvananthapuram — for claims above Rs. 50 lakhs.

---

## Language considerations across templates

**English is universally acceptable** in all Indian courts and government
offices for the five supported templates.

**Regional language rights:**
- RTI applications: Can be in Malayalam for Kerala departments (RTI Act
  Section 6(1) — "in English or Hindi or in the official language of the area")
- Police complaints: Can be in Malayalam in Kerala
- Consumer forums: Complaints can be in regional language; the commission
  may require translation for certain purposes

**The Sarvam AI integration in Neethi AI** handles translation. When a user
wants a document in Malayalam, generate the English version first (more
reliable legal terminology), then translate through Sarvam, and flag that
legal terminology in the translated version should be verified before filing.

---

## Incidents involving dates around July 1, 2024

This is the transition date when BNS/BNSS/BSA replaced IPC/CrPC/IEA.
The rule is:

- Offence committed **before** July 1, 2024 → prosecuted under IPC/CrPC/IEA
- Offence committed **on or after** July 1, 2024 → prosecuted under BNS/BNSS/BSA
- Proceedings that were **ongoing** on July 1, 2024 → continue under the old law

For documents dated in 2025 but relating to incidents in 2023-24, always
check the incident date before deciding which law to cite. This is the
most common source of error in automated legal drafting for this period.

---

## Fee structures — quick reference

| Document | Central | Kerala State |
|---|---|---|
| RTI application | Rs. 10 (IPO/DD/online) | Rs. 10 (court fee stamp/as specified) |
| Consumer complaint | Varies by claim amount (see Rules 2020 Schedule) | Same — central rules apply |
| FIR / Police complaint | Free | Free |
| Bail application | Court fee as per schedule | As per Kerala Court Fees Act |
| Legal notice | No prescribed fee (lawyer's professional fee) | Same |

---

## When you genuinely do not know the jurisdiction-specific rule

Say so. Write in the document:

```
[NOTE: The specific procedural requirements for [jurisdiction] should be
verified with a local advocate or directly with the relevant authority
before filing. The above draft is based on the central law / general
practice and may require modification for local requirements.]
```

This is honest, helpful, and legally defensible. Inventing jurisdiction-
specific rules is not.
