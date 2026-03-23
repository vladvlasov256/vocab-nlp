# TODO

## A2 benchmark gap (delta -0.30)

### Benchmark results (Dutch)

- A0: +1.60
- A1: +0.80
- A2: -0.30 (was -0.50)
- Overall: +0.70
- Pipeline avg: 4.2, LLM avg: 4.5
- Cohen's d: -0.32

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
- [x] Dense collocation whitelist — 105M-line OpenSubtitles corpus processed with spaCy on Modal T4 GPU. 15K bigrams (5K per pattern: ADJ+NOUN, VERB+NOUN, VERB+ADP)
- [x] NPMI-boosted phrase scoring — phrases confirmed by corpus get score × (1 + NPMI), compete naturally with singles. Removed hard phrase cap
- [x] Whitelist matching fix — match on lemma components instead of display text (kunstmatig vs kunstmatige)

### Investigated but not fixed

- **Separable verb parts demotion** — tried adding `_parts` to separable verbs so compound scoring demotes "plaatsvinden" (parts: plaats + vinden, both known-band). But this also demotes "meespelen" (parts: mee + spelen) which the judge wants. Can't distinguish light verbs from real separable verbs without a stop-list. Not worth the collateral damage.

### Remaining A2 failures (delta -0.30)

7 texts still lose to LLM baseline. Root cause is almost entirely **known-band single words** — common words the LLM picks as contextually important but frequency-based scoring filters as "too common."

#### Per-text analysis

| Text | Delta | Pipeline misses | Category |
|---|---|---|---|
| nl_a2_01 | -1 | aandacht krijgen, samenbrengen, blockchain-netwerk | Multi-word + beyond-freq |
| nl_a2_02 | -1 | cryptovaluta, passief inkomen, geautomatiseerde handel | Multi-word + beyond-freq |
| nl_a2_03 | -1 | bedrijf, verkopen, idee | Known-band singles |
| nl_a2_04 | -1 | bedrijf, leiders, verliezen, regering | Known-band singles |
| nl_a2_06 | -1 | werken, stoppen, begrijpen, proberen, trots, wedstrijd | Known-band singles |
| nl_a2_08 | -1 | lichaam, veilig, gebruiken | Known-band singles |
| nl_a2_09 | 0 | uitbraak, ruggenmerg, huiduitslag | Beyond-freq / Stanza splits |

#### Structural gap

The remaining delta is the ceiling for frequency-based extraction. The LLM baseline uses full text comprehension to select contextually important words regardless of frequency. Our pipeline can only rank by frequency band — a word like "bedrijf" (rank ~1200) is filtered as known-band even when it's the central topic of the text.

This gap is not fixable without adding semantic/contextual understanding to the pipeline, which would defeat the purpose of a lightweight NLP approach.
