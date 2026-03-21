# TODO

## A2 benchmark gap (delta -0.50)

### Benchmark results (Dutch, Cohen's d = 0.47)

- A0: +1.60
- A1: +0.80
- A2: -0.50
- Overall: +0.63

### What was fixed

- [x] Gradient within known band (0.05–0.45 instead of flat 0.30)
- [x] Dropped bigram fallback — only dep-based extraction (amod, compound, obj)
- [x] Per-level phrase cap (A2: max 2, others: max 3)
- [x] Per-level threshold config (all at 0.5 — lowering didn't help)
- [x] Collocation whitelist from OpenSubtitles (9K bigrams)
- [x] Separable verbs ranked by reconstructed form (meespelen=8394 not spelen=400)
- [x] Relaxed phrase band filter (>= 0.6 instead of >= 1.0)
- [x] VERB+NOUN requires whitelist match
- [x] Separable verb display format — `join_separable` flag (joined for bench, pipe for API)
- [x] Compound word rejoining — adjacent NOUN+NOUN via compound deprel, surface fallback for unsplit words
- [x] ADJ surface form in phrases — "digitale munt" not "digitaal munt"
- [x] Noise: plaatsvinden — compound-aware scoring demotes beyond-target compounds with known-band parts
- [x] Noise: iers universiteit — demonym ADJ filter in phrase extraction (capitalized ADJ skipped)
- [x] Noise: non-dom — hyphenated jargon filter (hyphenated tokens not in freq list dropped)
- [x] Separable verb dedup — standalone suppressed when separable form exists
- [x] Repetition boost — multiplicative: weight × count, near-boundary words cross 0.5 at 2+ occurrences
- [x] Compound scoring bug — target-band compounds (hoofdpijn) no longer demoted by known-band parts

### Remaining A2 misses (66 total)

#### 1. Single known-band words (26 misses) — biggest gap

Words the LLM picks because they're contextually important, but we filter as "too common." Almost all have 1 occurrence so repetition boost can't help.

**rank < 500** (13 words): zien, tijd, idee, begrijpen, werken, stoppen, proberen, kans, lopen, gebruiken, plek, veilig, belangrijk — arguably too basic for A2

**rank 500–1000** (7 words): lichaam, verliezen, trots, lezen, schrijven, verkopen ×2 — genuinely useful

**rank 1000–1500** (6 words): bedrijf ×2, regelen, wedstrijd, regering — near boundary, most valuable

#### 2. Target-band crowded out (6 misses)

Score 1.0 but don't make top-15: netwerk, niveau, materiaal, tijdschrift, besluiten, verslaan

#### 3. Beyond/unknown singles (10 misses)

Domain words or inflected forms not in freq list: rijke, leiders, crypto-industrie, blockchain-netwerk, handelsrobot, investeren, symptoom, infectie, peptide, schoner

#### 4. Multi-word phrases (21 misses) — second biggest gap

Collocations the LLM generates that our dep-parse doesn't extract:
- VERB+particle: spelen mee, uitkijken naar, doorgaan naar, oplossen in
- ADJ+NOUN: kunstmatige intelligentie, passief inkomen, geautomatiseerde handel, slim contract
- VERB+NOUN: afspraak maken, toegankelijk maken, plaats overnemen, aandacht krijgen
- Complex: medische hulp zoeken, op tijd hulp zoeken, winstgevend worden, gestorven zijn, snel herkennen, ogen hebben voor, platform groeien, aantrekkelijk worden, vechten om

#### 5. Compounds Stanza splits (3 misses)

hoofdpijn (×2), samenbrengen — `_clean_lemma` rejoins correctly, but were being demoted by compound scoring bug (now fixed)

### TODO — structural

- [ ] **Dense collocation whitelist** — run full 105M-line corpus on GPU. Currently 1304 VERB+NOUN bigrams from 4M tokens — no specific fail yet from sparse whitelist but will matter as we add more phrase types.
