# Indian Legal Data Sources — Neethi AI Ingestion Guide

**Date:** 2026-02-27
**Purpose:** Priority-ordered list of Indian legal documents required to achieve
70–80% query coverage across all four user roles (Layman, Lawyer, Police, Advisor).
**Status Legend:** ✅ Indexed | ⚠️ Partial | ❌ Missing

---

## Coverage Goal by Role

| Role | Primary Query Categories | Coverage Target |
|------|--------------------------|-----------------|
| **Layman (Citizen)** | Tenant/property rights, consumer complaints, family disputes, FIR process, bail | 70% |
| **Lawyer** | Statutory text + commentary, procedure, evidence, IRAC analysis, SC precedents | 75% |
| **Police** | Criminal offences (BNS), procedure (BNSS), evidence (BSA), bail, FIR, custody | 80% |
| **Legal Advisor** | Corporate, contracts, arbitration, IT compliance, employment, succession | 70% |

---

## Part A — Statutes (Primary Priority)

### Tier 1: Critical — Blocks Common Queries Right Now

These are the statutes with the highest query volume that are currently absent from the database.
Ingesting these would resolve ~40% of current UNVERIFIED responses.

---

#### 1. Model Tenancy Act, 2021 (MTA 2021)

| Field | Value |
|-------|-------|
| **Sections** | 56 |
| **Domain** | Property / Tenancy |
| **Roles covered** | Layman, Lawyer, Advisor |
| **Query types** | Security deposit, eviction procedure, rent disputes, landlord obligations |
| **Status** | ❌ Not ingested |
| **Act code** | `MTA_2021` |
| **Official source** | Ministry of Housing & Urban Affairs — `mohua.gov.in` |
| **PDF download** | https://mohua.gov.in/upload/uploadfiles/files/ModelTenancyAct2021.pdf |
| **Why critical** | Security deposit is Neethi's most-tested civil query. Without MTA 2021, the system cannot answer it with statutes — falls back to SC precedents only. |

**Ingestion command (after downloading PDF):**
```bash
python backend/preprocessing/ingest_act.py \
  --pdf data/acts/MTA_2021.pdf \
  --act-code MTA_2021 \
  --act-name "Model Tenancy Act, 2021" \
  --year 2021 \
  --era civil_statutes \
  --domain civil_property
```

---

#### 2. Consumer Protection Act, 2019 (CPA 2019)

| Field | Value |
|-------|-------|
| **Sections** | 107 |
| **Domain** | Consumer |
| **Roles covered** | Layman, Lawyer, Advisor |
| **Query types** | Deficiency of service, product liability, consumer forum, e-commerce disputes, refund rights |
| **Status** | ❌ Not ingested |
| **Act code** | `CPA_2019` |
| **Official source** | Ministry of Consumer Affairs |
| **PDF download** | https://consumeraffairs.nic.in/sites/default/files/file-uploads/latestnews/CPA2019.pdf |
| **Why critical** | Consumer complaints are the #2 most common layman query category after tenancy. |

---

#### 3. Code of Civil Procedure, 1908 (CPC 1908)

| Field | Value |
|-------|-------|
| **Sections** | 158 (+ 51 Orders with Rules) |
| **Domain** | Civil Procedure |
| **Roles covered** | Lawyer, Advisor |
| **Query types** | Filing civil suit, jurisdiction, injunction, execution, appeals, limitation |
| **Status** | ❌ In acts table — 0 sections indexed |
| **Act code** | `CPC_1908` |
| **Official source** | India Code (official consolidated acts repository) |
| **PDF download** | https://www.indiacode.nic.in/bitstream/123456789/2189/1/AAA1908___05.pdf |
| **Sections to prioritize** | Orders 7 (Plaint), 8 (Written Statement), 39 (Injunction), 21 (Execution) |

---

#### 4. Hindu Succession Act, 1956 (HSA 1956)

