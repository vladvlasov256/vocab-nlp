# TODO

## POS handling

Every UPOS tag must be handled explicitly — never silently ignore.

- [ ] **ADV** — Add adverbs as candidates. Words like "mnogo", "često", "zajedno" are useful vocab for learners. Validate against benchmarks before enabling.
- [ ] **PRON** — Consider teaching pronouns at A0 (ja, ti, on/ona). Currently dropped.
- [ ] **ADP** — Prepositions (u, na, za) may be worth surfacing at A0. Currently dropped.

## Serbian

### Noise (biggest impact on A1/A2 scores)

- [x] **Proper noun leakage** — Filter: capitalized mid-sentence + not in freq list → probable name. Gated by `filter_propn_by_surface` preset flag.
- [ ] **Malformed lemmas** — Stanza artifacts: "svetki", "dizajan", "vana" (should be "vani"). Minor — few occurrences, no systematic fix available.
- [x] **Dialect normalization** — Not a pipeline bug. Judge prompt updated to accept dialect variants (ijekavian/ekavian both valid).
- [ ] **Ambiguous verb forms** — "uči" can be "učiti" (learn) or "ući" (enter); Stanza sometimes picks wrong verb from context. Not fixable with overrides.
- [x] **čovek vs ljudi** — Not a bug. "čovek" is correct lemma for "ljudi". Judge prompt updated to accept standard lemmatization.
- [x] **Compound nouns** — "dronova-kamikaza" etc. are valid Serbian compounds, not malformed. Judge was wrong.
- [ ] **Compound proper nouns** — "Bliski istok" (Middle East) splits into "blizak" + "istok". Need multi-word expression handling or a proper noun blocklist.

### Coverage

- [x] **A2 known band lowered** — Known 1000→500. Pipeline now wins A2 (+0.30).
- [ ] **Re-tune all bands after remaining noise fixes** — Further band changes may help once malformed lemmas and dialect issues are addressed.

## Dutch

- [ ] **"vroeger" lemmatized as "vroeg"** — both Stanza and Wiktionary treat it as comparative of "vroeg", but it's a separate lexical item meaning "formerly". No clean fix yet.

## Done

- [x] Wiktionary-based lemma overrides (370k entries) — fixes coaches→coach, atleten→atleet, telescopen→telescoop
- [x] Serbian lemma overrides from srLex 1.3 + kaikki.org (2.1M entries)
- [x] Serbian frequency list from srLex 1.3 (105k lemmas, replaces Wikipedia 50k)
- [x] Per-language presets (LANG_PRESETS) with custom CEFR bands
- [x] Numeric token filter (regex `^\d+\.?$`)
- [x] Numbers card in CLI
- [x] Surface form fallback for bad Stanza lemmas
- [x] Filter items with spaces (failed compound rejoins)
- [x] Compound rejoining for underscore-split lemmas
- [x] DET filtering
- [x] Demonym adjective filtering
- [x] Proper noun separation
- [x] Noun chunk extraction removed (all garbage)
- [x] CEFR level band tuning
- [x] Judge prompt tuned for text comprehension
- [x] Benchmark language support (--lang nl/sr)
- [x] Serbian benchmark texts and baselines
- [x] Data file naming aligned ({lang}_freq.csv, {lang}_lemmas.tsv)
- [x] LFS for large data files
