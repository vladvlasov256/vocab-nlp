# vocab-nlp

Multilingual NLP microservice that extracts vocabulary candidates from short texts. Built for language learning apps targeting A0-B1 learners.

> Deterministic, fast, and cheaper than pure LLM extraction. Beats GPT vocab picking by Cohen's d = 1.51 on a 30-text Dutch benchmark.

![CLI screenshot](docs/cli.png)

## Pipeline

```
Input text → Trim → Stanza NLP → Heuristics → Ranked candidates
```

### Step 0: Trim

Collapse whitespace, cap at 4KB. No HTML parsing, no sentence splitting — expects clean adapted text.

### Step 1: Stanza

Tokenize, POS-tag, lemmatize, and dependency-parse the text. CPU-only, <1s for 10 sentences.

**Processors:** `tokenize, pos, lemma, depparse`

### Step 2: Extract & Rank

Collect NOUN, VERB, ADJ tokens, then apply heuristics:

**Separable verb reconstruction** (Dutch) — Stanza marks verb particles with `compound:prt`. "Hij belt zijn moeder op" → particle "op" + verb "bellen" → reconstructed lemma "opbellen".

**Compound rejoining** — Stanza sometimes lemmatizes Dutch compounds with underscores: "doorzettingsvermogen" → "doorzetting_vermogen". We try rejoining the parts with common Dutch connectors (direct, -s-, -e-, -en-, -er-) and validate against the frequency list. If "doorzettingsvermogen" exists in SUBTLEX-NL, use it. Otherwise fall through as-is.

**Demonym filtering** — Uppercase adjectives like "Israëlisch", "Palestijns" are filtered out. These are derived from proper nouns and aren't useful vocabulary items.

**Proper noun separation** — PROPN tokens go to a separate list, not mixed with vocabulary candidates.

**CEFR frequency ranking** — Each lemma is scored by its rank in a corpus frequency list (SUBTLEX-NL for Dutch, Wikipedia 50k for Serbian). Scoring is level-aware:

| Learner level | "Known" band | "Target" band | Effect |
|---------------|-------------|---------------|--------|
| A0 | top 0 | top 500 | Everything is new |
| A1 | top 500 | top 1500 | Skip basics |
| A2 | top 1500 | top 3000 | Skip common words |
| B1 | top 3000 | top 6000 | Surface advanced vocab |

Words in the target band score 1.0, known band scores 0.3, beyond/unknown score 0.6. Output is sorted by weight, filtered at 0.5, capped at 15 lemmas.

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
  "lemmas": [
    {"text": "hervormen", "pos": "VERB", "weight": 1.0, "in_target": true},
    {"text": "minister", "pos": "NOUN", "weight": 0.6, "in_target": false}
  ],
  "proper_nouns": []
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

Displays three panels: **Candidates** (above threshold), **Filtered out** (below threshold), and **Proper nouns**.

## Benchmark

30 Dutch texts (10 per level: A0, A1, A2) evaluated by GPT-5 as blind judge. Pipeline vocab list vs LLM baseline, scored 1-5 on relevance, coverage, and noise. Cohen's d = 1.51 (large effect).

```bash
uv run --group bench python bench/run.py
```

| Level | Pipeline avg | LLM avg | Delta |
|-------|-------------|---------|-------|
| A0 | 4.6 | 2.4 | +2.20 |
| A1 | 4.3 | 3.0 | +1.30 |
| A2 | 4.4 | 3.5 | +0.90 |
| **Overall** | **4.4** | **3.0** | **+1.47** |

### Known issues

- **"vroeger" lemmatized as "vroeg"** — Stanza and Wiktionary both treat "vroeger" as the comparative of "vroeg" (early), but in most contexts it's a separate word meaning "formerly." No clean fix without word-sense disambiguation.
- **Common verbs filtered at A2** — verbs like "veranderen" (rank 626) fall in the A2 known band and get filtered, but a judge considers them useful. Narrowing the known band reintroduces noise.

## Languages

| Language | Code | Status | Frequency list | Lemma overrides |
|----------|------|--------|---------------|-----------------|
| Dutch | `nl` | Active | SUBTLEX-NL (400k lemmas) | Wiktionary via kaikki.org (370k) |
| Serbian | `sr` | Active | srLex 1.3 (105k lemmas) | srLex 1.3 (1.7M) |
| Turkish | `tr` | Planned | — | — |
| Greek | `el` | Planned | — | — |

## Setup

```bash
uv sync                       # install deps
uv run python cli.py          # local testing
uv run modal serve app.py     # local dev with hot reload
uv run modal deploy app.py    # deploy to Modal
```
