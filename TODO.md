# TODO

## POS handling

Every UPOS tag must be handled explicitly — never silently ignore.

- [ ] **ADV** — Add adverbs as candidates. Words like "mnogo", "često", "zajedno" are useful vocab for learners. Validate against benchmarks before enabling.
- [ ] **PRON** — Consider teaching pronouns at A0 (ja, ti, on/ona). Currently dropped.
- [ ] **ADP** — Prepositions (u, na, za) may be worth surfacing at A0. Currently dropped.

## Serbian

- [ ] **Proper noun leakage** — Stanza sometimes tags proper nouns as NOUN/ADJ ("zelenski", "iPhona", "pokemon"). Cross-check against PROPN stems or capitalized surface forms.
- [ ] **Malformed lemmas** — Stanza produces artifacts like "dronova-kamikaza", "uNConferenca", "svetki". Need sr_lemmas.tsv overrides or heuristic filters.
- [ ] **Compound proper nouns** — "Bliski istok" (Middle East) gets split into "blizak" + "istok". Need multi-word expression handling.
- [ ] **Band tuning** — Current Serbian bands are a first guess. Re-run benchmarks after noise fixes and adjust.

## Dutch

- [ ] **"vroeger" lemmatized as "vroeg"** — both Stanza and Wiktionary treat it as comparative of "vroeg", but it's a separate lexical item meaning "formerly". No clean fix yet.

## Done

- [x] Wiktionary-based lemma overrides (370k entries) — fixes coaches→coach, atleten→atleet, telescopen→telescoop
- [x] Serbian lemma overrides from srLex 1.3 (1.7M entries)
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
