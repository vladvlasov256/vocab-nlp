"""Core NLP pipeline — shared by app.py (Modal) and cli.py (local)."""

import csv
import json
import logging
import re
from pathlib import Path

MAX_TEXT_BYTES = 4096
MAX_LEMMAS = 15

# Per-language presets: CEFR level settings + display name.
# band.known = top N most frequent words (skip these, too easy)
# band.target = words ranked up to this position (prioritize these)
# Words beyond target still appear but score lower.
LANG_PRESETS = {
    "nl": {
        "name": "Dutch",
        "filter_propn_by_surface": True,
        "separable_verbs": True,
        "levels": {
            "A0": {"band": {"known": 0,     "target": 1000},  "adv_weight": 0.7, "max_phrases": 3},
            "A1": {"band": {"known": 500,   "target": 3000},  "adv_weight": 0.7, "max_phrases": 3},
            "A2": {"band": {"known": 1500,  "target": 5000},  "adv_weight": 1.0, "max_phrases": 2},
            "B1": {"band": {"known": 3000,  "target": 8000},  "adv_weight": 1.0, "max_phrases": 3},
        },
    },
    "sr": {
        "name": "Serbian",
        "filter_propn_by_surface": True,
        "separable_verbs": False,
        "levels": {
            "A0": {"band": {"known": 0,     "target": 1500},  "adv_weight": 0.7, "max_phrases": 3},
            "A1": {"band": {"known": 200,   "target": 3000},  "adv_weight": 0.7, "max_phrases": 3},
            "A2": {"band": {"known": 500,   "target": 5000},  "adv_weight": 1.0, "max_phrases": 2},
            "B1": {"band": {"known": 2000,  "target": 8000},  "adv_weight": 1.0, "max_phrases": 3},
        },
    },
    "en": {
        "name": "English",
        "filter_propn_by_surface": True,
        "separable_verbs": False,
        "levels": {
            "A0": {"band": {"known": 0,     "target": 1000},  "adv_weight": 0.7, "max_phrases": 3},
            "A1": {"band": {"known": 300,   "target": 3000},  "adv_weight": 0.7, "max_phrases": 3},
            "A2": {"band": {"known": 800,   "target": 5000},  "adv_weight": 1.0, "max_phrases": 2},
            "B1": {"band": {"known": 1500,  "target": 8000},  "adv_weight": 1.0, "max_phrases": 3},
        },
    },
}
LANGUAGES = list(LANG_PRESETS.keys())
LEVELS = ["A0", "A1", "A2", "B1"]

_modal_data = Path("/root/data")
DATA_DIR = _modal_data if _modal_data.exists() else Path(__file__).parent / "data"
PROCESSORS = "tokenize,pos,lemma,depparse"


def trim_text(text: str) -> str:
    """Collapse whitespace and cap at MAX_TEXT_BYTES. Expects clean text (no HTML)."""
    text = re.sub(r"\s+", " ", text).strip()
    return text[:MAX_TEXT_BYTES]


