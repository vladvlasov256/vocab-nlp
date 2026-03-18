# PRD: Vocabulary Extraction Pipeline (v4)

> **Status:** Implemented and benchmarked. Cohen's d = 1.75 vs pure LLM extraction.
> **Next:** Phrase extraction layer — see [PRD-phrases.md](PRD-phrases.md).

## Motivation

Vocabulary extraction has gone through three iterations, each trying to fix the previous one's shortcomings:

- **v1 (pure LLM):** Single prompt asks the LLM to extract vocab from the adapted text. Results are non-deterministic, full of trivially common words ("de", "is", "en"), and miss compound words and multiword expressions entirely.
- **v2 (improved prompts):** Better prompt engineering with explicit instructions for verb phrases, separable verbs, and type annotations. Marginal improvement — the LLM still hallucinates trivial picks and misses morphologically complex items.
- **v3 (frequency pre-filtering + LLM):** JS-side frequency lists (`data/nl.tsv`, `data/sr.tsv`) with rank bands (e.g. 150-7000 for A0) pre-filter candidates before the LLM selects from them. Adds determinism for single words and prevents the worst trivial picks. But the fundamental problems remain:
  - **Separable verbs** like "opbellen" appear in text as "bel" and "op" in different positions — frequency lookup on split tokens can't reconstruct the infinitive.
  - **Compound nouns** like "slaapzak" are single tokens in text but need splitting to teach components; conversely "sociale zekerheid" is two tokens but one concept.
  - **Lemmatization** is absent — Turkish surface forms like "evlerinden" (from their houses) don't match the lemma "ev" in the frequency list.
  - **Phrase detection** is delegated to the LLM, which remains unreliable (benchmark oracle scores 3/5 on vocabulary).

The v3 approach hits a ceiling because frequency lists + tokenization can't solve linguistic structure problems. Dependency parsing, POS tagging, and proper lemmatization are needed — and these require an NLP library (Stanza), not prompt tricks.

## Problem

The bot's vocabulary extraction pipeline (through v3) cannot reliably handle compound words, separable verbs, multiword expressions, or agglutinative morphology. These are structural linguistic problems that frequency lists and LLM prompts alone cannot solve.

## Goal

Build a lightweight NLP microservice that extracts candidate lexemes (single words, compounds, multiword expressions) from short texts (up to 10 sentences) and returns a ranked JSON list. The bot's LLM then uses this list to generate translations, definitions, and examples — replacing the current "extract everything from scratch" approach.

## Target Languages

**Active:**

| Language | Code | Key Challenges | Status |
|----------|------|----------------|--------|
| Dutch    | `nl` | Separable verbs (`op\|bellen`), compound nouns | ✅ Production |
| Serbian  | `sr` | Cyrillic/Latin script, noun compounds | ✅ Production |
| English  | `en` | Demo/benchmark language | ✅ Production |

**Planned:**

| Language | Code | Key Challenges |
|----------|------|----------------|
| Turkish  | `tr` | Agglutinative morphology, compound verbs |
| Greek    | `el` | Compound nouns, NER for proper nouns |

The microservice loads all active language models at init time into separate Modal classes (one per language), each captured by Modal memory snapshot. Adding a language = adding one class with `stanza.Pipeline(lang)` + language-specific extraction rules.

## Architecture

```
[Lesson text] → [NLP Microservice] → [Candidate JSON] → [Bot]
                  (Steps 0-2)
```

The microservice handles Steps 0-2 and returns ranked candidates. Bot-side integration (LLM enrichment, translation, display) is covered in the YourDutchBot repo (`PRD-vocab-v4-integration.md`).

### Step 0: Text Trimming ✅

- Strip HTML tags, markdown formatting, URLs, email addresses
- Collapse repeated whitespace and blank lines
- Cap at `MAX_TEXT_BYTES` (4096)

### Step 1: Linguistic Preprocessing (Stanza) ✅

- Load language-specific Stanza pipeline: `tokenize, pos, lemma, depparse`
- Extract: tokens, POS tags, lemmas, dependency relations
- Wiktionary-based lemma overrides patched into Stanza's composite dict
- CPU-only (`use_gpu=False`), sufficient for short texts (<1s per 10 sentences)

### Step 2: Candidate Extraction & Ranking ✅

#### 2a. Candidate Extraction

- ✅ **POS filtering:** NOUN, VERB, ADJ, ADV collected as candidates; DET, PRON, AUX, CCONJ, SCONJ, PART, INTJ, PUNCT, SYM, X dropped
- ✅ **Separable verb reconstruction:** Dutch `compound:prt` dependency → `op|bellen` format (Duolingo convention). Base verb deduplicated when reconstructed.
- ✅ **Compound lemma rejoining:** Stanza underscore splits (`doorzetting_vermogen`) rejoined with Dutch connectors, validated against frequency list
- ✅ **Surface form fallback:** When Stanza's lemma isn't in freq list but surface form is, use surface form
- ✅ **Proper noun filtering:** PROPN → separate list; mis-tagged proper nouns caught by capitalization + freq list check
- ✅ **Merge logic:** Hyphenated compounds, single-char fragments, num+suffix patterns
- ✅ **Number extraction:** NUM tokens → separate list
- 🔴 **Phrase extraction:** See [PRD-phrases.md](PRD-phrases.md)

