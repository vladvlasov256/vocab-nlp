# TODO

## A2 benchmark gap (delta -0.60)

### Benchmark results (Dutch, Cohen's d = 0.47)

- A0: +1.60
- A1: +0.80
- A2: -0.60
- Overall: +0.60

### What was fixed

- [x] Gradient within known band (0.05–0.45 instead of flat 0.30)
- [x] Dropped bigram fallback — only dep-based extraction (amod, compound, obj)
- [x] Per-level phrase cap (A2: max 2, others: max 3)
- [x] Per-level threshold config (all at 0.5 — lowering didn't help)
- [x] Collocation whitelist from OpenSubtitles (9K bigrams)
- [x] Separable verbs ranked by reconstructed form (meespelen=8394 not spelen=400)
- [x] Relaxed phrase band filter (>= 0.6 instead of >= 1.0)
- [x] VERB+NOUN requires whitelist match

### A2 miss analysis

**25 of 31 missed words are in the known band (rank < 1500, score < 0.45).** This is the dominant pattern. The LLM baseline picks these because they're contextually important even if technically "known" at A2.

Breakdown by rank range:
- rank 200–500 (score 0.11–0.17): idee, begrijpen, werken, stoppen, gebruiken — very common, arguably too basic for A2
- rank 500–1000 (score 0.19–0.28): veilig, belangrijk, lichaam, trots, lezen, informatie, schrijven, verkopen — mid-frequency, genuinely useful at A2
- rank 1000–1500 (score 0.32–0.44): bedrijf, regelen, wedstrijd, regering, ervaring, gratis — near the boundary, most valuable

Only 2 misses are target-band words (terugbrengen, uitgeven) — and those ARE in our output as separable verbs (terug|brengen, uit|geven). The judge may not recognize the pipe format.

3 misses are compound words not in freq list (blockchaintechnologie, handelsplatform, handelsrobot) — domain-specific compounds Stanza splits into parts.

### Noise patterns

- **plaatsvinden** (rank 8028, score 0.60): false positive. "Plaats vinden" in text means "take place" but it's a separable verb already reconstructed. Showing as both separable verb AND standalone may be the issue.
- **mooi herinnering**: dep amod phrase, real but not a useful collocation for learning
- **iers universiteit**: "Ierse" mislemmatized, produces bad phrase
- **peptid**: Stanza misspelling of "peptide"
- **non-dom**: proper noun / jargon leaking in
- **digitaal munt**: wrong adjective form (should be "digitale munt")

### TODO

- [ ] **Separable verb display format** — replace pipe with joined form ("terugbrengen" not "terug|brengen"). Judge may not recognize pipe format, costing us points on words we actually have.
- [ ] **Repetition-based boost for known-band words** — if a known-band word appears 2+ times in the text, it's a topic word. Boost its score above the threshold. Addresses 25/31 misses without lowering threshold globally.
- [ ] **Dense collocation whitelist** — run full 105M-line corpus on GPU. Currently 1304 VERB+NOUN bigrams from 4M tokens is too sparse for the whitelist requirement to work.
- [ ] **Compound word rejoining** — "blockchaintechnologie", "handelsplatform" are split by Stanza. Rejoin adjacent nouns when the joined form exists in freq list or dictionary. (Partially implemented for underscored compounds already.)
- [ ] **ADJ surface form in phrases** — "digitaal munt" should be "digitale munt". Use surface form for adjectives in phrase display, keep lemma internally.
- [ ] **Noise: plaatsvinden** — showing as separable verb (plaats|vinden) AND as standalone. Deduplicate.
- [ ] **Noise: iers universiteit** — "Ierse" mislemmatized by Stanza. May need lemma override or demonym filter for phrase components.
- [ ] **Noise: non-dom** — jargon/proper noun leaking through. Not in freq list but scores 0.6.
