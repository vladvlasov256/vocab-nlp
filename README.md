# vocab-nlp

Multilingual NLP microservice that extracts vocabulary candidates from short texts. Built for language learning apps targeting A0-B1 learners.

> Deterministic, fast, and cheaper than pure LLM extraction. Beats GPT vocab picking by Cohen's d = 0.62 on a 15-text Dutch benchmark.

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

15 Dutch texts (5 per level: A0, A1, A2) evaluated by GPT-5 as blind judge. Pipeline vocab list vs LLM baseline (v1 prompt).

```bash
uv run --group bench python bench/run.py
```

| Level | Pipeline avg | LLM avg | Delta |
|-------|-------------|---------|-------|
| A0 | 4.0 | 2.2 | +1.80 |
| A1 | 3.3 | 3.2 | +0.10 |
| A2 | 3.7 | 3.1 | +0.60 |
| **Overall** | **3.7** | **2.8** | **+0.83** |

## Languages

| Language | Code | Status | Frequency list |
|----------|------|--------|---------------|
| Dutch | `nl` | Active | SUBTLEX-NL (400k lemmas) |
| Serbian | `sr` | Active | Wikipedia 50k |
| Turkish | `tr` | Planned | — |
| Greek | `el` | Planned | — |

## Setup

```bash
uv sync                       # install deps
uv run python cli.py          # local testing
uv run modal serve app.py     # local dev with hot reload
uv run modal deploy app.py    # deploy to Modal
```