| Field | Value |
|-------|-------|
| **Sections** | 30 |
| **Domain** | Family / Inheritance |
| **Roles covered** | Layman, Lawyer |
| **Query types** | Daughters' inheritance rights, ancestral property, joint family property, intestate succession |
| **Status** | ❌ In acts table — 0 sections indexed |
| **Act code** | `HSA_1956` |
| **Official source** | India Code |
| **PDF download** | https://www.indiacode.nic.in/bitstream/123456789/1603/1/A1956-30.pdf |
| **Note** | HSA was amended in 2005 (gender equality in coparcenary rights) — the PDF must be the 2005-amended version. |

---

### Tier 2: High Priority — Covers Specific Practice Areas

#### 5. State Rent Control Acts

State-specific tenancy laws are critical because India's tenancy law is concurrent (both central MTA 2021 and state laws apply). The three highest-volume states:

| State | Act | Sections | PDF Source |
|-------|-----|----------|------------|
| **Maharashtra** | Maharashtra Rent Control Act, 1999 | ~60 | `maharashtra.gov.in` / IndiaCode |
| **Delhi** | Delhi Rent Act, 1958 | ~58 | `indiacode.nic.in` |
| **Karnataka** | Karnataka Rent Act, 1999 | ~40 | `karnataka.gov.in` |

**Act codes:** `MRC_1999_MH`, `DRA_1958_DL`, `KRA_1999_KA`

**India Code consolidated source:**
- Maharashtra: https://www.indiacode.nic.in/bitstream/123456789/6545/1/maharashtra_rent_control_act_1999.pdf
- Delhi: https://www.indiacode.nic.in/bitstream/123456789/5082/1/delhi_rent_act_1958.pdf

---

#### 6. Protection of Children from Sexual Offences Act, 2012 (POCSO)

| Field | Value |
|-------|-------|
| **Sections** | 46 |
| **Domain** | Criminal (Specialised) |
| **Roles covered** | Police, Lawyer |
| **Query types** | Child sexual abuse procedure, mandatory reporting, special court, POCSO FIR |
| **Status** | ❌ Not ingested |
| **Act code** | `POCSO_2012` |
| **PDF download** | https://www.indiacode.nic.in/bitstream/123456789/2079/1/200032.pdf |
| **Why important for police** | POCSO creates mandatory duties for police (Section 19: mandatory report within 24h). Without it, police role responses on child protection cases are incomplete. |

---

#### 7. Prevention of Corruption Act, 1988 (PCA 1988)

| Field | Value |
|-------|-------|
| **Sections** | 31 |
| **Domain** | Criminal (Anti-corruption) |
| **Roles covered** | Lawyer, Police |
| **Query types** | Bribery, public servant offences, disproportionate assets, sanction for prosecution |
| **Status** | ❌ Not ingested |
| **Act code** | `PCA_1988` |
| **PDF download** | https://www.indiacode.nic.in/bitstream/123456789/1474/1/198849.pdf |

---

#### 8. Negotiable Instruments Act, 1881 (NIA 1881)

| Field | Value |
|-------|-------|
| **Sections** | 138 |
| **Domain** | Civil / Banking |
| **Roles covered** | Lawyer, Advisor, Layman |
| **Query types** | Cheque bounce (s.138), dishonour, notice period, magistrate complaint, compounding |
| **Status** | ❌ Not ingested |
| **Act code** | `NIA_1881` |
| **PDF download** | https://www.indiacode.nic.in/bitstream/123456789/2186/1/AAA1881___026.pdf |
| **Why important** | Cheque bounce cases (s.138) are the single highest-volume category in Indian trial courts — ~3.5 million pending cases. |

---

### Tier 3: Medium Priority — Completes Coverage

#### 9. Information Technology Act, 2000 (IT Act)

| Field | Value |
|-------|-------|
| **Sections** | 94 |
| **Domain** | Corporate / Cyber |
| **Roles covered** | Lawyer, Advisor |
| **Query types** | Cybercrime (s.66), data protection, digital signatures, electronic evidence, IT intermediary rules |
| **Status** | ❌ Not ingested |
| **Act code** | `ITA_2000` |
| **PDF download** | https://www.indiacode.nic.in/bitstream/123456789/1999/3/200021.pdf |

---

