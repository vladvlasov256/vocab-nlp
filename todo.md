# TODO

## A2 benchmark gap (delta -1.00)

### Benchmark results (Dutch)

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

### Root cause analysis

#### 1. Separable verbs ranked by base verb instead of reconstructed form

"mee|spelen" is ranked by "spelen" (rank 400, known band, score 0.16) instead of "meespelen" (rank 8394, beyond target, score 0.6). Same for "uit|kijken" (kijken=127 → score 0.08, but uitkijken=4206 → score 1.0).

The reconstructed form is a different word with a different meaning — "meespelen" (participate) vs "spelen" (play). Using the base verb rank is wrong.

**Fix:** In `extract_separable_verbs()`, try the reconstructed form in the freq list first. If found, use its rank. Fall back to base verb only if reconstructed form is missing.

**Affected texts:** nl_a2_05 (spelen mee, uitkijken naar), nl_a2_06 (plaats overnemen)

#### 2. Phrase filter kills beyond-target pairs

"kunstmatige intelligentie" — both components are beyond the target band (kunstmatig=9719, intelligentie=5488). The filter `if not any(w >= 1.0 for w in weights)` requires at least one component in the target band. Both score 0.6 so the phrase is dropped.

**Fix:** Allow phrases where both components are beyond target — they score 0.6 which passes the 0.5 threshold anyway. Remove or relax the "at least one in target band" requirement.

**Affected texts:** nl_a2_01 (kunstmatige intelligentie)

#### 3. VERB+NOUN dep (obj) produces noise phrases

"begrijpen verandering" — syntactically real (obj dep) but not a useful collocation. Both are common words that happen to be adjacent. The collocation whitelist is too sparse (4M tokens) to reliably filter these.

**Fix options:**
- Require VERB+NOUN phrases to match the collocation whitelist (needs denser whitelist from full corpus)
- Drop VERB+NOUN dep extraction entirely and rely on singles
- Tighter heuristic: reject when verb is in top N most common verbs

**Affected texts:** nl_a2_06 (begrijpen verandering), nl_a2_01 (contract gebruiken)

#### 4. Known-band singles below threshold

bedrijf (1014), verliezen (647), regering (1228), regelen (1019), wedstrijd (1022), stoppen (349), proberen (353) — all in known band at A2, scoring 0.05–0.39. The LLM baseline picks these because they're contextually important even if "known."

Lowering the threshold was tested and didn't improve benchmark scores — the judge penalizes noise more than it rewards coverage. This may not be fixable without context-aware scoring or a fundamentally different approach for A2.

**Affected texts:** nl_a2_04 (bedrijf, verliezen, regering, regelen), nl_a2_06 (stoppen, proberen, wedstrijd)
