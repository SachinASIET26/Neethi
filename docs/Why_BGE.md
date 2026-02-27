Good, these are two sharp questions that deserve precise answers. Let me take them one at a time, starting with the embedding model decision since that has deeper technical reasoning, then the URL field question which has a cleaner answer.

---

## Why BGE-M3 and Not InLegalBERT

The framing of this question contains a common and understandable assumption — that a model trained on domain-specific data should always outperform a general-purpose model in that domain. This is true for classification, NER, and NLI tasks, where InLegalBERT genuinely shines. But for **retrieval**, the situation is fundamentally different, and the reason comes down to what kind of model InLegalBERT actually is.

### InLegalBERT Was Not Built for Retrieval

InLegalBERT, developed by IIT Kharagpur and trained on 5.4 million Indian legal documents, is a **Masked Language Model (MLM)**. That means it was trained with the objective of predicting masked tokens — essentially, "fill in the blank" training on legal text. This makes it an exceptional model for understanding Indian legal vocabulary, legal reasoning patterns, and domain-specific terminology.

However, an MLM is **not a sentence embedding model**. When you pass a sentence through InLegalBERT, what you get back is a sequence of token-level hidden states — one 768-dimensional vector per token. To get a single vector that represents the entire passage (which is what Qdrant needs to do similarity search), you have to pool those token vectors — typically by averaging them or taking the `[CLS]` token. But this pooling produces vectors that are **not trained to be semantically comparable**. Two passages that are legally similar will not necessarily have similar pooled vectors from a raw MLM, because the model was never trained with the objective of making similar texts close together in vector space.

To make InLegalBERT suitable for retrieval, you would need to convert it into a **Sentence Transformer** — add a pooling head and fine-tune it with **contrastive learning** on legal passage pairs, where you explicitly train the model so that semantically similar legal passages end up near each other in the embedding space. This is a serious engineering project in itself, requiring two to four weeks of work, a manually annotated dataset of at least two thousand Indian legal query-passage pairs, and several GPU hours for fine-tuning. Your project's embedding comparison document evaluated this path and concluded it should be treated as a Phase 2 investment — after the system is live and you can build a proper evaluation dataset.

The practical consequences of using InLegalBERT raw without this fine-tuning are severe. Your retrieval quality would likely be worse than even a generic model like `all-MiniLM-L6-v2`, because the pooled MLM vectors have no incentive to cluster similar legal passages together.

### The Token Limit Is Disqualifying on Its Own

Even if you did invest in fine-tuning InLegalBERT into a sentence transformer, there is a second hard constraint that cannot be solved through fine-tuning: its **512-token maximum context window**.

Think about what a Supreme Court judgment chunk actually looks like. The paragraph-aware chunking strategy you're using targets 400–500 tokens per chunk, which fits within 512 — but only barely, and with no room for the asymmetric query prefix that BGE-M3 uses. More critically, many legal paragraphs in SC judgments exceed 512 tokens, particularly in the analysis and reasoning sections where judges write extended arguments. Every time a chunk is truncated at 512 tokens, you lose the tail of the legal reasoning — often the most important part, where the court reaches its conclusion. With a 8,192-token model like BGE-M3, you can embed entire legal arguments as single chunks without truncation.

### What BGE-M3 Offers That No Specialized Model Can Match

BGE-M3 was chosen not despite being general-purpose, but because of a specific set of capabilities that happen to be uniquely well-suited to the Neethi use case.

The first is **native hybrid output**. BGE-M3 is the only model that produces both a dense vector (for semantic similarity) and a sparse vector (BM25-style lexical matching) in a single forward pass. This is architecturally crucial for legal retrieval, where a query like "Section 302 read with Section 34" needs to match not just semantically similar passages but passages that contain the exact string "Section 302" or "Section 34." Without sparse vectors, pure semantic search would find passages about murder and joint liability but might miss the specific section reference. With sparse vectors, exact term matching is built in. Every other model in the comparison requires a separate BM25 pipeline to achieve this, doubling your infrastructure complexity.