#### 10. IPC 1860 — Section Text (Repealed but needed for pre-July 2024 cases)

| Field | Value |
|-------|-------|
| **Sections** | 511 |
| **Domain** | Criminal Substantive (historical) |
| **Roles covered** | Lawyer, Police (for FIR involving pre-2024 offences) |
| **Status** | ⚠️ In acts table, **repealed**, 0 sections indexed |
| **Act code** | `IPC_1860` |
| **PDF download** | https://www.indiacode.nic.in/bitstream/123456789/2263/3/AAA1860___045.pdf |
| **Why important** | All FIRs filed before July 1, 2024 used IPC sections. SC judgments on cases from 2015–2023 cite IPC sections. Without IPC text, the system cannot explain what "IPC 302" or "IPC 376" means in the context of those cases. |

---

#### 11. CrPC 1973 — Section Text (Repealed but needed for context)

| Field | Value |
|-------|-------|
| **Sections** | 484 |
| **Domain** | Criminal Procedure (historical) |
| **Act code** | `CrPC_1973` |
| **PDF download** | https://www.indiacode.nic.in/bitstream/123456789/2388/3/AAA1974___002.pdf |
| **Why important** | BNSS transitional provisions frequently cross-reference CrPC sections. Bail orders from 2023–2024 cite both CrPC and BNSS. |

---

#### 12. Hindu Marriage Act, 1955 (HMA 1955) — Complete Indexing

| Field | Value |
|-------|-------|
| **Sections** | 30 total — 19 currently indexed, **11 missing** |
| **Act code** | `HMA_1955` |
| **Fix** | Run `scripts/reindex_unindexed_sections.py` first (recovers ~7), then re-ingest from PDF if still incomplete |
| **PDF download** | https://www.indiacode.nic.in/bitstream/123456789/2199/3/AAA1955___025.pdf |

---

#### 13. Transfer of Property Act, 1882 (TPA 1882) — Complete Indexing

| Field | Value |
|-------|-------|
| **Sections** | 13 currently missing from Qdrant |
| **Act code** | `TPA_1882` |
| **Fix** | Run `scripts/reindex_unindexed_sections.py` (recovers ~13 from existing PostgreSQL) |

---

#### 14. Indian Contract Act, 1872 (ICA 1872) — Complete Indexing

| Field | Value |
|-------|-------|
| **Sections** | 18 currently missing from Qdrant |
| **Act code** | `ICA_1872` |
| **Fix** | Run `scripts/reindex_unindexed_sections.py` (recovers ~18 from existing PostgreSQL) |

---

### Tier 4: Role-Specific Coverage Completers

#### Police Role — Additional Acts

| Act | Sections | Act Code | PDF Source |
|-----|----------|----------|------------|
| Arms Act, 1959 | 45 | `ARMS_1959` | indiacode.nic.in |
| Narcotic Drugs & Psychotropic Substances Act (NDPS), 1985 | 83 | `NDPS_1985` | indiacode.nic.in |
| Maharashtra Police Act, 1951 (State-specific) | 162 | `MPA_1951_MH` | maharashtra.gov.in |
| Unlawful Activities (Prevention) Act (UAPA), 1967 | 52 | `UAPA_1967` | indiacode.nic.in |

#### Legal Advisor Role — Additional Acts

| Act | Sections | Act Code | PDF Source |
|-----|----------|----------|------------|
| Companies Act, 2013 | 470 | `CA_2013` | mca.gov.in |
| GST Act (CGST), 2017 | 174 | `CGST_2017` | cbic.gov.in |
| Real Estate (Regulation) Act (RERA), 2016 | 92 | `RERA_2016` | mohua.gov.in |
| Insolvency & Bankruptcy Code (IBC), 2016 | 255 | `IBC_2016` | ibbi.gov.in |
| Sexual Harassment at Workplace Act (POSH), 2013 | 30 | `POSH_2013` | indiacode.nic.in |
| Intellectual Property Rights (Trade Marks Act, 1999) | 159 | `TMA_1999` | ipindia.gov.in |

#### Family Law — Additional Acts

