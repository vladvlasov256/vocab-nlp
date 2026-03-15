# TODO

Test text (A1):
> Archeologen vinden munten onder een huis. Het huis staat in northwestern Russia. De munten zijn van goud. Er zijn 409 munten in een kist. De munten zijn van voor 1917. Ze zijn uit het Russian Empire. De vondst is belangrijk voor het verhaal van het land.

## Bugs

- [ ] **Bad lemmatization**: "archeolog" should be "archeoloog" — Stanza strips the double vowel
- [ ] **Band cutoffs too tight for A1**: "munt" (coin) ranked "beyond" but is clearly an A1/A2 word. A1 target band (500) may be too narrow.
- [ ] **PROPNs clutter candidates**: "Russia", "Russian", "Empire", "northwestern" show up as candidates. Should be filtered out or handled separately.
- [ ] **False noun chunks**: "verhaal land" extracted as a phrase but they're separate concepts. Noun chunk extraction needs tightening.
- [ ] **Good words filtered as "known" at A1**: "vinden", "huis", "goud", "belangrijk", "verhaal" are useful A1 vocab but filtered out. Known band may be too wide.
