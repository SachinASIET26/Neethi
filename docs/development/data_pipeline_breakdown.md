# Neethi AI — Data Pipeline Technical Breakdown
## Legal PDF Extraction → PostgreSQL → Qdrant for Indian Legal Agentic AI
**Role:** Senior RAG & Database Architect | **Scope:** BNS, BNSS, BSA Official India Code PDFs  
**Version:** 1.0 | **Date:** February 2026 | **Classification:** Engineering Reference

---

> **Reading Guide.** This document is written section by section in the order of operations a database architect follows. Read it front to back once before touching any tooling. Every decision here has a reason; that reason is stated explicitly. Where the existing JSON exhibits a defect, the defect is named, diagnosed, and corrected.

---

## Part 1 — Understanding the Source PDFs Before Extraction

### 1.1 What These PDFs Actually Are

The three official India Code PDFs — BNS 2023, BNSS 2023, and BSA 2023 — are not clean legislative documents. They are composite PDFs produced by the Bureau of Police Research and Development (BPR&D) for operational use by law enforcement and legal professionals. They contain **two entirely different categories of content fused into a single document stream**:

The first category is the **bare act text** — the actual law, which is what you want. The second category is **comparative editorial commentary** — analysis written by BPR&D comparing each new section against the old IPC, CrPC, and IEA sections it replaces. This commentary is valuable as metadata context but is catastrophically harmful if it leaks into the `legal_text` field that gets embedded and retrieved.

The existing JSON dataset has this leakage problem throughout. Understanding why it happens is prerequisite to fixing it.

### 1.2 The Anatomy of a Page in These PDFs

A typical page in the BNS PDF has the following structural layers, all of which produce text during extraction but serve entirely different purposes:

**The running header** appears at the top of every page and typically reads something like `BHARATIYA NYAYA SANHITA, 2023` alongside a chapter title. This is navigation furniture, not legal content.

**The page number** appears at the bottom, sometimes formatted as `— 47 —` or simply `47`. When PyMuPDF extracts text in reading order, these page numbers land mid-sentence between the content of one page and the next.

**The section heading and text** is the actual law. It begins with the section number in bold (e.g., `4. PUNISHMENTS.`) followed by sub-sections numbered `(1)`, `(2)`, `(a)`, `(b)`, etc., followed by Illustrations and Explanations.

**The footnotes** appear at the bottom of the page, separated by a thin horizontal rule. They follow a pattern of a superscript footnote number, then the text of the footnote. In the BPR&D PDFs, footnotes almost always cite the corresponding IPC/CrPC/IEA section being referenced. For example: `55 Section 63, "Amount of fine" IPC, 1860.`

**The comparison commentary** is either interleaved as a separate column in a two-column layout, or follows the section text in a visually distinct block (sometimes boxed or italicised). It contains phrases like `"Consolidation and Modifications in Section 8 BNS:-"` or `"COMPARISON WITH THE INDIAN PENAL CODE, 1860"`.

### 1.3 Diagnosed Noise Types in the Current JSON

Examining the existing `bns_complete.json`, `bnss_complete.json`, and `bsa_complete.json` reveals seven categories of noise that corrupt the `legal_text` field and degrade retrieval quality. These are not hypothetical — they are demonstrably present in the existing data.

**Noise Type 1 — Footnote Bleed.** Footnote references that sat at the bottom of a page were extracted inline, mid-paragraph. Example from BNS Section 8's `legal_text`: `"55 Section 63, \"Amount of fine\" IPC, 1860."` and `"57 Section 65, \"Limit to imprisonment for non-payment of fine\" IPC, 1860."` appear in the middle of sub-section (3)'s legal text. These lines are not law. They are footnotes that the PDF extractor picked up because it processes text in geometric reading order.

**Noise Type 2 — Cross-Section Contamination.** BNS Section 4's `legal_text` begins with `"4. Section 50 -'Section' - doesn't require any definition."` and then proceeds to contain the full text of BNS Section 3 (`SECTION 3. GENERAL EXPLANATIONS.`). Section 4 is supposed to be about Punishments. The contamination happened because the comparison commentary for Section 3 ran onto the same page as Section 4's beginning, and the section-boundary detector failed to reset.

**Noise Type 3 — Editorial Bracket Annotations.** Text like `"imprisonment for twenty years [ten years]"` or `"five thousand [fifty] rupees"` and `"(3) It shall come into force on [the 1st day of April, 1974] such date..."` in BNSS Section 1 are comparison markers. The bracket contains the old CrPC text; the outside text is the new BNSS text. The extractor treated the entire thing as legal text. For a vector search, embedding the phrase `"five thousand [fifty] rupees"` creates a corrupted semantic representation — the model sees an internal contradiction in the number.

**Noise Type 4 — Comparison Commentary in legal_text.** At the end of BNS Section 8's `legal_text`, the following appears: `"Consolidation and Modifications in Section 8 BNS:- Section 8 'Amount of fine', liability in default of payment of fine, etc' of BNS consolidates Section 63 to Section of IPC. Community service has been added..."` This is editorial analysis, not law. It belongs in `change_summary`, not `legal_text`.

**Noise Type 5 — Notes and change_summary Duplication.** In the BNSS dataset particularly, the `notes` and `change_summary` fields are often character-for-character identical. This doubles the size of the record without adding information. In Qdrant payloads this wastes space; in PostgreSQL this wastes storage and misleads downstream readers.

**Noise Type 6 — Degenerate rag_keywords.** The keyword list for BNSS Section 1 includes `"bharatiya"`, `"nagarik"`, `"sanhita"` — words that appear on literally every page of the document and have zero discriminatory power for retrieval. Additionally, keywords are stored as stemmed roots (`"facilitat"` instead of `"facilitate"`) due to an incomplete stemming implementation. These keywords would actually degrade sparse retrieval quality.

**Noise Type 7 — Inconsistent Chapter Numbering Convention.** BNS uses Roman numerals for chapter numbers (`"I"`, `"II"`, `"III"`) while BNSS uses Arabic numerals (`"1"`, `"2"`, `"3"`). A metadata filter `chapter_number = "1"` would match BNSS chapters but not BNS chapters. This is a schema consistency failure.

