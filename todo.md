# Benchmark: Pipeline vs LLM (fair item counts)

Bench clips to LLM counts: A0=4, A1=8, A2=12, B1=15.
API unchanged (MAX_LEMMAS=15).

## Results (pre-fix baseline)

| Lang | A0    | A1    | A2    | Overall | Cohen's d |
|------|-------|-------|-------|---------|-----------|
| NL   | -0.80 | -1.00 | -0.50 | -0.77   | -0.79     |
| EN   | -1.10 | -0.90 | -0.60 | -0.87   | -0.92     |
| SR   | -0.80 | -0.70 | -1.10 | -0.87   | -1.19     |

LLM wins everywhere. Pipeline never positive at any level/language combination.

## Action plan — status

### Quick scoring tweaks
1. [x] Raise A0 known-band to suppress filler (NL 0→100, EN 0→100, SR 0→30)
2. [x] Log-rank sort bonus for ranking (count × log₂(rank) × 0.02), capped weight for output
3. [x] Verb boost at A0/A1 for all languages

### Phrase extraction improvements
4. [x] max_phrases cap removed (was dead config, never enforced)
5. [x] NOUN+NOUN via nmod deprel — collocation-gated to avoid noise
6. [x] Phrases inherit component sort_key + boost (colloc-backed +0.2, others +0.05)
7. [x] SR reflexive verbs: "boriti se", "menjati se", "oporaviti se" etc. — detected via expl(sebe) dependent, appended after freq scoring
8. [x] VERB+NOUN whitelist gate kept at all levels (A2 relaxation tested → too noisy, reverted)

### Additional fixes applied
- Phrase dedup by component lemmas (not display text) — prevents "liga šampiona"/"lige šampiona" duplicates
- nmod display: surface form for genitive dependent ("liga šampiona" not "liga šampion")
- Compound spam cap: max 2 phrases sharing any component word
- Phrase component inheritance: phrases inherit best-component sort_key so they don't lose to singles they swallow

## Remaining issues

### "mens" filler in NL
"mens" (rank 597) still appears in 4/10 NL texts. At A2 it's known-band (0.5 weight) but still makes the cut via sort bonus. At A0 it's target-band (rank 597 > known=100). LLM never picks it.

### SR ADJ display forms
ADJ+NOUN phrases use surface form for ADJ, which shows inflected case instead of citation form. "veštačke inteligencije" instead of "veštačka inteligencija". NL doesn't have this problem because Dutch ADJ attributive form is consistent.

### Missing phrases without collocation backing
- "liga šampiona" — NOUN+NOUN (nmod) not in collocation whitelist (corpus extraction only captured ADJ+NOUN, VERB+NOUN, VERB+ADP). Need NOUN+NOUN collocation extraction or manual whitelist.
- "briga za sebe" — trigram, can't extract with bigram-only phrase system
- "širiti poruku" — VERB+NOUN without dep match in text

### EN compound diversity
Even with the 2-per-component cap, EN compound phrases can dominate at A0 (4 slots). "play game", "football game" take 2/4 slots. Not necessarily wrong but different from LLM style.