#### 2b. Ranking ✅

- ✅ **CEFR band scoring:** known (0.3), target (1.0), beyond (0.6) based on frequency rank relative to learner level
- ✅ **Per-level band cutoffs:** A0/A1/A2/B1 with language-specific known/target thresholds
- ✅ **ADV weight:** Reduced at lower levels (0.7 for A0/A1) to deprioritize adverbs
- ✅ **Threshold filter:** weight > 0.5 removes known-band words
- ✅ **Limit:** Top 15 candidates (`MAX_LEMMAS`)

**Frequency lists:**

| Language | Source | Entries |
|----------|--------|---------|
| Dutch | SUBTLEX-NL (subtitle corpus) | ~400k lemmas |
| Serbian | srLex 1.3 (lemma-aggregated) | ~100k entries |
| English | SUBTLEX-US (subtitle corpus) | ~74k word forms |

### Step 3: LLM Enrichment — out of scope

Bot-side integration (LLM prompt updates, translation, fallback). See YourDutchBot repo: `PRD-vocab-v4-integration.md`.

## API Contract

### Endpoints

Three separate endpoints, one per language:

```
POST /nl/    # Dutch
POST /en/    # English
POST /sr/    # Serbian
```

### Request

```json
{
  "text": "De minister belt bedrijven op om te praten.",
  "level": "A0"
}
```

Authorization: `Bearer <API_KEY>` header.

### Response

```json
{
  "language": "nl",
  "candidates": [
    { "text": "op|bellen", "pos": "VERB", "rank": 423, "weight": 1.0, "in_target": true },
    { "text": "bedrijf", "pos": "NOUN", "rank": 312, "weight": 1.0, "in_target": true },
    { "text": "minister", "pos": "NOUN", "rank": 1842, "weight": 0.6, "in_target": false }
  ],
  "proper_nouns": [
    { "text": "Amsterdam", "pos": "PROPN" }
  ],
  "numbers": [
    { "text": "3500", "pos": "NUM" }
  ],
  "merged_fragments": [
    { "parts": ["cross", "border"], "merged": "cross-border", "rule": "hyphen" }
  ]
}
```

**Fields:**
- `text` — lemmatized form; separable verbs use pipe format (`op|bellen`)
- `pos` — Universal POS tag (NOUN, VERB, ADJ, ADV)
- `rank` — frequency rank in language corpus (null if not found)
- `weight` — 0-1 relevance score based on CEFR band
- `in_target` — whether the word is in the target learning band for this level

## Deployment

### Channels

| Channel | Purpose | Entrypoint |
|---------|---------|------------|
| Modal API | Production (bot calls this) | `app.py` |
| CLI (Textual) | Local testing & development | `cli.py` |
| HF Space (Gradio) | Public demo | `gradio_app.py` |

### Modal Config

- `@app.cls` with `enable_memory_snapshot` — snapshots loaded Stanza models so cold starts skip download/load
- One class per language (Nl, En, Sr) with separate ASGI apps
- `max_containers=1` — low traffic, single container sufficient
- CPU-only (`cpu=1`) — Stanza performs well on CPU for short texts

### Performance

| Metric | Actual |
|--------|--------|
| Latency (warm) | < 500ms |
| Latency (cold, with snapshot) | ~2s |
| Text size | Up to 4096 bytes |
| Output | Up to 15 candidates |
| Cost | < $0.01 per extraction |

## Benchmark

### Dataset

10 texts per level (A0, A1, A2) for Dutch, Serbian, and English = 90 texts total.

Stored in `bench/texts/` with LLM baselines in `bench/baseline/`.

### Evaluation

`bench/run.py` sends both pipeline output and LLM baseline to a GPT-5 judge. Judge scores each list 1-5 on Relevance, Coverage, and Noise.

### Results (Dutch, 30 texts)

| Level | Pipeline avg | LLM avg | Delta |
|-------|-------------|---------|-------|
| A0 | 4.6 | 2.5 | +2.10 |
| A1 | 4.6 | 3.0 | +1.60 |
| A2 | 4.5 | 3.5 | +1.00 |
| **Overall** | **4.6** | **3.0** | **+1.57** |

**Cohen's d = 1.75** (large effect size; pipeline wins ~86% of the time).

## Open Questions

- [x] Should PROPN be included or filtered out? → **Filtered out**, returned in separate `proper_nouns` list.
- [x] Should separable verbs show dictionary form or split form? → **Pipe format** (`op|bellen`), Duolingo convention.
- [x] What should the API field be called? → **`candidates`** (not `lemmas`, since pipe-format verbs aren't standard lemmas).
- [ ] Should the ranking step use the learner's **known vocabulary** (from past lessons) to deprioritize already-learned words?
- [ ] Is Modal the right long-term host, or should this move to a sidecar on the Vercel deployment?

## References

- [Stanza](https://stanfordnlp.github.io/stanza/) — Stanford NLP library
- [NT2Lex](https://aclanthology.org/W18-0514/) — Dutch CEFR-graded lexicon
- [SUBTLEX-NL](http://crr.ugent.be/programs-data/subtitle-frequencies/subtlex-nl) — Dutch subtitle frequency corpus
