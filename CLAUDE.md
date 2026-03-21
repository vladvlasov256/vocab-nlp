# vocab-nlp (lemma)

Multilingual NLP microservice that extracts vocabulary candidates from short texts. Built for language learning apps targeting A0-B1 learners.

## Tech Stack

- **Runtime:** Modal (serverless, CPU-only)
- **NLP:** Stanza (tokenize, POS, lemma, depparse, NER)
- **API:** FastAPI via Modal's `@fastapi_endpoint`
- **Package manager:** uv

## Commands

```
uv sync                       # install deps
uv run modal serve app.py     # local dev (hot reload)
uv run modal deploy app.py    # deploy to Modal
```

## Languages

- **Active:** Dutch (`nl`), Serbian (`sr`)
- **Planned:** Turkish (`tr`), Greek (`el`)

All models loaded at container init, captured by Modal memory snapshot.

## API

```
POST /extract
{"text": "...", "lang": "nl"}
```

## Architecture

See PRD.md for full pipeline design. In short:

```
Step 0: Trim text (strip HTML, cap at 10 sentences)
Step 1: Stanza (tokenize, POS, lemma, depparse, NER)
Step 2: Phrase extraction + CEFR ranking (YAKE, frequency lists)
→ JSON candidates returned to caller (bot's LLM does translation)
```

## Modal Config

- `@app.cls` (not `@app.function`) — required for `enable_memory_snapshot` + `@modal.enter(snap=True)`, which snapshots loaded Stanza models so cold starts skip download/load. This means the endpoint is `VocabNlp.extract`, not just `extract`.
- `max_containers=1` — low traffic, single container is sufficient
- CPU-only (`cpu=1`, `use_gpu=False`) — Stanza performs well on CPU for short texts; GPU containers are significantly more expensive on Modal

## Benchmarks

- Do NOT run benchmarks unless explicitly asked by the user.
- Use `--text` to run a specific test: `uv run python bench/run.py --lang nl --text nl_a2_01`
- Use `--level` to filter by level: `uv run python bench/run.py --lang nl --level A2`

## Consumer

YourDutchBot — called during lesson generation, in parallel with MCQ generation.
