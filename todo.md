# TODO

## A2 benchmark gap (delta -1.00)

### Current state

Benchmark results (Dutch):
- A0: +1.50 (pipeline wins)
- A1: +0.10 (tie)
- A2: -1.00 (LLM wins)
- Overall: +0.20

### What was fixed

- [x] Gradient within known band (0.05–0.45 instead of flat 0.30)
- [x] Dropped bigram fallback — only dep-based extraction (amod, compound, obj)
- [x] Per-level phrase cap (A2: max 2, others: max 3)
- [x] Per-level threshold config (reverted to 0.5 for all — lowering didn't help)
- [x] Collocation whitelist from OpenSubtitles (9K bigrams, bypasses rank caps)

### Three remaining problems

1. **Noisy dep phrases.** VERB→NOUN (obj) produces bad collocations like "begrijpen verandering". Also "plaatsvinden" appears as a false positive single.

2. **Missing phrasal verbs.** LLM picks "plaats overnemen", "spelen mee", "uitkijken naar" — these are VERB+ADP / separable verb patterns. We dropped VERB+ADP bigrams because they were noisy, but the good ones are exactly what A2 learners need.

3. **Missing compounds.** LLM picks "blockchaintechnologie", "kunstmatige intelligentie" — multi-word compounds that our pipeline splits into separate singles.

### Possible next steps

- [ ] Fix VERB+NOUN dep noise (tighter filtering or require collocation whitelist match)
- [ ] Re-add phrasal verb extraction (VERB+ADP) with better quality control
- [ ] Handle multi-word compounds (adjacent ADJ+NOUN with strong collocation signal)
- [ ] Build denser collocation whitelist (full 105M-line corpus on GPU) to use as a requirement instead of bypass