| Act | Sections | Act Code | PDF Source |
|-----|----------|----------|------------|
| Muslim Personal Law (Shariat) Application Act, 1937 | 6 | `MLA_1937` | indiacode.nic.in |
| Muslim Women (Protection of Rights on Divorce) Act, 1986 | 8 | `MWPRD_1986` | indiacode.nic.in |
| Guardians and Wards Act, 1890 | 50 | `GWA_1890` | indiacode.nic.in |
| Maintenance and Welfare of Parents & Senior Citizens Act, 2007 | 32 | `MWPSCA_2007` | indiacode.nic.in |
| Domestic Violence Act, 2005 (Protection of Women from DV) | 37 | `PWDVA_2005` | indiacode.nic.in |

---

## Part B — Supreme Court Judgments (SC Precedents)

### Current State
- **Indexed:** 1,636 judgments (37,965 chunks) covering 2023–2024 only
- **Domain tagging:** 95% blank — run `scripts/tag_sc_judgment_domains.py` immediately
- **Indian Kanoon URLs:** 0% populated — citation links broken

### Priority Expansion Plan

#### B1. Landmark Judgments (Pre-2015, Curated List)

These are binding precedents cited in nearly every legal matter. ~50 judgments, ~1,000 chunks.

| Case | Year | Citation | Domain | Why Important |
|------|------|----------|--------|---------------|
| Maneka Gandhi v. Union of India | 1978 | (1978) 1 SCC 248 | Constitutional | Article 21 expanded — right to life & personal liberty |
| Vishaka v. State of Rajasthan | 1997 | (1997) 6 SCC 241 | POSH / Employment | Sexual harassment at workplace guidelines |
| Shreya Singhal v. Union of India | 2015 | (2015) 5 SCC 1 | IT / Constitutional | IT Act s.66A struck down — free speech |
| K.S. Puttaswamy v. Union of India | 2017 | (2017) 10 SCC 1 | Constitutional | Right to privacy as fundamental right |
| Joseph Shine v. Union of India | 2018 | (2018) 2 SCC 189 | Criminal | Adultery (IPC 497) struck down |
| Arnesh Kumar v. State of Bihar | 2014 | (2014) 8 SCC 273 | Criminal Procedure | Guidelines on arrest under s.498A — police critical |
| Dilip S. Dahanukar v. Kotak Mahindra | 2007 | (2007) 6 SCC 528 | NI Act | Cheque bounce — cannot imprison without notice |
| M/s Surya Dev Rai v. Ram Chander Rai | 2003 | (2003) 6 SCC 675 | Civil Procedure | Revision jurisdiction — CPC |
| T.N. Godavarman v. Union of India | 1997 | (1997) 2 SCC 267 | Constitutional / Environment | Forest protection rights |
| NALSA v. Union of India | 2014 | (2014) 5 SCC 438 | Constitutional | Transgender persons' rights |

**Source for landmark PDFs:** Indian Kanoon (indiankanoon.org) — use API or web scrape
**Alternative:** Supreme Court of India website (sci.gov.in) — case status + judgment PDFs

---

#### B2. High-Volume Recent Judgments (2019–2022)

~3,000 judgments across 4 years. Priority domains:

| Domain | Expected Volume | Collection Impact |
|--------|-----------------|-------------------|
| Criminal bail (BNSS/CrPC) | ~600 judgments | Police + Lawyer |
| Property disputes | ~400 judgments | Layman + Lawyer |
| Consumer/commercial | ~300 judgments | Advisor |
| Family law (divorce, custody) | ~250 judgments | Layman + Lawyer |
| Labour / service matters | ~200 judgments | Advisor |

**Download approach:**
```python
# Indian Kanoon API (requires API key from indiankanoon.org)
GET https://api.indiankanoon.org/search/?formInput=criminal+bail&pagenum=0
# Returns judgment metadata + PDF links
# Batch download 2019-2022 judgments by domain

# Supreme Court eCourts
# https://main.sci.gov.in/judgments
# Provides year-wise PDF downloads
```

---

#### B3. High Court Judgments (HC Case Law)