def load_freq_nl() -> dict[str, int]:
    """Load SUBTLEX-NL frequency list. Returns {lemma: rank}.

    SUBTLEX-NL is a subtitle-based corpus (~400k lemmas). Lower rank = more common.
    Used for CEFR scoring and as ground truth for compound validation.
    """
    freq = {}
    with open(DATA_DIR / "nl_freq.csv", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for rank, row in enumerate(reader, 1):
            lemma = row.get("dominant.pos.lemma", row.get("Word", "")).lower()
            if lemma and lemma not in freq:
                freq[lemma] = rank
    return freq


def load_freq_sr() -> dict[str, int]:
    """Load Serbian frequency list (srLex 1.3, lemma-aggregated). Returns {lemma: rank}."""
    freq = {}
    with open(DATA_DIR / "sr_freq.csv", encoding="utf-8") as f:
        for rank, line in enumerate(f, 1):
            parts = line.strip().split()
            if parts:
                freq[parts[0].lower()] = rank
    return freq


def load_freq_en() -> dict[str, int]:
    """Load SUBTLEX-US frequency list. Returns {word: rank}.

    SUBTLEX-US is a subtitle-based corpus (~74k word forms). Lower rank = more common.
    Word-form based (not lemma), but English has minimal inflection so this works well.
    """
    freq = {}
    with open(DATA_DIR / "en_freq.csv", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for rank, row in enumerate(reader, 1):
            word = row["Word"].lower()
            if word and word not in freq:
                freq[word] = rank
    return freq


FREQ_LOADERS = {"nl": load_freq_nl, "sr": load_freq_sr, "en": load_freq_en}


def _load_collocations(lang: str) -> set[str]:
    """Load collocation whitelist for a language. Returns set of 'word1 word2' bigrams."""
    path = DATA_DIR / f"collocations_{lang}.json"
    if not path.exists():
        return set()
    data = json.loads(path.read_text())
    bigrams = set()
    for items in data.values():
        for item in items:
            bigrams.add(item["bigram"])
    return bigrams


_COLLOCATIONS: dict[str, set[str]] = {}


def get_collocations(lang: str) -> set[str]:
    if lang not in _COLLOCATIONS:
        _COLLOCATIONS[lang] = _load_collocations(lang)
    return _COLLOCATIONS[lang]


def load_lemma_overrides(lang: str) -> dict[tuple[str, str], str]:
    """Load lemma override TSV for a language. Returns {(inflected_form, pos): lemma}."""
    path = DATA_DIR / f"{lang}_lemmas.tsv"
    if not path.exists():
        return {}
    overrides: dict[tuple[str, str], str] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.startswith("#") or not line.strip():
                continue
            parts = line.rstrip("\n").split("\t")
            if len(parts) != 3:
                continue
            form, pos, lemma = parts
            overrides[(form, pos)] = lemma
    return overrides


def patch_stanza_lemmatizer(nlp, lang: str) -> int:
    """Inject Wiktionary-based lemma overrides into Stanza's composite_dict.

    Also adds capitalized variants so sentence-initial words are handled.
    Returns the number of entries injected.
    """
    overrides = load_lemma_overrides(lang)
    if not overrides:
        return 0

    trainer = nlp.processors["lemma"]._trainer
    count = 0
    for (form, pos), lemma in overrides.items():
        key = (form, pos)
        if key not in trainer.composite_dict:
            trainer.composite_dict[key] = lemma
            count += 1
        # Also add capitalized variant (e.g. "Coaches" at start of sentence)
        cap_form = form[0].upper() + form[1:] if form else form
        cap_key = (cap_form, pos)
        if cap_form != form and cap_key not in trainer.composite_dict:
            trainer.composite_dict[cap_key] = lemma
            count += 1

    logging.getLogger("pipeline").info(f"[lemma-patch] {lang}: injected {count} overrides ({len(overrides)} base entries)")
    return count


def create_stanza_pipeline(lang: str, verbose: bool = False):
    """Create a Stanza pipeline for a language, with lemma overrides applied.

    Downloads model if needed, creates the pipeline, and patches the lemmatizer
    with Wiktionary-based overrides. This is the single entry point — callers
    should not interact with Stanza directly.
    """
    import stanza

    stanza.download(lang, processors=PROCESSORS, verbose=verbose)
    nlp = stanza.Pipeline(lang, processors=PROCESSORS, use_gpu=False, logging_level="WARN")
    patch_stanza_lemmatizer(nlp, lang)
    return nlp


def rank_to_weight(rank: int | None, lang: str = "nl", level: str = "A0") -> float:
    """Score a word by frequency rank relative to learner level.

    Returns:
        0.05–0.45 — word is in "known" band (gradient: common words score lower,
                     words near the target boundary score higher)
        1.0       — word is in "target" band (sweet spot, should learn next)
        0.6       — word is beyond target or not in freq list

    The 0.5 threshold in the API filters out known-band words,
    keeping target (1.0) and beyond/unknown (0.6).
    """
    band = LANG_PRESETS[lang]["levels"][level]["band"]

    if rank is None:
        return 0.6  # not in freq list — potentially interesting domain vocab
    if rank <= band["known"]:
        if band["known"] == 0:
            return 0.05
        # Linear gradient: rank 1 → 0.05, rank == known → 0.45
        return 0.05 + 0.40 * (rank / band["known"])
    if rank <= band["target"]:
        return 1.0  # target zone — learn these
    return 0.6  # beyond target — still useful


def extract_separable_verbs(sent) -> list[dict]:
    """Dutch separable verb reconstruction from dependency parse.

    Dutch has separable verbs where the particle splits from the verb:
      "Hij belt zijn moeder op" → particle "op" + verb "bellen" → "opbellen"

    Stanza marks particles with deprel="compound:prt" pointing at the verb head.
    We reconstruct the full form (for display) but keep the base verb lemma
    as _rank_key (for frequency ranking, since "bellen" is in the freq list
    but "opbellen" may not be).
    """
    verbs = {}
    particles = []
    for word in sent.words:
        if word.upos == "VERB":
            verbs[word.id] = word
        if word.deprel == "compound:prt" and word.head > 0:
            particles.append(word)

    results = []
    replaced_verb_ids = set()
    for particle in particles:
        verb = verbs.get(particle.head)
        if verb:
            reconstructed = particle.text.lower() + "|" + verb.lemma
            results.append({
                "text": reconstructed,
                "pos": "VERB",
                "_rank_key": verb.lemma.lower(),
            })
            replaced_verb_ids.add(verb.id)
    return results, replaced_verb_ids


# Dutch compound connectors used between parts of compound words.
# e.g. "doorzetting" + "s" + "vermogen" → "doorzettingsvermogen"
_NL_CONNECTORS = ("", "s", "e", "en", "er")


def _clean_lemma(text: str, freq: dict[str, int] | None = None) -> str:
    """Fix Stanza's underscore-split compound lemmas.

    Stanza sometimes lemmatizes Dutch compounds with underscores:
      "doorzettingsvermogen" → "doorzetting_vermogen"
      "computerprogramma" → "computer_programma"

    We try rejoining the two parts with common Dutch connectors and validate
    against the frequency list. If a valid compound exists, use it.
    Otherwise fall through and just strip underscores (produces a space-separated
    form that will be filtered out later by the space filter).
    """
    if "_" in text and freq is not None:
        parts = text.split("_")
        if len(parts) == 2:
            a, b = parts[0].lower(), parts[1].lower()
            best, best_rank = None, float("inf")
            for conn in _NL_CONNECTORS:
                compound = a + conn + b
                rank = freq.get(compound)
                if rank is not None and rank < best_rank:
                    best, best_rank = compound, rank
            if best is not None:
                return best
        # More than 2 parts or no match — just strip underscores
    return re.sub(r"[_]+", " ", text).strip()


# Per-language rank caps for phrase filtering. Words ranked below these
# thresholds are too generic to form useful collocations.
# "hebben contract" (verb rank ~23 in NL) is noise,
# "voeren gesprek" (verb rank ~800 in NL) is a real collocation.
_PHRASE_RANK_CAPS = {
    "nl": {"VERB": 250, "ADJ": 400, "NOUN": 100},
    "en": {"VERB": 150, "ADJ": 300, "NOUN": 80},
    "sr": {"VERB": 150, "ADJ": 300, "NOUN": 80},
}

_PHRASE_BIGRAMS = {
    ("ADJ", "NOUN"): "noun_phrase",
    ("NOUN", "NOUN"): "noun_phrase",
    ("VERB", "NOUN"): "verb_phrase",
    ("VERB", "ADP"): "verb_phrase",
}

_DEP_NOUN_RELS = {"amod", "compound"}
_DEP_VERB_RELS = {"obj"}


def extract_phrases(doc, lang: str, freq: dict[str, int], level: str = "A0") -> list[dict]:
    """Extract multi-word phrase candidates from dependency parse and POS bigrams.

    Dependency-based extraction only:
    - ADJ→NOUN (amod), NOUN→NOUN (compound)
    - VERB→NOUN (obj)

    Scoring uses max(component_weights) so phrases compete on the same
    0-1 scale as single-word candidates.
    """
    candidates = []

    for sent in doc.sentences:
        # --- Dependency-based extraction ---
        for word in sent.words:
            if word.upos == "NOUN":
                for dep in sent.words:
                    if (dep.head == word.id
                            and dep.deprel in _DEP_NOUN_RELS
                            and dep.upos in ("ADJ", "NOUN")):
                        parts = sorted([dep, word], key=lambda w: w.id)
                        candidates.append(_make_phrase(parts, "noun_phrase", "dep", freq))

            if word.upos == "VERB":
                for dep in sent.words:
                    if (dep.head == word.id
                            and dep.deprel in _DEP_VERB_RELS
                            and dep.upos == "NOUN"):
                        parts = sorted([word, dep], key=lambda w: w.id)
                        candidates.append(_make_phrase(parts, "verb_phrase", "dep", freq))

    # --- Deduplicate by lemma-normalized text ---
    seen = set()
    unique = []
    for c in candidates:
        if c["text"] not in seen:
            seen.add(c["text"])
            unique.append(c)

    # --- Filter: both components must be in freq list ---
    # Phrases with unknown components are likely Stanza artifacts, not real collocations.
    unique = [c for c in unique if all(freq.get(comp) is not None for comp in c["_components"])]

    # --- Score: max(component_weights) + adjustments ---
    collocations = get_collocations(lang)
    scored = []
    too_generic_phrases = []
    for c in unique:
        weights = [rank_to_weight(freq.get(comp), lang, level) for comp in c["_components"]]
        if not any(w >= 1.0 for w in weights):
            continue  # at least one component must be in target band
        in_whitelist = c["text"] in collocations
        # Skip phrases where any component is too generic for its POS,
        # unless the phrase appears in the collocation whitelist.
        if not in_whitelist:
            too_generic = False
            lang_caps = _PHRASE_RANK_CAPS.get(lang, {})
            for comp, pos in zip(c["_components"], c["_component_pos"]):
                cap = lang_caps.get(pos)
                if cap and freq.get(comp, float("inf")) <= cap:
                    too_generic = True
                    break
            if too_generic:
                score = max(weights)
                c["score"] = min(score, 1.0)
                too_generic_phrases.append(c)
                continue
        score = max(weights)
        if c["type"] == "verb_phrase":
            score += 0.05
        if all(0.3 < w <= 1.0 for w in weights):
            score += 0.05  # all target-band
        c["score"] = min(score, 1.0)
        scored.append(c)

    scored.sort(key=lambda c: c["score"], reverse=True)
    too_generic_phrases.sort(key=lambda c: c["score"], reverse=True)
    return scored[:20], too_generic_phrases


def _make_phrase(parts: list, ptype: str, source: str, freq: dict[str, int] | None = None) -> dict:
    """Build a phrase candidate dict from a list of Stanza words."""
    components = [_clean_lemma(p.lemma, freq).lower() for p in parts]
    return {
        "surface": " ".join(p.text for p in parts),
        "text": " ".join(components),
        "type": ptype,
        "source": source,
        "_components": components,
        "_component_pos": [p.upos for p in parts],
    }


def extract(doc, lang: str, freq: dict[str, int], level: str = "A0") -> dict:
    """Extract and rank vocabulary candidates from a Stanza doc.

    Pipeline:
    1. Collect NOUN/VERB/ADJ tokens + reconstruct Dutch separable verbs
    2. Clean compound lemmas (rejoin underscores)
    3. Surface form fallback for bad Stanza lemmas
    4. Filter noise (spaces, demonyms, determiners)
    5. Deduplicate, rank by frequency, score by CEFR level
    """
    candidates = []
    proper_nouns = []
    numbers = []
    merged_fragments = []

    # Pre-pass: collect all proper noun surface forms so we can skip mis-tagged
    # instances during collection. Stanza sometimes tags a proper noun as NOUN
    # (e.g. sentence-initial "CAB"), so we need to know PROPN surfaces upfront.
    # We track exact surface forms (not lowercased) to avoid filtering legitimate
    # common nouns that happen to share a lemma (e.g. "payments" vs "Payments").
    propn_surfaces = set()
    propn_stems = set()
    for sent in doc.sentences:
        for word in sent.words:
            if word.upos == "PROPN":
                propn_surfaces.add(word.text)
                propn_stems.add(word.lemma.lower())

    # --- Step 1: Collect tokens by POS ---
    # Every UPOS must be handled explicitly — never silently ignore a tag.
    # Candidates: extracted and ranked for learners
    # Separate lists: shown in their own card (proper nouns, numbers)
    # Dropped: function words / structural tokens, not useful for learners
    _CANDIDATE_POS = {"NOUN", "VERB", "ADJ", "ADV", "DET"}
    _DROPPED_POS = {
        "ADP",    # prepositions (u, na, za) — tested as candidates, d dropped 0.85→0.46
        "PRON",   # pronouns (ja, on, to) — tested as candidates, noise at A1+
        "AUX",    # auxiliary verbs (je, sam, će) — function words
        "CCONJ",  # coordinating conjunctions (i, ali, ili)
        "SCONJ",  # subordinating conjunctions (da, jer, kad)
        "PART",   # particles (ne, li)
        "INTJ",   # interjections — rare
        "PUNCT",  # punctuation
        "SYM",    # symbols
        "X",      # foreign/other
    }
    for sent in doc.sentences:
        # Build lookup for merge logic
        words_by_id = {w.id: w for w in sent.words}

        # Identify tokens to skip (merged into a neighbor)
        _skip = set()

        # Merge hyphenated compounds: "cross-border" → "cross" + "-" + "border"
        # Stanza splits hyphenated words into parts with deprel=compound
        # and a PUNCT "-" between them. Rejoin into "part1-part2".
        for word in sent.words:
            if word.deprel == "compound" and word.head > 0 and word.id not in _skip:
                head = words_by_id.get(word.head)
                hyphen = words_by_id.get(word.id + 1)
                if (head and hyphen
                        and hyphen.text == "-" and hyphen.upos == "PUNCT"
                        and hyphen.id + 1 == head.id):
                    merged_text = f"{word.text}-{head.text}"
                    merged_fragments.append({
                        "parts": [word.text, head.text],
                        "merged": merged_text,
                        "rule": "hyphen",
                    })
                    head.text = merged_text
                    head.lemma = merged_text
                    _skip.add(word.id)
                    _skip.add(hyphen.id)

        # Merge single-char compound fragments with their head.
        # Stanza splits "XA90P" → "XA90"(compound→Token) + "P"(compound→Token)
        # and "95p" → "95"(nummod→p) + "p". Rejoin these before collection.
        for word in sent.words:
            if len(word.text) == 1 and word.deprel == "compound" and word.head > 0:
                head = words_by_id.get(word.head)
                if head:
                    # Find all compound fragments pointing at the same head
                    parts = sorted(
                        [w for w in sent.words if w.head == head.id and w.deprel == "compound"]
                        + [head],
                        key=lambda w: w.id,
                    )
                    original_parts = [w.text for w in parts]
                    merged = "".join(original_parts)
                    merged_fragments.append({
                        "parts": original_parts,
                        "merged": merged,
                        "rule": "compound",
                    })
                    head.text = merged
                    head.lemma = merged
                    for w in parts:
                        if w.id != head.id:
                            _skip.add(w.id)

            # "95p" pattern: single-char NOUN with a NUM child via nummod → skip it
            # The NUM already goes to the numbers list; the suffix is not vocabulary.
            if len(word.text) == 1 and word.upos == "NOUN":
                num_child = next(
                    (w for w in sent.words if w.head == word.id and w.deprel == "nummod" and w.upos == "NUM"),
                    None,
                )
                if num_child:
                    merged_fragments.append({
                        "parts": [num_child.text, word.text],
                        "merged": f"({num_child.text}{word.text} → dropped suffix)",
                        "rule": "num_suffix",
                    })
                    _skip.add(word.id)

        for word in sent.words:
            if word.id in _skip:
                continue
            if word.upos == "PROPN":
                proper_nouns.append({"text": word.lemma, "pos": "PROPN"})
            elif word.upos == "NUM":
                numbers.append({"text": word.text, "pos": "NUM"})
            elif word.upos in _CANDIDATE_POS:
                # Skip words whose surface form matches a known proper noun
                # (e.g. "CAB" mis-tagged as NOUN). Uses exact surface match so
                # lowercase "payments" (legitimate) isn't blocked by "Payments" (PROPN).
                if word.text in propn_surfaces:
                    continue
                item = {"text": word.lemma, "pos": word.upos, "_surface": word.text, "_sent_initial": word.id == 1}
                if word.upos == "VERB":
                    item["_verb_id"] = word.id
                candidates.append(item)
            elif word.upos not in _DROPPED_POS:
                logging.getLogger("pipeline").warning(f"Unhandled POS: {word.upos} for '{word.text}'")

        # Separable verbs: "belt...op" → "op|bellen" (Dutch, German)
        if LANG_PRESETS[lang].get("separable_verbs", False):
            sep_verbs, sep_verb_ids = extract_separable_verbs(sent)
            candidates = [c for c in candidates if c.get("_verb_id") not in sep_verb_ids]
            candidates.extend(sep_verbs)

    # --- Step 2: Clean compound lemmas ---
    # Stanza splits Dutch compounds with underscores; try to rejoin them
    for item in candidates:
        item["text"] = _clean_lemma(item["text"], freq)

    # --- Step 3: Surface form fallback ---
    # When Stanza's lemma isn't in the freq list but the original surface form is,
    # use the surface form. Catches cases where Stanza over-strips:
    # e.g. surface "verzekerd" with bad lemma "verzekerd_zijn" → use "verzekerd"
    for item in candidates:
        lemma = item["text"].lower()
        surface = item.get("_surface", "").lower()
        if lemma != surface and lemma not in freq and surface in freq:
            item["text"] = surface

    # --- Step 4: Filter noise ---

    # Failed compound rejoins leave spaces (e.g. "taal model", "AI gebruik", "mee denen").
    # If _clean_lemma couldn't rejoin them, they're unverifiable garbage.
    candidates = [item for item in candidates if " " not in item["text"]]

    # Demonym/nationality adjectives (e.g. "Israëlisch", "Palestijns") — derived from
    # proper nouns, not useful vocabulary items for learners
    candidates = [item for item in candidates
                  if not (item["pos"] == "ADJ" and item["text"][0:1].isupper())]

    # Determiners (de, het, een) — too trivial for any level
    candidates = [item for item in candidates if item["pos"] != "DET"]

    # Numeric tokens (e.g. "2026.", "26.", "1.") — not vocabulary
    candidates = [item for item in candidates if not re.match(r"^\d+\.?$", item["text"])]

    # Probable proper nouns mis-tagged as NOUN/ADJ by Stanza.
    # If the surface form is capitalized mid-sentence and the lemma isn't in
    # the frequency list, it's almost certainly a name (e.g. "zelenski", "iPhona").
    # Sentence-initial words are skipped since capitalization is ambiguous there.
    if LANG_PRESETS[lang].get("filter_propn_by_surface", False):
        candidates = [item for item in candidates
                      if not (item.get("_surface", "")[0:1].isupper()
                              and not item.get("_sent_initial", False)
                              and item["text"].lower() not in freq)]

    # --- Step 5: Deduplicate ---
    seen = set()
    unique = []
    for item in candidates:
        key = item["text"].lower()
        if key not in seen:
            seen.add(key)
            unique.append(item)

    # --- Step 6: Rank and score ---
    level_settings = LANG_PRESETS[lang]["levels"][level]
    band = level_settings["band"]
    for item in unique:
        item.pop("_surface", None)
        item.pop("_sent_initial", None)
        item.pop("_verb_id", None)
        rank_key = item.pop("_rank_key", item["text"].lower())
        rank = freq.get(rank_key)
        item["rank"] = rank
        weight = rank_to_weight(rank, lang, level)
        if item["pos"] == "ADV":
            weight *= level_settings.get("adv_weight", 1.0)
        item["weight"] = weight
        item["in_target"] = rank is not None and band["known"] < rank <= band["target"]

    unique.sort(key=lambda x: x["weight"], reverse=True)

    # --- Step 7: Phrase extraction ---
    phrases, too_generic_phrases = extract_phrases(doc, lang, freq, level)

    # --- Step 8: Merge into unified items list ---
    # Only phrases above threshold swallow their component singles.
    # Rejected phrases must not eat singles — the single is the fallback.
    _THRESHOLD = 0.5
    max_phrases = level_settings.get("max_phrases", 3)
    for p in phrases:
        p.pop("_component_pos", None)

    # Select top phrases up to the cap
    accepted_phrases = [p for p in phrases if p["score"] > _THRESHOLD][:max_phrases]

    # Only swallow components of accepted phrases
    phrase_components = set()
    for p in accepted_phrases:
        phrase_components.update(p.pop("_components"))
    for p in phrases:
        p.pop("_components", None)

    items = []
    for item in unique:
        if item["text"].lower() in phrase_components:
            continue
        items.append({
            "text": item["text"],
            "surface": item["text"],
            "type": "single",
            "score": item["weight"],
            "pos": item["pos"],
            "rank": item["rank"],
            "in_target": item["in_target"],
        })
    for p in accepted_phrases:
        items.append(p)

    items.sort(key=lambda x: x["score"], reverse=True)

    # Deduplicate proper nouns
    seen_propn = set()
    unique_propn = []
    for item in proper_nouns:
        key = item["text"].lower()
        if key not in seen_propn:
            seen_propn.add(key)
            unique_propn.append(item)

    # Deduplicate numbers
    seen_num = set()
    unique_num = []
    for item in numbers:
        if item["text"] not in seen_num:
            seen_num.add(item["text"])
            unique_num.append(item)

    for p in too_generic_phrases:
        p.pop("_components", None)
        p.pop("_component_pos", None)

    return {"language": lang, "items": items, "proper_nouns": unique_propn, "numbers": unique_num, "merged_fragments": merged_fragments, "generic_phrases": too_generic_phrases}
