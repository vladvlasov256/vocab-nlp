# TODO

## A2 benchmark regression (delta -1.50)

### Root cause

At A2, the known band is 0–1500. Most useful words (stoppen, verandering, herinnering, trots, wedstrijd, proberen) fall inside this band and score 0.30. Meanwhile mediocre phrases like "begrijpen verandering" or "steunen tijdens" score 1.00 because one component is in the target band — and they take up top slots.

The LLM baseline picks words that are technically "known" at A2 but still worth teaching in context. Our pipeline buries them.

### Two problems

1. **Phrases are too greedy.** Adjacent words that aren't real collocations ("voetbal verslaan", "verslaan voor", "steunen tijdens") get extracted and score high. Dep-parse and bigram extraction both produce these. The collocation whitelist doesn't help because it's too sparse (750K lines / 4M tokens).

2. **Known-band words score too low.** At A2, rank 349 (stoppen) and rank 718 (trots) both get 0.30 — same as rank 23 (hebben). There's no gradient within the known band, so contextually valuable words can't compete with phrases.

### Observed in nl_a2_06

- Pipeline top items: zomer, wisselen, carrière, begrijpen verandering, mooi herinnering, voetbal verslaan, verslaan voor, steunen tijdens
- LLM baseline: werken, stoppen, verandering, plaats overnemen, begrijpen, herinnering, tijd, verslaan, trots, wedstrijd, proberen, carrière
- Pipeline misses: stoppen, verandering, herinnering, trots, wedstrijd, proberen (all score 0.30)

### Possible fixes

- [ ] Add gradient within known band (e.g. rank 1000 scores higher than rank 50)
- [ ] Raise phrase quality bar (require whitelist match, or tighter dep relations)
- [ ] Cap number of phrases in final output
- [ ] Review whether phrase swallowing is too aggressive at A2
