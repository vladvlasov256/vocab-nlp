# PRD: Phrase Extraction & Ranking (v5)

## Context

The single-word pipeline (v4) is stable and benchmarked at Cohen's d = 1.75 against pure LLM extraction. It handles lemmatization, separable verb reconstruction (`op|bellen`), compound nouns, CEFR-aware ranking, and proper noun filtering across Dutch, Serbian, and English.

The next quality leap comes from extracting **multi-word candidates** — verb phrases, collocations, and noun chunks that are pedagogically more useful than their individual components.

## Problem

Single-word extraction misses meaning units that learners actually need:

| Text contains | Pipeline returns | Learner needs |
|---------------|-----------------|---------------|
| "gesprekken voeren" | gesprek, voeren | gesprekken voeren (to have conversations) |
| "last krijgen" | last, krijgen | last krijgen (to get into trouble) |
| "hoge prijs" | hoog, prijs | hoge prijs (high price) |
| "obratiti pažnju" | obratiti, pažnja | obratiti pažnju (to pay attention) |

Individual words are correct but lose the collocational meaning. For A0-B1 learners, the phrase is the useful unit — they need to learn that "voeren" goes with "gesprekken", not just that "voeren" means "to conduct".

## Goal

Add a phrase extraction layer that produces 2-4 word candidate phrases alongside single-word candidates. The pipeline scores and ranks all items (singles + phrases) on a unified scale. The bot takes top N, same as today.

## Non-Goals

- Perfect collocation detection (linguistic research problem)
- Phrase translation (LLM handles this downstream)
- Replacing single-word candidates (phrases supplement, not replace)
- YAKE or statistical keyphrase extraction (abandoned — dependency parse is more precise for short texts)

## Design philosophy

The phrase extractor does NOT need to be smart. It needs to be **generous but not garbage**:

- Extract 15-20 phrase candidates
- Score them on the same 0-1 scale as singles (using component word frequencies)
- Bot takes top N from the unified ranked list, same as v4

The extractor over-generates; the scoring heuristics curate. No LLM involved in ranking.

## Candidate types

### 1. ADJ + NOUN (noun phrases)

Works across all languages. High precision, easy to extract.

```
Rule: token.upos == ADJ + dependency-linked NOUN (amod relation)
Examples:
  - hoge prijs          (high price)
  - nieuwe leider       (new leader)
  - mobiele spellen     (mobile games)
Type: noun_phrase
```

### 2. NOUN + NOUN (noun compounds / topic phrases)

Useful for Dutch split compounds, Serbian noun groups, English topic phrases.

```
Rule: NOUN + NOUN linked by compound or nmod relation
Examples:
  - olie prijs          (if tokenizer splits compound)
  - spel wereld         (game world)
  - language model
Type: noun_phrase
```

### 3. VERB + NOUN/OBJ (verb phrases)

Most pedagogically useful pattern. Captures collocations and light verb constructions.

```
Rule: VERB head + child with deprel obj / obl / iobj
Examples:
  - gesprekken voeren   (to have conversations)
  - vragen stellen      (to ask questions)
  - besluit nemen       (to make a decision)
  - problemen geven     (to cause problems)
Type: verb_phrase
```

### 4. VERB + ADP/PART (phrasal verbs / fixed preposition patterns)

For Dutch separable verbs, English phrasal verbs, and fixed verb+prep constructions.

```
Rule: VERB + compound:prt / case / obl with ADP
Examples:
  - nadenken over       (to think about)
  - wachten op          (to wait for)
  - op|bellen           (already implemented in v4)
  - look for
Type: verb_phrase
```

## Extraction rules (8 patterns)

### MVP set (start here)

Rules 1-4 give the most value with least effort:

#### Rule 1: ADJ + NOUN

```
Pattern:  ADJ NOUN (adjacent or amod relation)
Extract:  both words as phrase
Examples: hoge prijs, nieuwe leider, mobiele spellen
Type:     noun_phrase
```

#### Rule 2: NOUN + NOUN

```
Pattern:  NOUN NOUN (adjacent or compound/nmod relation)
Extract:  both words (second is usually the head)
Examples: olie prijs, spel wereld, taal model
Type:     noun_phrase
```