---

## Part 2 — The Extraction Philosophy: What "Clean" Means

Before defining rules, it is worth stating the architectural principle clearly: **the `legal_text` field in your database must contain exactly and only the text that a lawyer would read if they picked up the official Gazette notification and read the section**. Nothing else belongs in `legal_text`. The comparative analysis, the footnotes, the headers, the page numbers — all of it is noise relative to that definition.

This is not perfectionism. It is a retrieval accuracy requirement. When a user asks "what is the punishment for murder under BNS?", your embedding model will embed the query and compare it to embedded chunks in Qdrant. If your BNS Section 103 chunk contains a mix of law text and IPC comparison commentary, the embedding is a blend of two semantically different documents. The cosine similarity score will be lower than it should be, and worse, sections where the commentary happens to use the query's keywords more than the law text does will rank inappropriately high.

### 2.1 The Two-Pass Extraction Strategy

Professional extraction from these specific PDFs requires two passes, not one.

**Pass 1 — Structure Detection.** The goal of the first pass is not to extract text but to build a map of the document's structure. For each page, detect: where the page header is (coordinates in the PDF coordinate system), where the page footer and page number are, where section headings begin (characterised by a bold, left-aligned number followed by a capitalised heading), where footnote areas begin (characterised by content below a horizontal rule or a superscript-numbered pattern), and where comparison blocks begin (characterised by keywords like `"COMPARISON WITH"`, `"Modification & Additions"`, `"Consolidation and Modifications"`, or the presence of a two-column layout shift).

Once you have this structural map for each page, you have bounding boxes — coordinate regions — that label each area of each page as one of: `HEADER`, `FOOTER`, `SECTION_TEXT`, `FOOTNOTE`, `COMPARISON_BLOCK`. This is the authoritative classification layer. Nothing in `FOOTNOTE` or `COMPARISON_BLOCK` enters `legal_text`.

**Pass 2 — Content Extraction Using the Map.** Only after Pass 1 produces the structural map do you extract text. For each page, extract only from regions classified as `SECTION_TEXT`. Apply cleaning rules (Part 3) to the extracted text. Identify section boundaries (the bold numbered heading pattern) and assign text to the correct section record.

The key insight is that Pass 1 is a spatial analysis of the PDF, not a text analysis. PDFs are not plain text — they are geometric documents where every character has an x,y coordinate. PyMuPDF exposes these coordinates. Use them.

### 2.2 Section Boundary Rules

A section in Indian legislation has a predictable grammar. Understanding this grammar is what makes a legal-aware chunker different from a generic text splitter.

A section begins with its number and title, formatted as `[NUMBER]. [TITLE IN CAPS].` followed by a newline and the body text. The body text may contain numbered sub-sections `(1)`, `(2)` etc., which may themselves contain lettered sub-clauses `(a)`, `(b)` etc. A section may contain one or more `Illustration` blocks (marked with the word `Illustration` or `Illustrations` followed by lettered examples). A section may contain one or more `Explanation` blocks (marked with `Explanation.-` or `Explanation.--`). A section may contain `Proviso` blocks (marked with `Provided that`). The section ends when the next section heading begins.

This grammar is your chunking specification. The section, sub-sections, illustrations, explanations, and provisos are all distinct structural units that carry different legal weight. An Explanation in Indian law modifies the scope of the main provision — it is not a sub-section. A Proviso creates an exception — it qualifies what comes before it. These distinctions matter for retrieval because a user asking about an exception needs to find the Proviso, not the main provision.

---

## Part 3 — Text Cleaning Rules, Applied in Order

These rules are applied to the raw extracted text of each section after Pass 1 has filtered out headers, footers, footnotes, and comparison blocks. They are listed in application order — some rules must precede others to avoid conflicts.

**Rule 1 — Strip Running Headers.** Remove any line that matches the pattern of the Act's full name followed by a year, the chapter title, or section range markers. These appear because PDF extraction sometimes captures the header region despite your coordinate filter, especially at page boundaries. Regex: lines containing `BHARATIYA NYAYA SANHITA, 2023`, `BHARATIYA NAGARIK SURAKSHA SANHITA, 2023`, or `BHARATIYA SAKSHYA ADHINIYAM, 2023` followed by nothing else on the line are headers.

**Rule 2 — Strip Page Numbers.** Remove any line that consists solely of a number (with optional surrounding dashes or whitespace). Patterns like `— 47 —`, `47`, `[47]` are page numbers.

**Rule 3 — Remove Inline Footnote References.** Inline superscript footnote references appear in two forms: a standalone number at the start of a line (which is the footnote definition itself, e.g., `55 Section 63, "Amount of fine" IPC, 1860.`), or a superscript number embedded inline mid-sentence (which references a footnote). For the standalone form, the detection pattern is: a line that begins with one or two digits, followed by a space, followed by the word "Section" (capitalised), followed by a comma or quoted section name and act name. These lines are pure footnote definitions — remove them entirely. For inline superscript references (tiny numbers mid-text), PyMuPDF's character-level font size attribute identifies these: any character with a font size less than 70% of the surrounding body text font size is a superscript footnote marker and should be removed.

**Rule 4 — Remove Comparison Bracket Annotations.** The bracket annotation pattern `[old text]` where the brackets contain old-law text appears throughout the BPR&D PDFs. Distinguish this from legitimate legal brackets (which appear in genuinely parenthetical phrases like `"(whether of death or not)"`) by context: if both the bracketed text and the surrounding text contain numbers (especially monetary amounts or time periods) and they contradict each other numerically, the bracketed text is a comparison annotation. More reliably: if Pass 1 has correctly classified the surrounding block as `COMPARISON_BLOCK`, no bracket stripping is needed because the entire block is excluded. The residual bracket annotations in `SECTION_TEXT` regions are fewer and can be caught by: if a bracket immediately follows or precedes a number and contains a different number, remove the bracket and its contents.

