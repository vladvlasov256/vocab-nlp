# TODO

## Serbian
- [ ] Build Wiktionary lemma overrides for Serbian (`scripts/build_lemma_dict.py` — currently Dutch only)
- [ ] Create Serbian benchmark texts and baselines (`bench/texts/sr_*.txt`)
- [ ] Evaluate Serbian pipeline quality

## Dutch
- [ ] **"vroeger" lemmatized as "vroeg"** — both Stanza and Wiktionary treat it as comparative of "vroeg", but it's a separate lexical item meaning "formerly". No clean fix yet.
- [ ] Update README.md with latest benchmark numbers

## Done
- [x] Wiktionary-based lemma overrides (370k entries) — fixes coaches→coach, atleten→atleet, telescopen→telescoop
- [x] Surface form fallback for bad Stanza lemmas
- [x] Filter items with spaces (failed compound rejoins)
- [x] Compound rejoining for underscore-split lemmas
- [x] DET filtering
- [x] Demonym adjective filtering
- [x] Proper noun separation
- [x] Noun chunk extraction removed (all garbage)
- [x] CEFR level band tuning
- [x] Judge prompt tuned for text comprehension