#### Rule 3: VERB + NOUN

```
Pattern:  VERB NOUN (adjacent, or up to 1 token apart, or obj dependency)
Extract:  verb + noun
Examples: gesprekken voeren, vragen stellen, problemen geven
Type:     verb_phrase
```

#### Rule 4: VERB + ADP

```
Pattern:  VERB ADP (adjacent or obl/case dependency)
Extract:  verb + preposition
Examples: nadenken over, wachten op, zoeken naar
Type:     verb_phrase
```

### Extended set

#### Rule 5: VERB + PART (separable verbs) — already implemented in v4

```
Pattern:  compound:prt dependency, or linear PART VERB / VERB PART
Extract:  particle + verb as one unit
Examples: op|bellen, uit|gaan, aan|komen
Type:     verb_phrase
```

#### Rule 6: NOUN + ADP + NOUN

```
Pattern:  NOUN ADP NOUN (trigram)
Extract:  all 3 words if it's a short meaningful group
Examples: prijs van olie, deel van wereld, vraag over taal
Type:     noun_phrase
```

#### Rule 7: VERB + DET + NOUN

```
Pattern:  VERB DET NOUN or VERB PRON NOUN
Extract:  full phrase if it sounds like a useful learner unit
Examples: heeft een probleem, krijgt veel aandacht
Type:     verb_phrase
Note:     higher noise risk — filter aggressively
```

#### Rule 8: Named multiword / fixed phrases

```
Pattern:  NER span of 2-3 words, or fixed dependency relation
Extract:  only if it's a useful concept, NOT a person/country name
Examples: sociale media ✅, mobiele telefoon ✅, Verenigd Koninkrijk ❌
Type:     noun_phrase
Note:     use NER type to filter — skip PER, LOC; keep MISC
```

## Extraction approach

### Primary: dependency-based

When Stanza's dependency parse is clean (which it is for Dutch and English), use it directly.

#### Noun phrase extraction

```
for each token where upos == NOUN:
    collect dependents with deprel in {amod, compound, nmod}
    build span of 2-4 words
    → noun_phrase candidate
```

#### Verb phrase extraction

```
for each token where upos == VERB:
    collect dependents with deprel in {compound:prt, obl, obj}
    optionally attach mark/fixed (carefully)
    build span of 2-4 words
    → verb_phrase candidate
```

### Fallback: linear n-gram patterns

When dependency parse is noisy (expected for Serbian), fall back to POS-pattern matching on adjacent tokens.

Bigram/trigram window with these UPOS patterns:

| Pattern | Type | Example |
|---------|------|---------|
| ADJ NOUN | noun_phrase | hoge prijs |
| NOUN NOUN | noun_phrase | spel wereld |
| VERB NOUN | verb_phrase | vragen stellen |
| VERB ADP | verb_phrase | wachten op |
| NOUN ADP NOUN | noun_phrase | prijs van olie |
| VERB DET NOUN | verb_phrase | heeft een probleem |

This is surprisingly effective and catches phrases that dependency errors would miss.

## Output format

Every phrase candidate has two text representations:

```json
{
  "surface": "gesprekken voeren",
  "text": "gesprek voeren",
  "type": "verb_phrase",
  "score": 0.82,
  "source": "dep_pattern"
}
```

- `surface` — as it appears in the text (for display context)
- `text` — lemma-normalized form (for deduplication and LLM prompt)

Even if lemmatization is imperfect, having both fields is essential for deduplication.

## Scoring

Phrase scores must be on the same 0-1 scale as single-word weights so the bot can sort a unified list.

### Base score: component frequency

```
phrase_weight = max(component_weights)
```

Each component word gets its CEFR band weight (known=0.3, target=1.0, beyond=0.6) from the frequency list — same logic as v4 single-word scoring. The phrase takes the **max** — if any component is new to the learner, the phrase is worth teaching.

### Adjustments