**Rule 5 — Remove Comparison Commentary Blocks.** Even after Pass 1, some comparison commentary bleeds into section text, especially when a commentary block begins on the same page as a section's beginning. Secondary detection: any sentence or paragraph that begins with `"Consolidation and Modifications"`, `"COMPARISON WITH"`, `"Modification & Addition"`, `"The following changes were made"`, or `"In sub section"` followed by a reference to old-law section numbers is commentary. Remove from that point to the next section heading.

**Rule 6 — Unicode Normalization.** The PDFs contain several Unicode encoding artifacts: the encoding sequence `â€"` is the UTF-8 mojibake for an em-dash (`—`), `â€™` is a right single quotation mark (`'`), `â€œ` and `â€` are left and right double quotation marks (`"` and `"`), and `â†'` is a right arrow. Normalize all of these to their correct Unicode characters. Additionally, normalize multiple consecutive whitespace characters to single spaces, and normalize `\r\n` and `\r` line endings to `\n`.

**Rule 7 — Reconstruct Hyphenated Line Breaks.** PDF extraction sometimes splits words at line breaks with a hyphen: `"imprison-\nment"` should become `"imprisonment"`. Detect the pattern of a word ending with `-\n` followed by a lowercase continuation and join them.

**Rule 8 — Preserve Structural Markers.** Do not strip sub-section numbers, illustration labels, or explanation markers. These are part of the legal text. `(1)`, `(a)`, `Illustration`, `Explanation.-` are structural and semantic markers that help retrieval (a user asking about an exception to a rule needs to find the Explanation or Proviso, not the main provision body).

---

## Part 4 — PostgreSQL Schema: The Structured Relational Layer

### 4.1 The Philosophical Division

PostgreSQL holds everything that answers a question deterministically. If the answer to a question is always the same regardless of who asks, it belongs in PostgreSQL. If the answer requires semantic similarity reasoning, it belongs in Qdrant. The rule of thumb: **PostgreSQL is truth; Qdrant is relevance**.

Every table below is explained in terms of what question it answers and why that question must be answered deterministically.

### 4.2 Table: `acts`

This is the root table. Every section, chapter, and transition mapping is a child of a row in this table.

```
acts
├── id                  UUID PRIMARY KEY
├── act_code            VARCHAR(20) NOT NULL UNIQUE
│   -- Canonical short identifier. Values: 'BNS_2023', 'BNSS_2023', 'BSA_2023',
│   -- 'IPC_1860', 'CrPC_1973', 'IEA_1872'. This is the foreign key used everywhere.
│   -- Never use the full name as a key — it changes across editions.
├── act_name            VARCHAR(200) NOT NULL
│   -- Full official name: "Bharatiya Nyaya Sanhita, 2023"
├── act_name_hindi      VARCHAR(200)
│   -- "भारतीय न्याय संहिता, 2023" — for Sarvam AI translation support
├── short_name          VARCHAR(50)
│   -- "BNS" — common abbreviation used in citations
├── act_number          INT
│   -- Official act number passed by Parliament: 45 for BNS, 46 for BNSS, 47 for BSA
├── year                INT NOT NULL
├── effective_date      DATE
│   -- The date this act came into force. BNS/BNSS/BSA: 2024-07-01
├── repealed_date       DATE
│   -- NULL if still in force. IPC: 2024-06-30
├── status              VARCHAR(20) NOT NULL DEFAULT 'active'
│   -- CHECK (status IN ('active', 'repealed', 'amended', 'notified'))
├── era                 VARCHAR(30) NOT NULL
│   -- CHECK (era IN ('colonial_codes', 'naveen_sanhitas', 'constitutional', 'other'))
│   -- 'colonial_codes' = IPC/CrPC/IEA. 'naveen_sanhitas' = BNS/BNSS/BSA.
├── replaces_act_code   VARCHAR(20) REFERENCES acts(act_code)
│   -- BNS_2023 replaces IPC_1860. Null for IPC itself.
├── domain              VARCHAR(50)
│   -- CHECK (domain IN ('criminal_substantive', 'criminal_procedure', 'evidence', 'civil', 'constitutional'))
├── total_sections      INT
├── total_chapters      INT
├── gazette_reference   VARCHAR(200)
│   -- Official Gazette citation for the Act's notification
├── source_url          TEXT
│   -- India Code URL for the authoritative source text
├── created_at          TIMESTAMPTZ DEFAULT NOW()
└── updated_at          TIMESTAMPTZ DEFAULT NOW()
```

Why `era` on the `acts` table? Because the Query Analyst agent, when it determines temporal context from a user query, issues a filter like `era = 'naveen_sanhitas'` at the act level. Without this, it would need to enumerate all three post-2024 act codes every time.

### 4.3 Table: `chapters`

```
chapters
├── id                  UUID PRIMARY KEY
├── act_code            VARCHAR(20) NOT NULL REFERENCES acts(act_code)
├── chapter_number      VARCHAR(10) NOT NULL
│   -- Normalised to Roman numeral string for all acts: 'I', 'II', 'III'
│   -- This resolves the BNS/BNSS inconsistency in the existing JSON.
│   -- The chapter_number stored here is ALWAYS the Roman numeral form.
│   -- A separate chapter_number_int INT column holds the Arabic equivalent for ordering.
├── chapter_number_int  INT NOT NULL
│   -- Arabic integer for ORDER BY. Chapter I = 1, Chapter II = 2, etc.
├── chapter_title       VARCHAR(300) NOT NULL
├── sections_range      VARCHAR(30)
│   -- '1-3', '4-13', etc. Informational only — do not use for queries.
├── domain              VARCHAR(100)
│   -- Legal domain label: 'Preliminary & Definitions', 'Punishment Types', etc.
├── section_count       INT
└── UNIQUE (act_code, chapter_number)
```

### 4.4 Table: `sections` — The Central Table

This is the most important table in the system. Every agent, every citation verification, every statute normalization lookup ultimately traces back to a row here.