The `case_law` Qdrant collection is currently empty. High Courts produce jurisdiction-specific
precedents that are binding within their state — critical for layman and police queries where
state law applies.

**Priority HCs by query volume:**

| High Court | Jurisdiction | Priority Domains |
|------------|--------------|------------------|
| Bombay HC | Maharashtra, Goa | Tenancy (MRCA), cheque bounce, corporate |
| Delhi HC | Delhi | Tenancy (DRA), IT Act, service matters |
| Allahabad HC | Uttar Pradesh | Criminal, property (UP Zamindari Act) |
| Madras HC | Tamil Nadu, Puducherry | Family (Hindu law), property |
| Karnataka HC | Karnataka | Tenancy (KRA), IT (Bangalore tech cases) |

**Source:** eCourts judgment portal — https://districts.ecourts.gov.in/

---

## Part C — Procedural Documents

These are not statutes but critical for police and citizen queries.

| Document | Type | Covers | Source |
|----------|------|--------|--------|
| FIR Filing Guidelines (BNSS procedural circulars) | Govt circular | Police procedure | State police portals |
| Supreme Court Standard Operating Procedures | SOP | Court filing, e-filing | sci.gov.in |
| Consumer Forum Filing Guidelines | Govt document | NCDRC procedure | ncdrc.nic.in |
| RERA Complaint Procedure | Govt document | Real estate disputes | rera.gov.in (state-wise) |
| Legal Aid Authority (NALSA) Booklets | Public awareness | Citizen rights | nalsa.gov.in |

---

## Part D — Ingestion Method

### D1. Current Pipeline (Use for Standard Statutory PDFs)

```bash
# Standard act ingestion via existing pipeline
cd /teamspace/studios/this_studio/Phase2

# Step 1: Download PDF to data/acts/
wget -O data/acts/MTA_2021.pdf "https://mohua.gov.in/upload/uploadfiles/files/ModelTenancyAct2021.pdf"

# Step 2: Run ingestion pipeline
python backend/preprocessing/ingest_act.py \
  --pdf data/acts/MTA_2021.pdf \
  --act-code MTA_2021 \
  --act-name "Model Tenancy Act, 2021" \
  --year 2021 \
  --era civil_statutes \
  --domain civil_property \
  --batch-size 16

# Pipeline steps: PDF extraction → section parsing → PostgreSQL insert → Qdrant indexing
# Human review queue: sections with confidence < 0.7 queued for approval
```

### D2. SC Judgment Ingestion (Existing Mechanism + Extensions Needed)

The existing SC judgment ingestion pipeline (`backend/preprocessing/sc_judgment_ingester.py`)
handles eCourts-format metadata. For expansion:

```python
# Indian Kanoon API batch ingestion
# Requires IK API key (get from indiankanoon.org/api)
python scripts/ingest_sc_judgments_ik.py \
  --api-key $IK_API_KEY \
  --year-range 2019-2022 \
  --domains "criminal,civil,property,family" \
  --max-judgments 3000
```

After ingestion, **always run domain tagging:**
```bash
python scripts/tag_sc_judgment_domains.py
# Tags civil/criminal/constitutional from case_no prefix patterns
```

### D3. Chunking Strategy by Document Type

| Document Type | Chunking Method | Chunk Size | Overlap |
|---------------|----------------|------------|---------|
| Short statutory sections (< 400 tokens) | Single chunk | Full section | None |
| Long statutory sections (400–1200 tokens) | Split at subsection | 400 tokens | 50 tokens |
| Very long sections (> 1200 tokens) | Overlapping windows | 600 tokens | 100 tokens |
| Definitions sections (s.2 of any act) | Granular per-definition | 1 definition | None |
| SC judgment text | Semantic chunks | 500 tokens | 75 tokens |
| HC judgment text | Semantic chunks | 400 tokens | 50 tokens |

### D4. Metadata Schema for New Acts

Every ingested act must populate all required Qdrant payload fields:

