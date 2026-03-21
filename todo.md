# TODO

## A2 benchmark gap (delta -1.00)

### Current state

After three rounds of fixes, A2 improved from -1.50 to -1.00 but still loses to LLM baseline.

Benchmark results (Dutch):
- A0: +1.50 (pipeline wins)
- A1: +0.10 (tie)
- A2: -1.00 (LLM wins)
- Overall: +0.20

### What was fixed

- [x] Gradient within known band (0.05–0.45 instead of flat 0.30)
- [x] Dropped bigram fallback — only dep-based extraction (amod, compound, obj)
- [x] Per-level phrase cap (A2: max 2 phrases, others: max 3)
- [x] Collocation whitelist from OpenSubtitles (9K bigrams, bypasses rank caps)

### Remaining A2 issue

Known-band words (rank < 1500) max out at 0.45 — still below the 0.5 API threshold, so they never surface. The LLM baseline picks these words ("stoppen", "wedstrijd", "trots") because they're contextually valuable even if technically "known."

### Possible next steps

- [ ] Lower API threshold or raise gradient ceiling above 0.5 so top known-band words make the cut (design decision: changes output for all levels)
- [ ] Build denser collocation whitelist (full 105M-line corpus on GPU) to use as a requirement instead of bypass
