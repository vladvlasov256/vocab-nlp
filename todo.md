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

**Not fixable** without lowering the known boundary (1500 → ~800), which would flood output with noise from the < 500 range. The LLM baseline picks these from context understanding, which frequency scoring fundamentally can't replicate.

#### 2. Target-band crowded out (6 misses)

Score 1.0 but don't make top-15: netwerk, niveau, materiaal, tijdschrift, besluiten, verslaan

**Fix: raise A2 phrase cap from 2 → 3.** Phrases take 1 slot but swallow 2 component singles. With cap=2, 2 phrases eat 4 singles → only 13 single slots remain. With cap=3, better phrases get through AND free up single slots since phrase components are deduplicated. Other levels already use cap=3.

#### 3. Beyond/unknown singles (10 misses)

Domain words or inflected forms not in freq list: rijke, leiders, crypto-industrie, blockchain-netwerk, handelsrobot, investeren, symptoom, infectie, peptide, schoner

Analysis:
- **rijke** → Stanza lemmatizes to "rijk" (rank 957, known-band). Filtered correctly.
- **leiders** → Stanza lemmatizes to "leider" (rank 1471, known-band). Filtered correctly.
- **crypto-industrie, blockchain-netwerk** → hyphenated compounds not in freq. Filtered by hyphenated jargon filter. Could add exception for compounds where both parts are in freq list.
- **handelsrobot** → not in freq, Stanza doesn't split it. No path to recovery.
- **investeren** (rank 7671), **symptoom** (5313), **infectie** (6551) → beyond target band, score 0.6. Present in output but may get crowded out of top-15.
- **peptide** (rank 92192) → in output as "peptid" (Stanza misspelling). Lemma override would fix.
- **schoner** (rank 159260) → comparative form, not useful as standalone vocab.

**Fix: allow hyphenated compounds where both parts are in freq list.** Would recover crypto-industrie ("crypto" + "industrie" both in freq) and blockchain-netwerk.

#### 4. Multi-word phrases (21 misses) — second biggest gap

Collocations the LLM generates that our dep-parse doesn't extract.

**Already extracted, different format (4):**
- spelen mee → we output "meespelen" (separable verb reconstruction)
- uitkijken naar → we output "uitkijken" (separable verb)
- doorgaan naar → we output "doorgaan" (known-band, score 0.39, filtered)
- oplossen in → we output "oplossen" (single verb, ADP dropped)

These aren't real misses — the judge should recognize them. Format difference only.

**Extracted by dep-parse but blocked by phrase cap (3):**
- kunstmatige intelligentie → ADJ+NOUN amod, extracted but capped at 2 phrases in nl_a2_01 (beaten by "digitale munt" + "slimme contract")
- passief inkomen → ADJ+NOUN amod, would need to be extracted
- geautomatiseerde handel → ADJ+NOUN amod, would need to be extracted

**Fix: raise A2 phrase cap to 3** (same as fix for category 2).

**VERB+NOUN dep-obj, blocked by whitelist (3):**
- afspraak maken → VERB+NOUN obj, not in collocation whitelist
- toegankelijk maken → ADJ+VERB, not a pattern we extract
- aandacht krijgen → NOUN+VERB, reversed word order

**Fix: expand collocation whitelist** (dense corpus run) or relax whitelist requirement for high-scoring pairs.

**Complex phrases beyond current extraction (11):**
- slim contract → already extracted as "slimme contract" (surface form differs from baseline)
- plaats overnemen → idiomatic, not standard dep pattern
- medische hulp zoeken → 3-word phrase, beyond bigram extraction
- op tijd hulp zoeken → 4-word phrase
- winstgevend worden → ADJ+VERB copula, not extracted
- gestorven zijn → participle+AUX, not extracted
- snel herkennen → ADV+VERB, not extracted
- ogen hebben voor → idiom
- platform groeien → not a real collocation
- aantrekkelijk worden → ADJ+VERB copula, not extracted
- vechten om → VERB+ADP, extracted pattern but "om" is too generic

**Not fixable** without fundamentally different extraction (e.g. LLM-based phrase selection). These require understanding meaning, not just syntax.

#### 5. Compounds Stanza splits (3 misses)

hoofdpijn (×2), samenbrengen — `_clean_lemma` rejoins correctly. Were being demoted by compound scoring bug (now fixed).

### TODO — actionable

- [ ] **Raise A2 phrase cap from 2 → 3** — unblocks "kunstmatige intelligentie" and frees top-15 slots. Low risk, other levels already use 3.
- [ ] **Allow hyphenated compounds with known parts** — recover "crypto-industrie", "blockchain-netwerk" where both parts are in freq list. Currently blocked by hyphenated jargon filter.
- [ ] **peptide lemma override** — add "peptid → peptide" to nl_lemmas.tsv (Stanza misspelling)

### TODO — structural

- [ ] **Dense collocation whitelist** — run full 105M-line corpus on GPU. Currently 1304 VERB+NOUN bigrams from 4M tokens. Would recover "afspraak maken" and other VERB+NOUN pairs blocked by whitelist.