```python
{
    # Required
    "act_code": "MTA_2021",
    "act_name": "Model Tenancy Act, 2021",
    "section_number": "7",
    "section_title": "Deposit to be paid by tenant",
    "legal_text": "...",           # Full section text
    "era": "civil_statutes",       # NOT naveen_sanhitas (MTA is not a Sanhita)
    "legal_domain": "civil_property",

    # Quality
    "extraction_confidence": 0.95,
    "is_offence": False,

    # Hierarchy
    "chapter_title": "Chapter II — Tenancy Agreement",
    "chapter_number": "2",

    # Optional but valuable
    "is_bailable": None,
    "triable_by": None,
    "punishment": None,
    "cross_references": ["MTA_2021_s.8", "MTA_2021_s.9"],
}
```

---

## Part E — Immediate Action Checklist

**Execute these in order on Lightning AI server:**

```bash
# 1. Recover 43 missing sections from existing PostgreSQL data (5 minutes)
python scripts/reindex_unindexed_sections.py

# 2. Tag 36,100 sc_judgment chunks with legal_domain (15 minutes)
python scripts/tag_sc_judgment_domains.py

# 3. Download and ingest Tier 1 critical statutes (3-4 hours)
# MTA 2021, CPA 2019, CPC 1908, HSA 1956

# 4. Verify Qdrant collections after ingestion
python scripts/inspect_data_stores.py

# 5. Run IK URL enrichment for existing 1,636 SC judgments
python scripts/enrich_ik_urls.py  # (needs to be built)
```

---

## Part F — Coverage Map After Full Ingestion

### Expected query coverage by role after Tier 1 + Tier 2 ingestion:

| Role | Current Coverage | After Tier 1 | After Tier 1+2 | After All Tiers |
|------|-----------------|--------------|-----------------|-----------------|
| Layman | ~35% | ~58% | ~72% | ~82% |
| Lawyer | ~45% | ~62% | ~75% | ~85% |
| Police | ~65% | ~70% | ~78% | ~88% |
| Advisor | ~40% | ~52% | ~65% | ~80% |

**Coverage definition:** % of representative queries that receive a VERIFIED or PRECEDENT_ONLY
response (not UNVERIFIED), measured on a 500-query evaluation set per role.

### Query categories still uncovered after all tiers (residual 15–20%):

1. State-specific laws beyond MH/DL/KA (Tamil Nadu, UP, Gujarat tenancy acts)
2. Religious personal law details (Muslim divorce specifics, Parsi personal law)
3. Tax law (Income Tax Act — 298 sections — very large)
4. Environment law (Environment Protection Act, Wildlife Act)
5. Highly specialised IP law (Patent Act, Copyright Act details)

These categories represent infrequent or highly specialised queries. For these,
the system should gracefully direct users to qualified legal professionals.

---

## Part G — Official Sources Index

| Source | URL | What It Provides |
|--------|-----|-----------------|
| **India Code** | https://www.indiacode.nic.in | All central acts — canonical PDFs |
| **Supreme Court of India** | https://sci.gov.in | SC judgments (official PDFs) |
| **Indian Kanoon** | https://indiankanoon.org | SC + HC + Tribunal judgments (API available) |
| **eCourts** | https://districts.ecourts.gov.in | District court + HC judgments |
| **Ministry of Law** | https://legislative.gov.in | Bills, acts, amendments |
| **NALSA** | https://nalsa.gov.in | Legal aid booklets (layman-accessible) |
| **NCDRC** | https://ncdrc.nic.in | Consumer forum procedure |
| **MCA (Companies)** | https://mca.gov.in | Companies Act + MCA circulars |
| **SEBI** | https://sebi.gov.in | Securities regulations |
| **RBI** | https://rbi.org.in | Banking regulations |
| **IBBI** | https://ibbi.gov.in | IBC + insolvency regulations |
| **Maharashtra Govt** | https://maharashtra.gov.in | State acts (Maharashtra) |
| **Delhi Govt** | https://delhi.gov.in | State acts (Delhi) |

---

*Document maintained by the Data Pipeline Agent.*
*Update after each ingestion batch. Cross-reference with `docs/retrieval_quality_analysis.md`.*