| Signal | Adjustment | Rationale |
|--------|-----------|-----------|
| **verb_phrase** | +0.05 | Verb phrases are more pedagogically useful |
| **All components in target band** | +0.05 | Pure learning value |
| **Repeated in text** | +0.05 | Repeated phrases are central to the text |
| **One component is stopword** | -0.05 | Less useful as a phrase |
| **All components in known band** | hard reject | "veel mensen", "dit moment" = noise |

### Anti-patterns (hard reject)

Structurally valid but pedagogically useless:

- All components are function words or in "known" band
- Phrase is a time expression (`op dit moment`, `in de afgelopen`)
- Phrase is a generic filler (`voor veel mensen`, `het is`)
- Contains only proper nouns
- Contains URLs or numbers
- Spans entire sentence

Caught by:
1. Rule: reject if all words are stopwords or known-band
2. Small per-language stopphrase list (~10-20 entries)

## Filters and deduplication

### Keep

- Length 2-4 words
- At least one content word (not all stopwords)
- Score above minimum threshold

### Remove

- Duplicates by lemma-normalized form
- Phrases fully contained in a higher-scoring phrase (keep the better one)
- Singles whose lemma appears as a component of a selected phrase (phrases swallow their parts)

Example:
- Keep `gesprekken voeren` → drop standalone `gesprek` and `voeren`
- Keep `hoge prijs` → drop standalone `hoog` and `prijs`
- Keep standalone `op|bellen` if no phrase contains it

## Pipeline integration

```
TEXT
│
├─ sentence parse (Stanza)
│
├─ generate single-word candidates (existing v4)
│
├─ generate phrase candidates (NEW)
│   ├─ dependency patterns (primary)
│   └─ linear ngram fallback (for noisy parses)
│
├─ normalize (surface + lemma forms)
│
├─ score (composite heuristic)
│
├─ dedupe / prune
│
└─ return ranked items (singles + phrases)
     → bot takes top N
```

## API design

### Same endpoints, new output

v5 replaces v4 on the same endpoints (`POST /nl/`, `POST /en/`, `POST /sr/`). Phrases are always better than words-only — there's no case for maintaining two pipelines side by side. The bot doesn't need a version switch; it just gets richer candidates.

On Modal, the existing language classes (Nl, En, Sr) gain phrase extraction logic. On HF Space, the Gradio UI shows the unified output.

### Request

Same as v4:

```json
{
  "text": "De minister voert gesprekken over de hoge olieprijzen.",
  "level": "A1"
}
```

### Response

Unified `items` list with mixed types, not separate `candidates` + `phrases` fields:

```json
{
  "language": "nl",
  "items": [
    {
      "text": "gesprek voeren",
      "surface": "gesprekken voert",
      "type": "verb_phrase",
      "score": 0.92,
      "source": "dep_pattern"
    },
    {
      "text": "hoog olieprijs",
      "surface": "hoge olieprijzen",
      "type": "noun_phrase",
      "score": 0.85,
      "source": "dep_pattern"
    },
    {
      "text": "minister",
      "surface": "minister",
      "type": "single",
      "pos": "NOUN",
      "rank": 1842,
      "weight": 0.6,
      "in_target": false,
      "score": 0.60
    }
  ],
  "proper_nouns": [...],
  "numbers": [...]
}
```

**Why unified `items` instead of separate lists:**
- Bot doesn't need to merge two lists — just take top N
- Score is comparable across types (singles and phrases on the same scale)
- Simpler bot-side integration: `items.slice(0, vocabMax)`

**Fields:**
- `text` — lemma-normalized form (for LLM prompt and dedup)
- `surface` — as it appears in the text (for display context)
- `type` — `single`, `verb_phrase`, `noun_phrase`
- `score` — unified relevance score (0-1, comparable across types)
- `source` — `dep_pattern`, `ngram`, or `freq_rank` (for debugging)
- `pos`, `rank`, `weight`, `in_target` — only on `single` type items

### Backward compatibility

The response shape changes (`candidates` → `items`, new fields). The bot needs a one-time update to consume the new format. Since we control both sides, this is a coordinated deploy — no need for versioned endpoints or feature flags.

## Language priority

