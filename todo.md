# Benchmark: Pipeline vs LLM (fair item counts)

Bench clips to LLM counts: A0=4, A1=8, A2=12, B1=15.
API unchanged (MAX_LEMMAS=15).

## Results

| Lang | A0    | A1    | A2    | Overall | Cohen's d |
|------|-------|-------|-------|---------|-----------|
| NL   | -0.80 | -1.00 | -0.50 | -0.77   | -0.79     |
| EN   | -1.10 | -0.90 | -0.60 | -0.87   | -0.92     |
| SR   | -0.80 | -0.70 | -1.10 | -0.87   | -1.19     |

LLM wins everywhere. Pipeline never positive at any level/language combination.

NL/EN: A0 worst, A2 best (more slots = more room for error).
SR: reversed — A2 worst (-1.10), A0/A1 best. LLM scored 5.0 on all 10 SR A2 texts.

## Why SR A2 is worst

The SR LLM baseline is heavily phrase-oriented. Nearly every SR A2 text has 3-4 multi-word picks: "poreska politika", "veštačka inteligencija", "liga šampiona", "ukočen vrat", "širiti poruku", "briga za sebe", "pasivan prihod", "preko granica". Pipeline extracts almost none of these — they're either not in the collocation whitelist, not matching extraction patterns, or losing to single words in scoring.

NL/EN LLM baselines are more single-word focused, so the gap is smaller at A2.

## Problem 1: Filler words stealing slots (A0, all langs)

Top-50 words like "have/be/person" (EN), "mens/hebben/zeggen" (NL), "kazati/imati/čovek" (SR) score just above 0.5 via contextual boost and take slots from domain words.

- en_a0_05: "be, week, team, help" vs LLM "game, team, play, final"
- nl_a0_09: "zeggen, mens, ziek, hebben" vs LLM "ziekte, pijn, koorts, oppletten"
- sr_a0_10: "kazati, imati, čovek, meningitis" vs LLM "meningitis, bol u glavi, crvena tačka, upozoravati na"

**Fix:** Raise A0 known-band so these drop below threshold.

## Problem 2: LLM picks phrases, pipeline picks singles (all levels, worst at SR A2)

LLM sends multi-word units. Pipeline splits them into separate words or doesn't extract them at all.

SR A2 examples — LLM picks vs what pipeline sends:
- "poreska politika" → pipeline sends "poreski" (adj alone)
- "veštačka inteligencija" → pipeline has it but it loses to single words
- "liga šampiona" → not extractable (NOUN+NOUN, not ADJ+NOUN)
- "ukočen vrat" → not in collocation whitelist
- "širiti poruku" → not in whitelist (VERB+NOUN but no dep match)
- "briga za sebe" → trigram, can't extract

**Fix:**
- [ ] Add NOUN+NOUN extraction pattern
- [ ] Raise max_phrases cap (currently 2-3)
- [ ] Phrases should rank above singles when collocation-backed
- [ ] SR reflexive verbs ("boriti se", "nastavljati se")

## Problem 3: Verbs underweighted (A0/A1)

LLM picks action verbs (werken, spelen, raditi, pomoći). Pipeline drops them for nouns.

- sr_a0_07: Pipeline "velik, svetski, lider, nauka" vs LLM "raditi, grupa, pomoći, istraživač"
- nl_a0_06: Pipeline misses "werken", "praten"
- en_a0_05: Pipeline misses "play"

**Fix:** Verb boost at A0/A1.

## Problem 4: No differentiation within target band

All target-band words score 1.0. TF-IDF bonus exists but capped at 1.0. With 4-12 slots, which words make the cut is arbitrary among equals.

**Fix:** Uncap weight for sort order, keep 0.5 threshold for filtering.

## Action plan (priority order)

### Quick scoring tweaks
1. [ ] Raise A0 known-band to suppress filler (NL 0→200, EN 0→150, SR 0→100)
2. [ ] Uncap weight for ranking (keep 0.5 threshold, let contextual bonus create gradient)
3. [ ] Verb boost at A0/A1 for all languages

### Phrase extraction improvements
4. [ ] Raise/remove max_phrases cap
5. [ ] Add NOUN+NOUN phrase pattern (for "liga šampiona" type)
6. [ ] Collocation-backed phrases rank above singles
7. [ ] SR reflexive verb handling ("boriti se")
8. [ ] Relax whitelist gate for VERB+NOUN at A2 (currently requires whitelist match)