```
sections
├── id                      UUID PRIMARY KEY
├── act_code                VARCHAR(20) NOT NULL REFERENCES acts(act_code)
├── chapter_id              UUID REFERENCES chapters(id)
├── section_number          VARCHAR(20) NOT NULL
│   -- The section number as a string: '1', '2', '103', '438A'
│   -- String because section numbers in Indian law can include letters: '53A', '124A'
├── section_number_int      INT
│   -- Integer part only, for ordering. Section 53A → 53. NULL if purely alphanumeric.
├── section_number_suffix   VARCHAR(5)
│   -- Alphabetic suffix if any: '53A' → 'A'. NULL if numeric only.
├── section_title           VARCHAR(500)
│   -- The official heading: 'Murder', 'Short Title, Commencement And Application'
│   -- Cleaned: no ALL-CAPS, title case normalised.
├── section_title_hindi     VARCHAR(500)
│   -- Hindi equivalent for multilingual retrieval support
├── legal_text              TEXT NOT NULL
│   -- THE CLEAN LAW TEXT ONLY. Zero noise as per Part 3 rules.
│   -- This is the single most important field in the system.
│   -- What a lawyer reads when they open the Gazette. Nothing else.
├── status                  VARCHAR(20) NOT NULL DEFAULT 'active'
│   -- CHECK (status IN ('active', 'repealed', 'omitted', 'substituted', 'amended'))
├── applicable_from         DATE
│   -- When this section came into force.
├── applicable_until        DATE
│   -- NULL if still in force. Set to repealed date when a section is superseded.
├── era                     VARCHAR(30) NOT NULL
│   -- Inherited from acts.era. Denormalised here for query performance.
│   -- Qdrant payload will also carry this — they must stay in sync.
│
│   --- Offence Classification Fields (populated for criminal law sections only) ---
├── is_offence              BOOLEAN DEFAULT FALSE
│   -- TRUE if this section defines or describes a criminal offence.
├── is_cognizable           BOOLEAN
│   -- TRUE = police can arrest without warrant. NULL = not an offence section.
├── is_bailable             BOOLEAN
│   -- TRUE = accused entitled to bail as a right. NULL = not applicable.
├── triable_by              VARCHAR(50)
│   -- 'Court of Sessions', 'Magistrate First Class', 'Any Magistrate', etc.
├── punishment_type         VARCHAR(100)
│   -- Comma-separated: 'death,life_imprisonment,fine' or 'imprisonment,fine'
│   -- Normalised vocabulary; do not free-text this field.
├── punishment_min_years    NUMERIC(5,2)
│   -- Minimum imprisonment in years. NULL if not prescribed.
├── punishment_max_years    NUMERIC(5,2)
│   -- Maximum imprisonment in years. 99999 represents life imprisonment.
├── punishment_fine_max     BIGINT
│   -- Maximum fine in rupees. NULL if not prescribed.
│
│   --- Source Quality Fields ---
├── has_subsections         BOOLEAN DEFAULT FALSE
│   -- TRUE if this section has sub-sections (1), (2) etc.
├── has_illustrations       BOOLEAN DEFAULT FALSE
├── has_explanations        BOOLEAN DEFAULT FALSE
├── has_provisos            BOOLEAN DEFAULT FALSE
├── extraction_confidence   FLOAT DEFAULT 1.0
│   -- How confident the extraction pipeline is that legal_text is clean.
│   -- < 0.7 means manual review is recommended before indexing to Qdrant.
│
│   --- Cross-Reference Tracking (structured form) ---
├── internal_refs           JSONB
│   -- Array of section refs within the same act: [{"act":"BNS_2023","section":"2","clause":"(3)"}]
├── external_refs           JSONB
│   -- Refs to other acts: [{"act":"IT_Act_2000","section":"66A"}]
│
└── UNIQUE (act_code, section_number)

-- Indexes
CREATE INDEX idx_sections_act_code ON sections(act_code);
CREATE INDEX idx_sections_status ON sections(status);
CREATE INDEX idx_sections_era ON sections(era);
CREATE INDEX idx_sections_is_offence ON sections(is_offence) WHERE is_offence = TRUE;
CREATE INDEX idx_sections_cognizable ON sections(is_cognizable) WHERE is_cognizable IS NOT NULL;
CREATE UNIQUE INDEX idx_sections_act_num ON sections(act_code, section_number);
```

### 4.5 Table: `sub_sections`

Sub-sections are extracted as separate rows. This is the change that matters most for retrieval precision. When a user asks about bail rights, they need BNSS Section 480(1) — not the entire 800-word Section 480. When a user asks about the exception to a provision, they need the specific Explanation or Proviso clause.

```
sub_sections
├── id                  UUID PRIMARY KEY
├── section_id          UUID NOT NULL REFERENCES sections(id)
├── act_code            VARCHAR(20) NOT NULL
│   -- Denormalized for join-free filtering in Qdrant payload construction.
├── parent_section_number VARCHAR(20) NOT NULL
│   -- The parent section number, e.g., '480'
├── sub_section_label   VARCHAR(20) NOT NULL
│   -- '(1)', '(2)', '(a)', '(b)', 'Explanation', 'Proviso', 'Illustration_A'
│   -- Normalised form. Illustrations labeled 'Illustration_A', 'Illustration_B', etc.
├── sub_section_type    VARCHAR(30) NOT NULL
│   -- CHECK (sub_section_type IN (
│   --   'numbered',     -- (1), (2), (3)
│   --   'lettered',     -- (a), (b), (c)
│   --   'explanation',  -- Explanation.-
│   --   'proviso',      -- Provided that
│   --   'illustration', -- Illustration (a), (b)
│   --   'exception'     -- Exception
│   -- ))
├── legal_text          TEXT NOT NULL
│   -- The clean text of this sub-section alone.
│   -- Does NOT repeat the parent section's opening text.
├── position_order      INT NOT NULL
│   -- Ordinal position within the parent section, starting at 1.
└── UNIQUE (section_id, sub_section_label)
```