| Priority | Language | Reason |
|----------|----------|--------|
| 1 | Dutch | Primary market, richest phrase patterns (separable verbs, compounds, fixed collocations) |
| 2 | English | Demo/benchmark language, fast feedback loop, easy to verify quality |
| 3 | Serbian | Product language, but more linguistic noise (case system, word order variation, lemmatization quality) |

Implementation order: build language-agnostic base on Dutch, validate on English, then adapt for Serbian.

### Language-specific bonuses (Step 3)

| Language | Bonus rules |
|----------|-------------|
| Dutch | `compound:prt` → `op\|bellen` (done); VERB + `over`/`op`/`aan`/`uit`/`in` patterns |
| Serbian | VERB + NOUN(accusative) bonus; short noun phrases; careful with long case chains |
| English | Phrasal verbs; adjective+noun collocations |

## Implementation plan

### Step 1: Language-agnostic phrase candidates

- Dependency-based extraction: verb+obj, verb+obl, adj+noun, noun+noun
- Linear n-gram fallback for noisy parses
- Lemmatize all components (surface + text fields)
- Apply length filter (2-4 words)
- Apply anti-pattern filter

### Step 2: Scoring and ranking

- Composite score: type bonus, repetition, title, content density, length/boring penalties
- Rank and return top 10-20 phrase candidates alongside single-word candidates

### Step 3: Language-specific bonuses

- Dutch: verb+prep fixed patterns, particle verbs
- Serbian: reflexive constructions, case-normalized phrases
- English: phrasal verbs

### Step 4: Benchmark

Two separate evaluations — one tests the extractor, one tests the product:

#### A. Candidate recall

Does the extractor surface the right phrases?

- For each text, have a human mark 5-10 "ideal glossary items" (singles + phrases)
- Run the extractor, check how many ideal items appear in the top 20 candidates
- Metric: recall@20 (what % of ideal items did the extractor find?)

This isolates extraction quality from LLM selection quality. If recall is low, the extractor needs better rules. If recall is high but final output is bad, the LLM prompt needs work.

#### B. Final glossary quality

Does the full pipeline (extractor + LLM selection) beat the baselines?

Three-way comparison:
1. **LLM-from-scratch** — "give me useful vocab/phrases for this text" (existing baseline)
2. **v4 singles-only** — current pipeline, no phrases
3. **v5 singles+phrases** — new pipeline with phrase candidates

Same judge setup as v4 benchmark: GPT-5 scores each list 1-5 on Relevance, Coverage, Noise.

This tests product value. If v5 doesn't beat v4 significantly, the phrase layer isn't worth the complexity.

**Targets:**
- Candidate recall@20 > 80%
- v5 vs v4: Cohen's d > 0.5 (meaningful improvement)
- v5 vs LLM-from-scratch: Cohen's d > 1.0 (maintain existing advantage)

## Integration with bot

The bot's `selectLemmas` becomes `selectVocabulary` — same logic (sort by score, take top N), but now the list contains both singles and phrases:

```
v5 response.items (already ranked by pipeline):
  1. gesprek voeren     verb_phrase   0.92
  2. hoog olieprijs     noun_phrase   0.85
  3. minister           single        0.60
  ...

Bot: items.slice(0, vocabMax)
```

The LLM only translates the selected items. Phrase items get special formatting in the vocabulary card to show they're multi-word units.

## Pseudocode

