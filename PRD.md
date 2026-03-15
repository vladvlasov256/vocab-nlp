# PRD: Vocabulary Extraction Pipeline (v4)

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

**Now (v4 scope):**

| Language | Code | Key Challenges |
|----------|------|----------------|
| Dutch    | `nl` | Separable verbs (`opbellen` → `bel...op`), compound nouns (`slaapzak`) |
| Serbian  | `sr` | Cyrillic/Latin script, noun compounds |

**Planned (design for, don't implement yet):**

| Language | Code | Key Challenges |
|----------|------|----------------|
| Turkish  | `tr` | Agglutinative morphology, compound verbs |
| Greek    | `el` | Compound nouns, NER for proper nouns |

The microservice loads all active language models at init time into a single container (captured by Modal memory snapshot). Adding a language = adding one `stanza.Pipeline(lang)` call to init + language-specific extraction rules. No architectural changes needed.

## Architecture

```
[Lesson text] → [NLP Microservice] → [Candidate JSON] → [LLM prompt] → [Vocabulary for user]
                  (Steps 1-2)                              (Step 3, existing bot)
```

The microservice handles Steps 1-2. Step 3 stays in the bot's existing LLM flow.

### Step 0: Text Trimming ✅

The service must aggressively trim input text before NLP processing to minimize latency and noise:

- Strip HTML tags, markdown formatting, URLs, email addresses
- Remove source attribution lines, bylines, image captions
- Collapse repeated whitespace and blank lines
- Truncate to a maximum of 10 sentences (drop the rest — vocab from a 150-word A2 text doesn't need more)
- Reject texts under 2 sentences (not enough context for meaningful extraction)

Stanza processing time is linear in text length. Every unnecessary token costs ~1ms. For a 10-sentence A2 text this is marginal, but the service should never waste cycles on boilerplate that the news adapter or LLM left in.

### Step 1: Linguistic Preprocessing (Stanza) ✅

- Load language-specific Stanza pipeline: `tokenize, pos, lemma, depparse, ner`
- Extract: tokens, POS tags, lemmas, dependency relations, named entities, noun chunks
- Stanza chosen over spaCy for higher accuracy on low-resource languages (Serbian, Turkish) — 2-5% better on UD benchmarks
- CPU-only (`use_gpu=False`), sufficient for short texts (<1s per 10 sentences)

**Output:** Structured token list with POS, lemma, dependency, and NER annotations.

### Step 2: Phrase Extraction & Ranking

Two sub-steps:

#### 2a. Candidate Extraction

- **YAKE** (Yet Another Keyword Extractor) for language-agnostic keyphrase extraction (unigrams through trigrams, top 20-30)
- ✅ **Noun chunks** from Stanza dependency parse
- **Language-specific rules:**
  - ✅ Dutch: group particles (`advmod`) with verbs to reconstruct separable verbs; compound splitter for long nouns
  - Turkish: morpheme-aware splitting for compounds
  - Serbian/Greek: NER + noun compound patterns

PhraseMachine is **not used** — it is English-only and does not handle the target languages.

#### 2b. Ranking

- ✅ **Exact match** against CEFR A2 frequency lists → score 1.0
- **Partial match** for multiword phrases: percentage of component words found in A2 list
- ✅ **Frequency proxy** fallback: corpus frequency rank (top-1000 = A1-A2, 1000-2000 = A2-B1)
- ✅ Filter: threshold > 0.5, limit to top 15 items

**CEFR frequency lists per language:**

| Language | Source |
|----------|--------|
| Dutch    | NT2Lex (17k graded items, includes MWEs) |
| Turkish  | TOMER CEFR frequency lists |
| Serbian  | Wikipedia frequency + CEFR adaptation (top-2000) |
| Greek    | Wikipedia frequency + CEFR adaptation (top-2000) |

### Step 3: LLM Enrichment (existing bot, not in microservice)

The bot sends the candidate list to the LLM with a prompt like:

> "From these candidates, produce A2-level vocabulary: translate to [user language], add a simple definition and an example sentence from the original text."

This step already exists in the bot. The microservice only provides better input.

## API Contract

### Request

```
POST /extract
Content-Type: application/json

{
  "text": "De minister wil de sociale zekerheid hervormen...",
  "lang": "nl"
}
```

### Response

```json
{
  "language": "nl",
  "lemmas": [
    { "text": "sociale zekerheid", "pos": "NOUN", "span": [3, 5], "weight": 0.95, "is_a2": true },
    { "text": "opbellen", "pos": "VERB", "span": [12, 13], "weight": 0.87, "is_a2": true },
    { "text": "hervormen", "pos": "VERB", "span": [8, 9], "weight": 0.62, "is_a2": false }
  ]
}
```

**Fields:**
- `text` — lemmatized form (reconstructed for separable verbs)
- `pos` — Universal POS tag (NOUN, VERB, ADJ, PROPN)
- `span` — token indices in original text
- `weight` — 0-1 relevance score (CEFR match + frequency)
- `is_a2` — whether the lemma appears in the A2 frequency list

## Tech Stack

| Component | Choice | Reason |
|-----------|--------|--------|
| NLP       | Stanza | Best multilingual accuracy on CPU |
| Keyphrases | YAKE  | Unsupervised, language-agnostic, no training needed |
| API       | FastAPI (Python) | Lightweight, async, easy deploy |
| Hosting   | Modal  | Free tier ($20/mo credits), no bundle size limits, container-based, good for ML workloads |

### Why not JS?

JS NLP libraries (WinkNLP, Compromise) achieve ~80-85% accuracy vs Stanza's 95%+ on UD benchmarks. For Dutch/Turkish/Serbian/Greek, the gap is larger. A separate Python microservice is worth the operational cost.

### Why not pure LLM?

- NLP pre-filtering reduces LLM hallucinations (80-90% relevant phrases vs ~50% with pure LLM)
- Cheaper: NLP step is free (CPU), reduces LLM prompt size
- Faster: NLP < 1s, targeted LLM prompt is smaller and faster
- Deterministic: same text always produces the same candidates

## Hosting: Modal

- **Free tier:** $20/month credits (sufficient for 100k+ inferences)
- **Cold start:** 1-3s container boot + model load, mitigated by memory snapshots (snapshot persists initialized Stanza pipelines, so subsequent cold starts skip model loading — just container boot ~1-2s)
- **Warm latency:** < 500ms per request
- **Deploy:** `modal deploy app.py`
- **Models:** stored in Modal volumes (~200MB per language, ~800MB total for 4 languages)

### Why cold starts don't matter

The vocab extraction runs during lesson generation, in parallel with MCQ question generation (`Promise.all` in `reading.ts`). The lesson flow already takes 5-10+ seconds (LLM text adaptation → MCQ generation → TTS audio). A 2-3s cold start is completely hidden behind work that's already happening. Even a worst-case 5s cold start on the very first lesson of the day adds no perceived latency.

Traffic clusters in morning/evening windows (lesson time). One cold start per session, then warm for the rest. No need for keep-alive pings burning credits on idle compute.

### Why not Vercel

Vercel serverless functions have a 250MB compressed bundle limit. Stanza + PyTorch CPU (~150-200MB) plus 4 language models (~120-200MB) totals 300-400MB — exceeds the limit. Even with aggressive tree-shaking, PyTorch CPU alone is borderline.

## Performance Requirements

| Metric | Target |
|--------|--------|
| Latency (warm) | < 1s per text |
| Latency (cold) | < 5s |
| Text size | Up to 500 words / 10 sentences |
| Output | 10-15 lemmas per text |
| Throughput | 1000+ requests/day |
| Cost | < $0.01 per extraction (NLP only, no LLM) |

## Integration with Bot

The bot calls the microservice during lesson generation (reading/listening tasks), before the vocabulary prompt:

```
1. Fetch news article
2. LLM adapts text to A2 level
3. POST /extract with adapted text  ← NEW
4. LLM generates vocabulary using candidate list  ← IMPROVED (was: from scratch)
5. Present vocabulary to user
```

## Future: Level-Aware Filtering

Accept learner level (A0, A1, A2) as an input parameter. The level controls which words are considered "already known" and filtered out:

| Level | "Known" band | Effect |
|-------|-------------|--------|
| A0 | top ~500 | Surface almost everything — even basic words are new |
| A1 | top ~1000 | Skip the most basic words, show A2-level vocab |
| A2 | top ~2000 | Skip common words, surface B1-level vocab |

This shifts the weight function's rank bands and the filtering threshold so that an A0 learner sees "groot" and "klein" while an A2 learner skips them in favor of less frequent words like "hervormen".

## Open Questions

- [ ] Should PROPN (proper nouns like "Angela Merkel") be included or filtered out?
- [ ] Should the ranking step use the learner's **known vocabulary** (from past lessons) to deprioritize already-learned words?
- [ ] Is Modal the right long-term host, or should this move to a sidecar on the Vercel deployment?
- [ ] Which CEFR lists are freely available and redistributable for Serbian and Greek?

## References

- [Stanza](https://stanfordnlp.github.io/stanza/) — Stanford NLP library
- [YAKE](https://github.com/LIAAD/yake) — unsupervised keyword extraction
- [NT2Lex](https://aclanthology.org/W18-0514/) — Dutch CEFR-graded lexicon
- [PhraseMachine](https://github.com/slanglab/phrasemachine) — English-only, evaluated and rejected
- [KB Dutch Compound Splitting](https://kdutch.ivdnt.org/wiki/Compound_splitting)
- [spacy-stanza bridge](https://pypi.org/project/spacy-stanza/)