The reasoning for separating sub-sections: the embedding of a 2,000-word section that contains both the definition of an offence AND its exceptions AND three illustrations creates a vector that is semantically diffuse. A user asking about the exception will not reliably retrieve this chunk at the top of results because the exception's semantic signal is diluted by the main provision's signal. Granular sub-section embeddings solve this.

### 4.6 Table: `law_transition_mappings` — The Safety Table

This is the table that prevents the murder-snatching confusion. Every row is a deterministic fact about how the legal landscape changed on July 1, 2024.

```
law_transition_mappings
├── id                  UUID PRIMARY KEY DEFAULT gen_random_uuid()
├── old_act             VARCHAR(20) NOT NULL
│   -- 'IPC_1860', 'CrPC_1973', 'IEA_1872'
├── old_section         VARCHAR(20) NOT NULL
│   -- '302', '376', '124A'
├── old_section_title   VARCHAR(500)
│   -- 'Murder', 'Rape', 'Sedition' — the old section's heading for human review
├── new_act             VARCHAR(20)
│   -- 'BNS_2023', 'BNSS_2023', 'BSA_2023'. NULL if the offence was deleted.
├── new_section         VARCHAR(20)
│   -- '103', '63', NULL
├── new_section_title   VARCHAR(500)
│   -- 'Murder', 'Rape' — the new section's heading
├── transition_type     VARCHAR(20) NOT NULL
│   -- CHECK (transition_type IN (
│   --   'equivalent',    -- Direct 1-to-1 renaming with same substance
│   --   'modified',      -- Renamed but substance changed
│   --   'split_into',    -- One old section → multiple new sections
│   --   'merged_from',   -- Multiple old sections → one new section
│   --   'deleted',       -- Old section has no new equivalent (e.g., IPC 124A sedition)
│   --   'new'            -- New section exists in new law with no old equivalent
│   -- ))
├── transition_note     TEXT
│   -- Human-readable explanation of what changed and why it matters.
│   -- "Murder. Renumbered from IPC 302. Punishment unchanged. BNS 302 = Snatching — completely different."
├── scope_change        VARCHAR(30)
│   -- CHECK (scope_change IN ('none', 'narrowed', 'expanded', 'restructured', 'unknown'))
│   -- Was the legal scope of the offence changed, not just renumbered?
├── semantic_similarity FLOAT
│   -- Cosine similarity between embeddings of old and new section text.
│   -- Populated by the validation pipeline. Low score (< 0.65) flags conceptual drift.
├── gazette_reference   VARCHAR(300)
│   -- Official source: 'Statement of Objects and Reasons, BNS Bill 2023, Schedule II'
├── effective_date      DATE NOT NULL DEFAULT '2024-07-01'
├── confidence_score    FLOAT NOT NULL DEFAULT 0.0
│   -- 1.0 = from official comparative table (highest authority)
│   -- 0.85 = multi-source agreement
│   -- 0.65 = semantic similarity auto-approved
│   -- < 0.5 = requires human review
├── approved_by         VARCHAR(100)
│   -- Legal reviewer's name/ID. NULL = not yet approved.
├── approved_at         TIMESTAMPTZ
├── user_correct_votes  INT DEFAULT 0
├── user_wrong_votes    INT DEFAULT 0
├── auto_demoted        BOOLEAN DEFAULT FALSE
│   -- TRUE if user votes dropped confidence below threshold
├── is_active           BOOLEAN DEFAULT FALSE
│   -- ONLY rows with is_active = TRUE are used by StatuteNormalizationTool.
│   -- is_active = TRUE requires: confidence_score >= 0.65 AND approved_by IS NOT NULL
├── created_at          TIMESTAMPTZ DEFAULT NOW()
└── updated_at          TIMESTAMPTZ DEFAULT NOW()

-- The critical indexes
CREATE INDEX idx_transition_old ON law_transition_mappings(old_act, old_section);
CREATE INDEX idx_transition_new ON law_transition_mappings(new_act, new_section);
CREATE INDEX idx_transition_active ON law_transition_mappings(is_active) WHERE is_active = TRUE;
```

**The split case explained.** When IPC Section 376 (Rape) splits into BNS Sections 63, 64, 65, 66, 67, 68, and 70, you create seven rows in this table — one for each new section — all with `old_section = '376'` and `transition_type = 'split_into'`. The `StatuteNormalizationTool` queries `WHERE old_act = 'IPC_1860' AND old_section = '376'` and gets back seven rows. It presents all seven new sections to the Query Analyst, which decides which sub-aspect of rape law is relevant to the query. This is deterministic, not semantic.

### 4.7 Table: `cross_references`

Cross-references in Indian legislation are explicit ("as defined in Section 2(1)(d)") and implicit (when the same legal concept is addressed in multiple sections). Structured cross-references make the graph traversal possible without a dedicated graph database.

```
cross_references
├── id                  UUID PRIMARY KEY
├── source_act          VARCHAR(20) NOT NULL
├── source_section      VARCHAR(20) NOT NULL
├── target_act          VARCHAR(20) NOT NULL
├── target_section      VARCHAR(20) NOT NULL
├── target_subsection   VARCHAR(20)
│   -- '(1)(d)', '(a)', 'Explanation_1' etc.
├── reference_text      TEXT
│   -- The exact phrase that created this reference: "as defined in Section 2(1)(d)"
├── reference_type      VARCHAR(30)
│   -- CHECK (reference_type IN (
│   --   'definition_import',    -- "as defined in Section X"
│   --   'subject_to',           -- "subject to the provisions of Section X"
│   --   'procedure_link',       -- procedural section pointing to offence section
│   --   'punishment_table',     -- reference to Schedule or punishment table
│   --   'exception_reference',  -- "except as provided in Section X"
│   --   'cross_act_reference'   -- reference to a different Act
│   -- ))
└── extraction_method   VARCHAR(30)
    -- 'regex_pattern', 'llm_extracted', 'manual'
```

### 4.8 Supporting Tables for Operational Integrity

**`extraction_audit`** — tracks every section that was extracted, what noise was found, what was removed, and the final extraction confidence score. This is your quality control record. Every section in `sections` has a corresponding audit row.