```python
def extract_phrase_candidates(doc, title_tokens, freq, lang):
    candidates = []

    for sent in doc.sentences:
        words_by_id = {w.id: w for w in sent.words}

        # --- Dependency-based extraction ---

        for word in sent.words:
            # Noun phrases: ADJ + NOUN
            if word.upos == "NOUN":
                modifiers = [w for w in sent.words
                             if w.head == word.id
                             and w.deprel in ("amod", "compound", "nmod")]
                for mod in modifiers:
                    parts = sorted([mod, word], key=lambda w: w.id)
                    surface = " ".join(p.text for p in parts)
                    lemma = " ".join(p.lemma.lower() for p in parts)
                    candidates.append({
                        "surface": surface,
                        "text": lemma,
                        "type": "noun_phrase",
                        "source": "dep_pattern",
                    })

            # Verb phrases: VERB + OBJ/OBL
            if word.upos == "VERB":
                attachments = [w for w in sent.words
                               if w.head == word.id
                               and w.deprel in ("obj", "obl", "iobj")
                               and w.upos in ("NOUN", "ADJ", "ADP")]
                for att in attachments:
                    parts = sorted([word, att], key=lambda w: w.id)
                    surface = " ".join(p.text for p in parts)
                    lemma = " ".join(p.lemma.lower() for p in parts)
                    candidates.append({
                        "surface": surface,
                        "text": lemma,
                        "type": "verb_phrase",
                        "source": "dep_pattern",
                    })

        # --- Linear n-gram fallback ---

        BIGRAM_PATTERNS = [
            ("ADJ", "NOUN"),
            ("NOUN", "NOUN"),
            ("VERB", "NOUN"),
            ("VERB", "ADP"),
        ]
        TRIGRAM_PATTERNS = [
            ("NOUN", "ADP", "NOUN"),
            ("VERB", "DET", "NOUN"),
            ("VERB", "PRON", "NOUN"),
        ]
        tokens = sent.words

        # Bigrams
        for i in range(len(tokens) - 1):
            pair = (tokens[i].upos, tokens[i+1].upos)
            if pair in BIGRAM_PATTERNS:
                surface = tokens[i].text + " " + tokens[i+1].text
                lemma = tokens[i].lemma.lower() + " " + tokens[i+1].lemma.lower()
                candidates.append({
                    "surface": surface,
                    "text": lemma,
                    "type": "noun_phrase" if "NOUN" in pair else "verb_phrase",
                    "source": "ngram",
                })

        # Trigrams
        for i in range(len(tokens) - 2):
            triple = (tokens[i].upos, tokens[i+1].upos, tokens[i+2].upos)
            if triple in TRIGRAM_PATTERNS:
                parts = tokens[i:i+3]
                surface = " ".join(p.text for p in parts)
                lemma = " ".join(p.lemma.lower() for p in parts)
                ptype = "verb_phrase" if tokens[i].upos == "VERB" else "noun_phrase"
                candidates.append({
                    "surface": surface,
                    "text": lemma,
                    "type": ptype,
                    "source": "ngram",
                })

    # --- Score (same 0-1 scale as single-word weights) ---

    for c in candidates:
        component_weights = [cefr_weight(w.lemma, freq, level) for w in c["_words"]]
        if all(w <= 0.3 for w in component_weights):
            continue  # all known-band → boring, skip
        c["score"] = max(component_weights)
        if c["type"] == "verb_phrase":
            c["score"] += 0.05
        if all(0.3 < w <= 1.0 for w in component_weights):
            c["score"] += 0.05  # all target-band
        # cap at 1.0
        c["score"] = min(c["score"], 1.0)

    # --- Filter and dedupe ---

    candidates = [c for c in candidates if len(c["text"].split()) <= 4]
    candidates = [c for c in candidates if not all_stopwords(c)]
    candidates = dedupe_by_lemma(candidates)
    candidates = prune_subphrases(candidates)
    candidates.sort(key=lambda c: c["score"], reverse=True)

    return candidates[:20]
```

## Open questions

- [x] Should phrases that contain a single-word candidate suppress that candidate? → **Yes.** Phrases swallow their component singles. If "hoge prijs" is selected, standalone "prijs" and "hoog" are dropped.
- [x] How to handle Serbian case forms in phrases? → **Always lemmatize.** `text` field is nominative/infinitive, `surface` keeps original form.
- [x] Should the phrase score consider position in text? → **No.** Keep it simple — frequency-based scoring is enough for short texts.
- [x] Is a per-language stopphrase list maintainable? → **Skip it.** Start with rules only ("all components known-band → reject"). Add a stopphrase list later if benchmark shows noise.
- [x] Should dep-based and ngram candidates be deduplicated? → **Yes.** Dedupe by lemma-normalized form. `source` field records which method found it first.

## Success criteria

- Phrase candidates are linguistically correct >90% of the time (manual spot check)
- Benchmark score with phrases >= benchmark score without phrases
- No regression on single-word extraction quality
- Dutch phrase quality visibly better than Serbian (expected due to linguistic complexity)
