---
app_file: gradio_app.py
sdk: gradio
---

# vocab-nlp

Multilingual NLP microservice that extracts vocabulary candidates from short texts. Built for language learning apps targeting A0-B1 learners.

> Deterministic, fast, and cheaper than pure LLM extraction. Extracts single words and multi-word phrases (ADJ+NOUN, VERB+NOUN collocations).

![CLI screenshot](docs/cli.png)

## Pipeline

```
Input text → Trim → Stanza NLP → Singles + Phrases → Ranked items
```

### Step 0: Trim

Collapse whitespace, cap at 4KB. No HTML parsing, no sentence splitting — expects clean adapted text.

### Step 1: Stanza

Tokenize, POS-tag, lemmatize, and dependency-parse the text. CPU-only, <1s for 10 sentences.

**Processors:** `tokenize, pos, lemma, depparse`

### Step 2: Extract & Rank

Collect NOUN, VERB, ADJ, ADV tokens, then apply heuristics. NUM and PROPN go to separate lists. Function words (ADP, PRON, AUX, CONJ) are explicitly dropped — tested as candidates but they take up slots and get flagged as noise (d dropped 0.85→0.46).

**Separable verb reconstruction** (Dutch) — Stanza marks verb particles with `compound:prt`. "Hij belt zijn moeder op" → particle "op" + verb "bellen" → reconstructed lemma "opbellen".

**Compound rejoining** — Stanza sometimes lemmatizes Dutch compounds with underscores: "doorzettingsvermogen" → "doorzetting_vermogen". We try rejoining the parts with common Dutch connectors (direct, -s-, -e-, -en-, -er-) and validate against the frequency list. If "doorzettingsvermogen" exists in SUBTLEX-NL, use it. Otherwise fall through as-is.

**Hyphenated compound rejoining** — Stanza splits hyphenated words into separate tokens: "self-esteem" → "self" + "-" + "esteem", "cross-border" → "cross" + "-" + "border". When parts are linked by `deprel=compound` with a hyphen PUNCT between them, they are rejoined into a single candidate (e.g. "self-esteem").

**Tokenizer fragment merging** — Stanza's tokenizer splits at digit-letter boundaries: "XA90P" → "XA90" + "P", "95p" → "95" + "p". Single-character fragments with `deprel=compound` are merged back into their head token. Single-character NOUNs with a NUM child (unit suffixes like "p" in "95p") are dropped — the number is already captured separately.

**Demonym filtering** — Uppercase adjectives like "Israëlisch", "Palestijns" are filtered out. These are derived from proper nouns and aren't useful vocabulary items.

**Proper noun separation** — PROPN tokens go to a separate list, not mixed with vocabulary candidates. A pre-pass collects all PROPN lemmas upfront; any candidate whose lemma matches a known proper noun is skipped at collection time (catches mis-tagged instances like sentence-initial "CAB" → NOUN). Additionally, Stanza sometimes mis-tags proper nouns as NOUN/ADJ mid-sentence — we catch these by checking if the surface form is capitalized and the lemma is absent from the frequency list (e.g. "zelenski", "iPhona").

**Phrase extraction** — Dependency-based extraction of multi-word collocations:
- ADJ→NOUN (amod): "slim contract", "wetenschappelijk tijdschrift"
- NOUN→NOUN (compound): "bloedvergiftiging"
- VERB→NOUN (obj): "verdienen loon", "geven antwoord"

Phrases are scored using `max(component_weights)` and compete on the same 0–1 scale as singles. A per-level cap limits phrase count (A2: max 2, others: max 3). Phrases above threshold swallow their component singles to avoid duplication. A collocation whitelist built from OpenSubtitles (NPMI-scored bigrams) provides positive signal for phrase quality.

**CEFR frequency ranking** — Each lemma is scored by its rank in a corpus frequency list (SUBTLEX-NL for Dutch, srLex 1.3 for Serbian). Scoring is level-aware with a gradient within the known band:

| Learner level | "Known" band | "Target" band | Effect |
|---------------|-------------|---------------|--------|
| A0 | top 0 | top 1000 | Everything is new |
| A1 | top 500 | top 3000 | Skip basics |
| A2 | top 1500 | top 5000 | Skip common words |
| B1 | top 3000 | top 8000 | Surface advanced vocab |

Words in the target band score 1.0, beyond/unknown score 0.6. Known-band words score on a gradient (0.05–0.45) based on rank position — words near the target boundary score higher than very common words. Output is sorted by score, filtered at 0.5, capped at 15 items.

