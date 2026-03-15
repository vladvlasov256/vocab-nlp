# TODO

Test text (A1):
> Archeologen vinden munten onder een huis. Het huis staat in northwestern Russia. De munten zijn van goud. Er zijn 409 munten in een kist. De munten zijn van voor 1917. Ze zijn uit het Russian Empire. De vondst is belangrijk voor het verhaal van het land.

## Benchmark (2 runs, gpt-5 judge)

| Level | Pipeline avg | LLM avg | Delta |
|-------|-------------|---------|-------|
| A0    | 3.1         | 2.5     | +0.60 |
| A1    | 2.6         | 3.3     | -0.70 |
| A2    | 2.2         | 3.3     | -0.90 |
| **Overall** | **2.7** | **3.0** | **-0.33** |

Cohen's d ≈ -0.24

## Bugs (from manual testing)

- [ ] **Bad lemmatization**: "archeolog" should be "archeoloog" — Stanza strips the double vowel
- [ ] **Band cutoffs too tight for A1**: "munt" (coin) ranked "beyond" but is clearly an A1/A2 word. A1 target band (500) may be too narrow.
- [x] **PROPNs clutter candidates**: "Russia", "Russian", "Empire", "northwestern" show up as candidates. → Fixed: separated into `proper_nouns` list.
- [ ] **False noun chunks**: "verhaal land" extracted as a phrase but they're separate concepts. Noun chunk extraction needs tightening.
- [ ] **Good words filtered as "known" at A1**: "vinden", "huis", "goud", "belangrijk", "verhaal" are useful A1 vocab but filtered out. Known band may be too wide.

## Bugs (from benchmark)

- [ ] **Malformed noun chunks**: "kunstmatig intelligentie", "verkiezing_commissie India", "groot taal_model", "samen_brengen", "oud pixel" — noun chunk extraction joins words that shouldn't be joined. Biggest source of noise at A1/A2.
- [ ] **DET leaking into candidates**: "de", "het" still appear. Should be filtered at A1+ or always.
- [ ] **Proper noun adjectives not filtered**: "Israëlisch", "Palestijns" pass through as ADJ. Need to detect nationality/demonym adjectives.
- [ ] **Stanza lemma errors**: "negend" (should be "negende"), "atlet" (should be "atleet"), "overpraten" (not a real word). Can't fix Stanza, but could post-process or skip suspicious lemmas.
- [ ] **Underscores in compounds**: "software_ingenieurs", "standaard_coode", "computer_programma" — Stanza tokenizer joins with underscores. Need to clean or split these.
