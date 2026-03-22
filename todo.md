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
- [x] A2 phrase cap raised from 2 → 3 — matches other levels, unblocks "kunstmatige intelligentie"
- [x] Hyphenated compounds — allow when both parts in freq and both above known band (crypto-industrie)
- [x] Judge hint for separable verbs — Dutch-specific hint so judge equates "meespelen" = "spelen mee"
- [x] peptide lemma — already correct via Wiktionary overrides (Stanza: "peptiden" → "peptide"), no fix needed

### Remaining A2 misses (66 total)

#### 1. Single known-band words (26 misses) — biggest gap

Words the LLM picks because they're contextually important, but we filter as "too common." Almost all have 1 occurrence so repetition boost can't help.

**rank < 500** (13 words): zien, tijd, idee, begrijpen, werken, stoppen, proberen, kans, lopen, gebruiken, plek, veilig, belangrijk — arguably too basic for A2

**rank 500–1000** (7 words): lichaam, verliezen, trots, lezen, schrijven, verkopen ×2 — genuinely useful

**rank 1000–1500** (6 words): bedrijf ×2, regelen, wedstrijd, regering — near boundary, most valuable

**Not fixable** without lowering the known boundary (1500 → ~800), which would flood output with noise from the < 500 range. The LLM baseline picks these from context understanding, which frequency scoring fundamentally can't replicate.

#### 2. Target-band crowded out (6 misses)

Score 1.0 but don't make top-15: netwerk, niveau, materiaal, tijdschrift, besluiten, verslaan. May improve with phrase cap raised to 3 (fewer singles eaten by phrase components).

#### 3. Beyond/unknown singles (10 misses)

- **rijke** → "rijk" (rank 957, known-band). Filtered correctly.
- **leiders** → "leider" (rank 1471, known-band). Filtered correctly.
- **crypto-industrie** → now passes hyphenated filter (both parts in freq, both above known band).
- **blockchain-netwerk** → "blockchain" not in freq list. Not recoverable.
- **handelsrobot** → not in freq, Stanza doesn't split it. Not recoverable.
- **investeren** (7671), **symptoom** (5313), **infectie** (6551) → beyond target, score 0.6. Present but may get crowded out.
- **peptide** (92192) → correctly extracted, judge complaint was from stale run.
- **schoner** (159260) → comparative form, not useful standalone.

#### 4. Multi-word phrases (21 misses) — second biggest gap

**Already extracted, different format (4):**
- spelen mee → we output "meespelen" (separable verb). Judge hint added.
- uitkijken naar → we output "uitkijken" (separable verb). Judge hint added.
- doorgaan naar → we output "doorgaan" (known-band, score 0.39, filtered)
- oplossen in → we output "oplossen" (single verb, ADP dropped)

**Extracted but blocked by phrase cap (3):**
- kunstmatige intelligentie → should now pass with cap raised to 3
- passief inkomen, geautomatiseerde handel → ADJ+NOUN amod, extractable but may be capped

**VERB+NOUN blocked by whitelist (3):**
- afspraak maken, toegankelijk maken, aandacht krijgen → not in collocation whitelist

**Complex phrases beyond current extraction (11):**
- medische hulp zoeken, op tijd hulp zoeken (3+ words)
- winstgevend worden, aantrekkelijk worden, gestorven zijn (ADJ/participle + copula)
- snel herkennen (ADV+VERB), vechten om (VERB+ADP too generic)
- ogen hebben voor (idiom), platform groeien (not a real collocation)
- slim contract → already extracted as "slimme contract" (surface form differs from baseline)
- plaats overnemen → idiomatic

**Not fixable** without LLM-based phrase selection or significantly expanding extraction patterns.

#### 5. Compounds Stanza splits (3 misses) — fixed

hoofdpijn (×2), samenbrengen — `_clean_lemma` rejoins correctly. Compound scoring bug fixed.

### TODO — structural

- [ ] **Dense collocation whitelist** — run full 105M-line corpus on GPU. Currently 1304 VERB+NOUN bigrams from 4M tokens. Would recover "afspraak maken" and other VERB+NOUN pairs blocked by whitelist.