## API

Deployed on [Modal](https://modal.com) (serverless, CPU-only, memory snapshots for fast cold starts).

```bash
curl -X POST https://<your-modal-url>/extract \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_KEY" \
  -d '{"text": "De minister wil de sociale zekerheid hervormen.", "lang": "nl", "level": "A1"}'
```

**Response:**

```json
{
  "language": "nl",
  "items": [
    {"text": "hervormen", "type": "single", "score": 1.0, "pos": "VERB", "rank": 4521, "in_target": true},
    {"text": "sociaal zekerheid", "type": "noun_phrase", "score": 1.0, "surface": "sociale zekerheid"},
    {"text": "minister", "type": "single", "score": 0.6, "pos": "NOUN", "rank": 8200, "in_target": false}
  ],
  "proper_nouns": [],
  "numbers": []
}
```

### Deploy

```bash
uv run modal deploy app.py
```

## CLI

Interactive TUI for testing the pipeline locally without deploying.

```bash
uv run python cli.py
```

**Controls:**
- Type or paste text, press Enter to analyze
- `Ctrl+E` — change learner level (A0/A1/A2/B1)
- `Ctrl+T` — change weight threshold
- `Ctrl+L` — switch language
- `Up/Down` — input history
- `Ctrl+C` — quit

Displays panels: **Candidates** (above threshold), **Filtered out** (below threshold), **Proper nouns**, **Numbers**, **Merged fragments**, and **Generic phrases** (phrases filtered by rank caps).

## Benchmark

30 texts per language (10 per level: A0, A1, A2) evaluated by GPT-5 as blind judge. Pipeline vocab list vs LLM baseline, scored 1-5 on relevance, coverage, and noise.

```bash
uv run --group bench python bench/run.py --lang nl
uv run --group bench python bench/run.py --lang sr
uv run --group bench python bench/run.py --lang en
uv run --group bench python bench/run.py --text en_a2_03 -v  # single text, print judge prompt
```

### Dutch (v5, with phrases) — Cohen's d = 0.47

| Level | Pipeline avg | LLM avg | Delta |
|-------|-------------|---------|-------|
| A0 | 4.5 | 2.9 | +1.60 |
| A1 | 4.6 | 3.8 | +0.80 |
| A2 | 3.8 | 4.4 | -0.60 |
| **Overall** | **4.3** | **3.7** | **+0.60** |

Serbian and English benchmarks not yet re-run with v5 phrases.

### Known issues

**A2 regression:** Known-band words (rank < 1500) max out at score 0.45 — below the 0.5 API threshold — so contextually valuable words like "stoppen", "wedstrijd", "trots" don't surface. The LLM baseline picks these. See `todo.md` for analysis and possible fixes.

**Dutch:**
- **"vroeger" lemmatized as "vroeg"** — Stanza and Wiktionary both treat "vroeger" as the comparative of "vroeg" (early), but in most contexts it's a separate word meaning "formerly." No clean fix without word-sense disambiguation.

**Serbian:**
- **Minor lemma typos** — Stanza occasionally produces slightly misspelled lemmas (e.g. "dizajan", "svetki"). These are rare and corrected by the downstream LLM during lesson generation.
- **Ambiguous verb forms** — "uči" can lemmatize to "učiti" (learn) or "ući" (enter); Stanza picks based on context and sometimes gets it wrong.

> **Note:** The pipeline output is consumed by an LLM that generates lesson content. Minor lemma imperfections (typos, dialect forms) are corrected at that stage. The pipeline prioritizes picking the right words over perfect spelling.

## Languages

| Language | Code | Status | Frequency list | Lemma overrides |
|----------|------|--------|---------------|-----------------|
| Dutch | `nl` | Active | SUBTLEX-NL (400k lemmas) | Wiktionary via kaikki.org (370k) |
| Serbian | `sr` | Active | srLex 1.3 (105k lemmas) | srLex 1.3 + kaikki.org (2.1M) |
| English | `en` | Active | SUBTLEX-US (74k words) | — |
| German | `de` | Planned | — | — |
| Turkish | `tr` | Planned | — | — |
| Greek | `el` | Planned | — | — |

## Setup

```bash
uv sync                       # install deps
uv run python cli.py          # local testing
uv run modal serve app.py     # local dev with hot reload
uv run modal deploy app.py    # deploy to Modal
```
