# Benchmark Data Generation Brief

## Goal

Generate 15 benchmark texts (5 per level: A0, A1, A2) in Dutch, with LLM-generated vocabulary lists for each. This data will be used to evaluate and tune the vocab-nlp pipeline.

## What to build

A script that:

1. **Fetches 5 news articles** from GNews API (English, from hardcoded topics: Business, Technology, etc.)
2. **Adapts each article 3 times** using the existing text adaptation prompt — once for each level (A0, A1, A2)
3. **Generates a vocabulary list** for each adapted text using the current v1 vocab prompt
4. **Saves the output** to `bench/` in this repo

## Output structure

```
bench/
  texts/
    nl_a0_01.txt    # adapted text only (no metadata)
    nl_a0_02.txt
    ...
    nl_a1_01.txt
    ...
    nl_a2_05.txt
  baseline/
    nl_a0_01.json   # LLM vocab output
    nl_a0_02.json
    ...
```

### Text file format

Plain text, no metadata. Just the adapted article.

### Baseline JSON format

```json
{
  "level": "A1",
  "lemmas": ["vinden", "huis", "munt", "goud", "belangrijk"]
}
```

Just the vocabulary words the LLM picked, as a flat list of lemmas. No translations, no definitions — we only need the word selection for comparison.

## Secrets

The script should read the current `.env` file for `GNEWS_API_KEY` and `OPENAI_API_KEY`.

## Requirements

- Use the **same adaptation prompts** the bot uses in production (reading task flow)
- Use the **same vocab extraction prompt** the bot currently uses (v1)
- Each adapted text should be 5-10 sentences (same as production)
- Pick one article per topic to ensure diversity (Business, Technology, Sports, Science, Health, etc.)
- Script should be re-runnable (idempotent, overwrites existing files)

## Not needed

- Translations or definitions
- MCQ generation
- Audio/TTS
- User-facing formatting