The second is **multilingual coverage**. BGE-M3 supports 100+ languages including Hindi, Tamil, Telugu, Kannada, Malayalam, Bengali, Marathi, and Gujarati. This aligns directly with the Sarvam AI translation integration planned for Neethi's multilingual support. When a user submits a query in Hindi, BGE-M3 can embed it in the same vector space as English judgment chunks — meaning a Hindi query can retrieve English judgment text without requiring a translation step before retrieval.

The third is the **8,192-token context window**, already discussed, which eliminates truncation concerns for any realistic legal passage.

### The Honest Comparison

Looking at the numbers from your embedding comparison study, for the Indian legal domain specifically, the ranking on retrieval quality is estimated as:

InLegalBERT **after proper fine-tuning as a sentence transformer** would likely rank first for English Indian legal text specifically. But BGE-M3 out of the box scores an estimated NDCG@10 of around 52% on legal retrieval tasks, while InLegalBERT raw (without fine-tuning) would score substantially lower because its vectors are not optimized for retrieval at all. The fine-tuned InLegalBERT-ST is absolutely worth investing in once Neethi is live and you have a proper evaluation dataset — your own project documentation explicitly recommends this as a Phase 2 goal. But right now, with time constraints and no annotated retrieval training data, BGE-M3 is the right choice by a significant margin.

---

## Is the Empty `ik_url` Field Actually Required?

The short answer is no — it is not *required* to store an empty string. But storing it is a deliberate and worthwhile schema decision, and understanding why helps clarify the thinking behind the design.

### The Problem with Omitting It Entirely

If you simply don't include `ik_url` in the Qdrant payload at all during the initial ingestion, you have two options when you later want to add it: either re-ingest every point from scratch (re-embedding, re-upserting — expensive and slow), or run a targeted payload-update pass using Qdrant's `set_payload` operation on existing point IDs. The second approach is exactly what the plan calls for, and it works regardless of whether `ik_url` exists in the current payload or not. Qdrant will add a new field to an existing point's payload just as happily as it updates an existing field.

So functionally, you could omit `ik_url` entirely and add it later, and the system would work identically.

### Why Storing an Empty String Is Still the Better Choice

The reason to include it upfront is **schema consistency and forward-compatibility**. When your `ResponseFormatter` or a future `JudgmentFetcherAgent` processes a Qdrant search result, it reads fields from the payload dictionary. If `ik_url` exists in some points but not others, every consumer of that payload must add a defensive check: `url = payload.get("ik_url", "")`. If `ik_url` is always present — even as an empty string — every consumer can simply read `payload["ik_url"]` and check truthiness. It is a small thing, but consistency in payload schemas reduces bugs over time, particularly as more agents and tools are added to the system.

The more important reason is what it communicates in your `ingested_judgments` Supabase table. The `ik_resolved_at IS NULL` partial index lets you efficiently query "give me all judgments that still need URL enrichment." If you had never stored `ik_url` at all, you would need a different mechanism to track enrichment status. By storing it as an empty string from day one and using `ik_resolved_at` as the completion flag, the two systems stay synchronized: Supabase knows which records need enrichment, and Qdrant always has the field ready to receive the value when the enrichment runs.

In practical terms, storing an empty string costs you essentially nothing — it is a few bytes per point in the payload, negligible against the kilobytes of actual legal text stored in the `text` field. The schema discipline it buys is worth more than the storage it costs.

### The Definitive Answer

Include `ik_url` as an empty string in the initial schema. Treat it not as a placeholder for missing data, but as an explicitly declared "pending enrichment" signal. When you run the Indian Kanoon enrichment pass — whether that's next week or three months from now — the update path is clean, the system doesn't need to know which points have URLs and which don't, and the `ik_resolved_at IS NULL` query in Supabase gives you instant visibility into how much of the enrichment is complete. It is a small upfront discipline that pays dividends throughout the lifetime of the project.