**`human_review_queue`** — any section or mapping where `extraction_confidence < 0.8` or `confidence_score < 0.65` goes here. A legal reviewer sees the raw text, the cleaned text, and approves or rejects. Nothing with a review pending enters Qdrant indexing.

**`ingestion_jobs`** — tracks which PDFs have been processed, when, with what version of the extraction pipeline, so re-runs are idempotent and incremental updates are safe.

---

## Part 5 — Qdrant Schema: The Semantic Retrieval Layer

### 5.1 Collection Architecture

Qdrant is not a single bucket. The collections are designed around retrieval patterns, not storage convenience. Each collection has a distinct embedding profile, metadata filter vocabulary, and access pattern.

**Collection `legal_sections`** — the primary retrieval collection. Contains embedded chunks of legal text from BNS, BNSS, BSA, IPC, CrPC, and IEA. This is where "what does Section X say" queries land.

**Collection `legal_sub_sections`** — granular sub-section chunks. Used when the Query Analyst determines the query is about a specific clause, exception, proviso, or illustration. Allows precise retrieval without the semantic dilution of full-section embeddings.

**Collection `case_law`** — Supreme Court and High Court judgments. Separate collection because judgment text has a fundamentally different embedding profile from statute text: it is narrative, longer, and contains legal reasoning alongside citation strings. Mixing with statute text would degrade both retrieval paths.

**Collection `notifications`** — SEBI circulars, RBI notifications, MCA general orders, state government notifications. Used for corporate and compliance queries.

**Collection `law_transition_context`** — embedded transition notes and comparative explanations. When the system needs to explain to a user how IPC 302 became BNS 103 in plain language, it retrieves from here, not from `legal_sections`. Separating this prevents transition commentary from contaminating statute text retrieval.

### 5.2 Embedding Configuration

All collections use **BGE-M3** as the embedding model. This is a fixed architectural decision documented in the project's `embedding_model_comparison.md`. BGE-M3 produces both dense and sparse representations simultaneously, which directly enables Qdrant's hybrid search without a separate BM25 computation step.

Vector dimensions: 1024 (BGE-M3 dense) + sparse (variable length, BGE-M3 ColBERT-style sparse).

Distance metric: Cosine similarity for dense vectors.

### 5.3 The `legal_sections` Collection — Point Payload Specification

Every point in Qdrant's `legal_sections` collection has a payload. The payload is what Qdrant's metadata filters operate on. The design principle: **every dimension you might want to filter on must be in the payload as a flat, primitive-typed field**. Nested objects in Qdrant payloads cannot be efficiently filtered; flatten everything.

```json
{
  "point_id": "uuid-matching-sections.id",
  
  "act_code": "BNS_2023",
  "act_name": "Bharatiya Nyaya Sanhita, 2023",
  "act_short": "BNS",
  
  "section_number": "103",
  "section_title": "Murder",
  "chapter_number": "V",
  "chapter_number_int": 5,
  "chapter_title": "Of Offences Against the Human Body",
  
  "era": "naveen_sanhitas",
  "status": "active",
  "applicable_from": "2024-07-01",
  "applicable_until": null,
  
  "legal_domain": "criminal",
  "sub_domain": "offences_against_body",
  
  "is_offence": true,
  "is_cognizable": true,
  "is_bailable": false,
  "triable_by": "Court of Sessions",
  "punishment_type": "death,life_imprisonment,fine",
  "punishment_max_years": 99999,
  
  "has_subsections": true,
  "has_illustrations": true,
  "has_explanations": true,
  "has_provisos": false,
  
  "supersedes_act": "IPC_1860",
  "supersedes_section": "302",
  "transition_type": "equivalent",
  
  "chunk_type": "full_section",
  "chunk_index": 0,
  "total_chunks": 1,
  
  "text": "[CLEAN LEGAL TEXT — what gets embedded and displayed]",
  
  "extraction_confidence": 0.98,
  "ingestion_timestamp": "2026-02-07T00:00:00Z"
}
```

**Why `chunk_type` and `chunk_index`?** Long sections (Section 2 Definitions, Section 8 Amount of Fine) exceed the practical embedding window for a single quality chunk. These are split into overlapping chunks of approximately 400-600 tokens with a 50-token overlap. The `chunk_index` tracks position within the split. When the Response Formatter needs to display the full section text, it queries PostgreSQL by `section_id`, not Qdrant. Qdrant's job is only to find the right section — display comes from PostgreSQL.

