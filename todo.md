# TODO

## A2 benchmark gap (delta -0.50)

### Benchmark results (Dutch)

- A0: +1.60
- A1: +0.80
- A2: -0.50
- Overall: +0.63
- Pipeline avg: 4.0, LLM avg: 4.5

### What was fixed

- [x] Gradient within known band (0.05–0.45 instead of flat 0.30)
- [x] Dropped bigram fallback — only dep-based extraction (amod, compound, obj)
- [x] Per-level phrase cap (A2: max 3, others: max 3)
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
- [x] Noise: non-dom — hyphenated jargon filter (requires both parts in freq and above known band)
- [x] Separable verb dedup — standalone suppressed when separable form exists; join_separable moved after dedup
- [x] Repetition boost — multiplicative: weight × count, near-boundary words cross 0.5 at 2+ occurrences
- [x] Compound scoring bug — target-band compounds (hoofdpijn) no longer demoted by known-band parts
- [x] Hyphenated compounds — allow when both parts in freq and both above known band (crypto-industrie)
- [x] Judge hint for separable verbs — Dutch-specific hint so judge equates "meespelen" = "spelen mee"
- [x] peptide lemma — already correct via Wiktionary overrides, no fix needed

### Investigated but not fixed

- **Separable verb parts demotion** — tried adding `_parts` to separable verbs so compound scoring demotes "plaatsvinden" (parts: plaats + vinden, both known-band). But this also demotes "meespelen" (parts: mee + spelen) which the judge wants. Can't distinguish light verbs from real separable verbs without a stop-list. Not worth the collateral damage.
- **kunstmatige intelligentie still blocked** — extracted as phrase (score 0.65) but ranked 4th behind 3 phrases scoring 1.0 (digitale munt, slimme contract, spannend moment). Cap=3 added "spannend moment" instead. Raising cap further would eat too many single slots.

### Remaining A2 misses by category

#### 1. Single known-band words (22 misses) — biggest gap, not fixable

Single-occurrence words the LLM picks as contextually important but we filter as "too common."

| Range | Words | Fixable? |
|---|---|---|
| rank < 500 (11) | zien, tijd, idee, begrijpen, werken, stoppen, proberen, kans, lopen, plek, belangrijk | No — too basic |
| rank 500–1000 (6) | lichaam, verliezen, trots, lezen, schrijven, verkopen | No — 1 occurrence |
| rank 1000–1500 (5) | bedrijf ×2, regelen, wedstrijd, regering | No — 1 occurrence |

Lowering known boundary (1500 → 800) would recover rank 1000–1500 words but flood output with rank < 500 noise.

#### 2. Multi-word phrases (17 misses) — second biggest gap

| Type | Examples | Fixable? |
|---|---|---|
| Format diff — sep. verbs (3) | spelen mee, uitkijken naar, doorgaan naar | Judge hint added |
| Phrase cap overflow (1) | kunstmatige intelligentie | Investigated, not without trade-off |
| VERB+NOUN not in whitelist (3) | afspraak maken, toegankelijk maken, aandacht krijgen | Dense whitelist would help |
| 3+ word phrases (4) | medische hulp zoeken, op tijd hulp zoeken | No — beyond bigram extraction |
| ADJ/participle + copula (3) | winstgevend worden, aantrekkelijk worden, gestorven zijn | No — not a dep pattern we extract |
| Other (3) | ogen hebben voor (idiom), snel herkennen (ADV+VERB), vechten om | No |

#### 3. Target-band crowded out (4 misses)

Score 1.0 but don't make top-15 due to competition: netwerk, materiaal, hersenen, besluiten

#### 4. Beyond/unknown singles (6 misses)

Not recoverable: blockchain-netwerk (not in freq), handelsrobot (not in freq), ruggenmerg (Stanza doesn't split), huiduitslag (Stanza doesn't split), leiders/rijke (known-band after lemmatization)

#### 5. Minor noise

**plaatsvinden** in nl_a2_05 (score 0.60) — the separable verb itself, not a duplicate. Can't demote without also demoting useful separable verbs like meespelen.

### TODO — structural

- [ ] **Dense collocation whitelist** — run full 105M-line corpus on GPU. Currently 1304 VERB+NOUN bigrams from 4M tokens. Would recover "afspraak maken", "aandacht krijgen" and other VERB+NOUN pairs blocked by whitelist requirement.