**Why both `era` and `applicable_from`/`applicable_until`?** The `era` field supports coarse categorical filtering (user asked about current law → filter `era = 'naveen_sanhitas'`). The date fields support fine-grained temporal queries (user's case was filed on June 15, 2024 → filter `applicable_from <= '2024-06-15' AND (applicable_until IS NULL OR applicable_until >= '2024-06-15')`).

**Why `supersedes_act` and `supersedes_section` on the Qdrant payload?** When the system retrieves BNS Section 103 in response to a query, the Response Formatter needs to generate the transition note: "Previously IPC Section 302 (repealed)". Having this information in the Qdrant payload means zero additional PostgreSQL round-trips during response generation. This is a deliberate denormalization for latency reduction.

### 5.4 The `legal_sub_sections` Collection — Point Payload Specification

```json
{
  "point_id": "uuid-matching-sub_sections.id",
  
  "parent_section_id": "uuid-of-parent-sections-row",
  "act_code": "BNSS_2023",
  "section_number": "480",
  "sub_section_label": "(1)",
  "sub_section_type": "numbered",
  "position_order": 1,
  
  "era": "naveen_sanhitas",
  "status": "active",
  "legal_domain": "criminal_procedure",
  "sub_domain": "bail",
  
  "parent_section_title": "Provision for bail to person apprehended",
  "parent_chapter_title": "Of Bail and Bail Bonds",
  
  "is_exception": false,
  "is_definition": false,
  "is_illustration": false,
  "is_proviso": false,
  
  "chunk_type": "sub_section",
  "text": "[CLEAN SUB-SECTION TEXT ONLY — does not repeat parent section opening]"
}
```

### 5.5 Chunking Strategy: The Complete Decision Tree

The chunking decision is made per section, not globally. The rules below constitute the complete decision tree.

**Scenario A — Short section (legal_text under 400 tokens, no sub-sections).** Embed the entire section as a single point in `legal_sections`. No entry in `legal_sub_sections`. Example: BNS Section 6 ("Fractions of terms of punishment") — two sentences, completely self-contained. One point, maximum retrieval precision.

**Scenario B — Medium section with sub-sections (400–1200 tokens).** Embed the full section as one point in `legal_sections` (with `chunk_type = 'full_section'`). Additionally, embed each sub-section (numbered sub-sections, explanations, and provisos) as individual points in `legal_sub_sections`. Illustrations are embedded as part of their parent sub-section where they directly illustrate that sub-section's rule; if they are section-level illustrations, embed them separately with `sub_section_type = 'illustration'`. This dual representation means a query about the general provision retrieves from `legal_sections`, and a query about a specific clause or exception retrieves from `legal_sub_sections`.

**Scenario C — Long section (over 1200 tokens, with or without sub-sections).** Sections like BNS Section 2 (Definitions) and BNS Section 8 (Amount of Fine) can run to 3,000+ tokens after cleaning. Split the `legal_sections` embedding into overlapping 600-token chunks with 75-token overlap, tracking `chunk_index` and `total_chunks`. Always preserve sub-section boundaries — never cut through a sub-section mid-text; prefer to start a new chunk at the next sub-section boundary. Additionally create `legal_sub_sections` entries for each individual sub-section. For BNS Section 2, every definition — `2(1)`, `2(2)`, `2(3)` ... `2(39)` — is its own `legal_sub_sections` entry. When a user asks "what is the definition of child under BNS?", the sub-section search returns BNS 2(3) directly, a 20-word entry, with zero dilution from the other 38 definitions.

**Scenario D — Section 2 (Definitions) specifically.** This section is a special case across all three acts. The definitions section in each act is a dense list of 30–60 definitions, each a standalone legal concept. Every definition sub-clause gets its own `legal_sub_sections` entry. The `sub_section_label` for BNS Section 2(3) is `"(3)"` and the `text` is `'"child" means any person below the age of eighteen years'`. When a user asks "what is a child under BNS?", a sub-section search with text similarity to "definition of child BNS" returns this exact 14-word entry with a relevance score close to 1.0.

---

## Part 6 — Data Quality Validation Before Indexing

### 6.1 The Validation Pipeline

Before a section is indexed into Qdrant, it passes through a validation pipeline. This pipeline runs deterministically and produces a structured validation report per section.

**Check 1 — Footnote Residue Detection.** Scan `legal_text` for patterns matching `^\d{1,3}\s+Section\s+\d+` (a line starting with 1-3 digits, space, "Section", space, digits). Any match flags the section for manual review. Additionally check for footnote-style superscript number references by scanning for isolated numbers following non-space, non-punctuation characters mid-sentence.

**Check 2 — Comparison Commentary Residue Detection.** Scan `legal_text` for trigger phrases: `"COMPARISON WITH"`, `"Modification & Addition"`, `"Consolidation and Modifications"`, `"In sub section"` followed by a parenthetical referencing old-law section numbers. Any match is a hard fail — section must be re-extracted.

**Check 3 — Section Boundary Integrity.** Verify that the `section_number` in the record matches the section number that appears as the first meaningful token in `legal_text`. If BNS record has `section_number = '8'` but `legal_text` begins with `"3. GENERAL EXPLANATIONS"`, this is a cross-section contamination failure (exactly the defect seen in the existing JSON for BNS Section 4).

**Check 4 — Bracket Annotation Residue Detection.** Scan for patterns of `[NUMBER]` or `[\d+ (unit)]` where a number inside brackets contradicts a number immediately outside brackets (e.g., `"five thousand [fifty] rupees"`). These are comparison annotation residues.

**Check 5 — Legal Text Completeness.** If `legal_text` is empty, null, or under 20 characters, the section failed extraction entirely. Flag for manual extraction from the PDF.

**Check 6 — Sub-section Count Consistency.** If `has_subsections = TRUE` in the sections record, there must be at least one corresponding row in `sub_sections`. If the count of rows in `sub_sections` for this section_id is less than the expected sub-section count (estimable by counting `(1)`, `(2)` patterns in the cleaned text), flag for review.

**Check 7 — Punishment Field Consistency.** If `is_offence = TRUE`, then `is_cognizable`, `is_bailable`, and `triable_by` must be non-null. These fields cannot be left null for offence sections — they are required by the Police user's response formatter and the citation verifier. If they cannot be determined from the section text itself (some sections require Schedule I of BNSS for these values), they are populated via a join query against the BNSS Schedule I table.

### 6.2 The Extraction Confidence Score Calculation

The `extraction_confidence` score is computed as a weighted product of the individual checks:

The base score starts at 1.0. Footnote residue found subtracts 0.3. Comparison commentary residue found subtracts 0.4 (hard fail if found). Bracket annotation residue found subtracts 0.2. Legal text under 50 characters subtracts 0.5. Sub-section count discrepancy of more than 20% subtracts 0.15. Any sub-section that itself fails checks propagates a 0.05 penalty per failed sub-section.

A section with `extraction_confidence < 0.7` does not enter Qdrant until manually reviewed and re-extracted. A section with `extraction_confidence >= 0.7 and < 0.9` enters Qdrant but its metadata carries `needs_review = TRUE`, and any response citing it appends: `"[Source text pending quality review]"`.

---

## Part 7 — Correcting the Existing JSON Before PostgreSQL Ingestion

The existing JSON files are a useful starting point but cannot be ingested directly. They require a structured correction pass. This section maps each identified defect to its correction action.

### 7.1 legal_text Field Corrections

For BNS Section 4: The `legal_text` begins with footnote material and then contains the full text of Section 3. The entire `legal_text` value must be discarded and re-extracted from the PDF using the coordinate-based extraction described in Part 2. The extraction confidence for this section should be set to 0.0 until re-extraction is complete — it currently contains another section's law entirely.

For BNS Section 8: Strip all lines matching the footnote detection pattern (lines starting with `55`, `57`, `62` followed by "Section" and IPC references). Strip the trailing commentary block beginning with `"Consolidation and Modifications in Section 8 BNS:-"`. After stripping, re-verify that all seven sub-sections `(1)` through `(7)` and the Illustration remain intact.

For BNSS Section 1: The text `"[the 1st day of April, 1974]"` inside sub-section (3) is a CrPC comparison annotation. Remove the bracket and its contents, preserving the surrounding BNSS text: `"It shall come into force on such date as the Central Government may, by notification in the Official Gazette, appoint."` This is the correct BNSS text.

For any section where `notes` and `change_summary` are identical character-for-character: keep `change_summary` (it is more explicitly named for its purpose) and set `notes` to null. In PostgreSQL the `notes` field is renamed to `extraction_notes` and reserved for the extraction pipeline's own notes, not editorial content from the source document.

### 7.2 Schema Normalisation Corrections

Chapter numbers must be standardised to Roman numerals across all three acts. The conversion table is I through XXXIX for BNSS (39 chapters). Store the Arabic integer equivalent in `chapter_number_int` for all ordering operations.

The `rag_keywords` array in the existing JSON must not be directly ingested into PostgreSQL or used for sparse retrieval. The keywords are not computed correctly — they contain act-wide stop words (`"bharatiya"`, `"sanhita"`, `"act"`) and incorrectly stemmed forms. Discard this field. Sparse retrieval in Qdrant uses BGE-M3's own sparse representation computed from the clean `legal_text` — you do not pre-compute keywords.

The `domain` field exists at both the chapter level and the section level in the existing JSON, sometimes with different values for sections in the same chapter. The chapter-level domain is the authoritative one. Section-level `domain` must be reconciled against chapter-level `domain`. Where they differ, the legal content of the section governs which is correct — this is a case for manual legal review, not algorithmic resolution.

---

## Part 8 — The Data Flow: End-to-End Summary

The complete path from PDF to queryable data is:

The official India Code PDF is ingested by the extraction pipeline. Pass 1 maps the document structure spatially. Pass 2 extracts clean text within identified `SECTION_TEXT` regions. Text cleaning rules are applied in order. Each section is parsed into its structural components (section heading, sub-sections, illustrations, explanations, provisos). Validation checks are run; any failure below the confidence threshold routes to the human review queue. Validated sections are written to PostgreSQL: one row in `sections`, multiple rows in `sub_sections`, cross-reference rows in `cross_references`. Law transition mappings are populated in `law_transition_mappings` from the official comparative tables, with confidence scores and approval status. Only sections with `extraction_confidence >= 0.7` and approved mappings proceed to Qdrant indexing. Each section's clean `legal_text` is embedded by BGE-M3 (producing dense + sparse vectors simultaneously). The point is upserted into the appropriate Qdrant collection with its full payload. The extraction audit table records the outcome.

The result: PostgreSQL holds the ground truth (structured facts, relationships, transition mappings, offence classifications). Qdrant holds the semantic retrieval index (embedded text, payload for filtering). At query time, the StatuteNormalizationTool queries PostgreSQL deterministically. The RetrievalSpecialist queries Qdrant semantically with metadata filters derived from the PostgreSQL lookup. The CitationVerifier confirms retrieved section numbers against PostgreSQL before any citation reaches the user. The legal system's data integrity rests on PostgreSQL; its intelligence rests on Qdrant. Neither can substitute for the other, and neither can function correctly without the data quality work described in Parts 1 through 7.

---

## Appendix A — Noise Pattern Quick Reference

| Noise Type | Detection Pattern | Action |
|---|---|---|
| Footnote definition | Line starts with `\d{1,2}\s+Section\s+\d+` | Remove entire line |
| Inline footnote reference | Superscript number mid-sentence (font size < 70% of body) | Remove character |
| Comparison bracket | `\[old_amount\]` adjacent to contradicting amount | Remove bracket + content |
| Comparison block | Line starts with `COMPARISON WITH`, `Consolidation and Modifications`, `Modification & Addition` | Remove to next section heading |
| Page number | Line is solely `\d+` or `— \d+ —` | Remove entire line |
| Running header | Line is exact Act name and year, or chapter name alone | Remove entire line |
| Old law text in new law field | Section content from a different section_number appears in `legal_text` | Discard entire legal_text, re-extract |

## Appendix B — field_name Standardisation Across Acts

The existing JSON uses `bns_section`, `bnss_section`, `bsa_section` as the section number field name — different names for the same concept across the three files. In PostgreSQL, the field is universally `section_number`. The `act_code` field identifies which act it belongs to. No act-specific field names survive past ingestion.

Similarly, `replaces_ipc`, `replaces_crpc`, `replaces_iea` in the JSON are collapsed into a single relationship in the `law_transition_mappings` table. The act-specific field names in the JSON are an artefact of producing three separate JSON files; the database schema is unified.

## Appendix C — Fields Deliberately Excluded from Qdrant Payload

Some fields from PostgreSQL are intentionally not mirrored in the Qdrant payload because they are not useful for filtering at retrieval time and would inflate payload size, increasing memory usage per collection point.

`extraction_confidence` is not in Qdrant because only sections above the threshold are indexed — a low-confidence section does not exist in Qdrant, so the field is redundant. `internal_refs` and `external_refs` JSONB arrays are in PostgreSQL only — they are used by the Legal Reasoner after retrieval, not for retrieval itself. `user_correct_votes` and `user_wrong_votes` from `law_transition_mappings` are PostgreSQL-only operational fields, not relevant to semantic search. `approved_by` and `approved_at` are audit fields that live entirely in PostgreSQL.

---

*Document prepared for Neethi AI engineering team, February 2026. All schema definitions are implementation-ready specifications. No Python code included by design — language-agnostic specifications that any backend implementation can follow.*
