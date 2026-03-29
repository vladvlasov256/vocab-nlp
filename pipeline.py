"""Core NLP pipeline — shared by app.py (Modal) and cli.py (local)."""

import csv
import json
import logging
import math
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
        "collocation_min_count": 3,
        "collocation_min_npmi": 0.0,
        "collocation_boost": 1.0,
        "levels": {
            "A0": {"band": {"known": 100,   "target": 1000},  "adv_weight": 0.7, "max_phrases": 3, "threshold": 0.5, "verb_boost": 0.3},
            "A1": {"band": {"known": 500,   "target": 3000},  "adv_weight": 0.7, "max_phrases": 3, "threshold": 0.5, "verb_boost": 0.2},
            "A2": {"band": {"known": 1500,  "target": 5000},  "adv_weight": 1.0, "max_phrases": 3, "threshold": 0.5},
            "B1": {"band": {"known": 3000,  "target": 8000},  "adv_weight": 1.0, "max_phrases": 3, "threshold": 0.5},
        },
    },
    "sr": {
        "name": "Serbian",
        "filter_propn_by_surface": True,
        "separable_verbs": False,
        "collocation_min_count": 3,
        "collocation_min_npmi": 0.0,
        "collocation_boost": 1.0,
        "levels": {
            "A0": {"band": {"known": 30,    "target": 1500},  "adv_weight": 0.7, "max_phrases": 3, "threshold": 0.5, "verb_boost": 0.3},
            "A1": {"band": {"known": 200,   "target": 3000},  "adv_weight": 0.7, "max_phrases": 3, "threshold": 0.5, "verb_boost": 0.2},
            "A2": {"band": {"known": 500,   "target": 5000},  "adv_weight": 1.0, "max_phrases": 2, "threshold": 0.5},
            "B1": {"band": {"known": 2000,  "target": 8000},  "adv_weight": 1.0, "max_phrases": 3, "threshold": 0.5},
        },
    },
    "en": {
        "name": "English",
        "filter_propn_by_surface": True,
        "separable_verbs": False,
        "collocation_min_count": 20,
        "collocation_min_npmi": 0.15,
        "collocation_boost": 0.5,
        "levels": {
            "A0": {"band": {"known": 100,   "target": 1000},  "adv_weight": 0.7, "max_phrases": 3, "threshold": 0.5, "verb_boost": 0.3},
            "A1": {"band": {"known": 300,   "target": 3000},  "adv_weight": 0.7, "max_phrases": 3, "threshold": 0.5, "verb_boost": 0.2},
            "A2": {"band": {"known": 800,   "target": 5000},  "adv_weight": 1.0, "max_phrases": 2, "threshold": 0.5, "verb_boost": 0.35},
            "B1": {"band": {"known": 1500,  "target": 8000},  "adv_weight": 1.0, "max_phrases": 3, "threshold": 0.5, "verb_boost": 0.25},
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


def _load_collocations(lang: str) -> dict[str, float]:
    """Load collocation whitelist for a language. Returns {bigram: npmi} dict."""
    path = DATA_DIR / f"collocations_{lang}.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    preset = LANG_PRESETS.get(lang, {})
    min_count = preset.get("collocation_min_count", 3)
    min_npmi = preset.get("collocation_min_npmi", 0.0)
    bigrams: dict[str, float] = {}
    for items in data.values():
        for item in items:
            if item.get("count", 0) < min_count:
                continue
            npmi = item.get("npmi", 0.0)
            if npmi < min_npmi:
                continue
            bigrams[item["bigram"]] = npmi
    return bigrams


_COLLOCATIONS: dict[str, dict[str, float]] = {}


def get_collocations(lang: str) -> dict[str, float]:
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


def extract_separable_verbs(sent, freq: dict[str, int]) -> list[dict]:
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
            # Rank by the full separable verb if it exists in the freq list,
            # otherwise fall back to base verb. "meespelen" (rank 8394) is a
            # different word from "spelen" (rank 400).
            joined = particle.text.lower() + verb.lemma.lower()
            rank_key = joined if freq.get(joined) is not None else verb.lemma.lower()
            results.append({
                "text": reconstructed,
                "pos": "VERB",
                "_rank_key": rank_key,
            })
            replaced_verb_ids.add(verb.id)
    return results, replaced_verb_ids


# Dutch compound connectors used between parts of compound words.
# e.g. "doorzetting" + "s" + "vermogen" → "doorzettingsvermogen"
_NL_CONNECTORS = ("", "s", "e", "en", "er")


def _clean_lemma(text: str, freq: dict[str, int] | None = None) -> tuple[str, tuple[str, ...] | None]:
    """Fix Stanza's underscore-split compound lemmas.

    Stanza sometimes lemmatizes Dutch compounds with underscores:
      "doorzettingsvermogen" → "doorzetting_vermogen"
      "computerprogramma" → "computer_programma"

    We try rejoining the two parts with common Dutch connectors and validate
    against the frequency list. If a valid compound exists, use it.
    Otherwise fall through and just strip underscores (produces a space-separated
    form that will be filtered out later by the space filter).

    Returns (cleaned_text, parts) where parts is a tuple of the original
    underscore-split components, or None if no split occurred.
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
                return best, (a, b)
            # Not in freq — return space-separated but keep parts for ranking
            return f"{a} {b}", (a, b)
        # More than 2 parts — just strip underscores
    return re.sub(r"[_]+", " ", text).strip(), None


# Per-language rank caps for phrase filtering. Words ranked below these
# thresholds are too generic to form useful collocations.
# "hebben contract" (verb rank ~23 in NL) is noise,
# "voeren gesprek" (verb rank ~800 in NL) is a real collocation.
_PHRASE_RANK_CAPS = {
    "nl": {"VERB": 250, "NOUN": 100, "ADJ": {"A0": 200, "A1": 300, "A2": 700, "B1": 700}},
    "en": {"VERB": 150, "NOUN": 80,  "ADJ": {"A0": 150, "A1": 250, "A2": 600, "B1": 600}},
    "sr": {"VERB": 150, "NOUN": 80,  "ADJ": {"A0": 150, "A1": 250, "A2": 300, "B1": 300}},
}

_PHRASE_BIGRAMS = {
    ("ADJ", "NOUN"): "noun_phrase",
    ("NOUN", "NOUN"): "noun_phrase",
    ("VERB", "NOUN"): "verb_phrase",
    ("VERB", "ADP"): "verb_phrase",
}

_DEP_NOUN_RELS = {"amod", "compound", "nmod"}
_DEP_VERB_RELS = {"obj"}


def extract_phrases(doc, lang: str, freq: dict[str, int], level: str = "A0", propn_stems: set | None = None) -> list[dict]:
    """Extract multi-word phrase candidates from dependency parse and POS bigrams.

    Dependency-based extraction:
    - ADJ→NOUN (amod), NOUN→NOUN (compound)
    - VERB→NOUN (obj)
    - VERB+ADP (positional, whitelist-gated: "talk about", "sit down")

    Scoring uses max(component_weights) so phrases compete on the same
    0-1 scale as single-word candidates.
    """
    candidates = []
    collocations = get_collocations(lang)

    for sent in doc.sentences:
        words = sent.words
        # --- Dependency-based extraction ---
        for word in words:
            if word.upos == "NOUN":
                for dep in words:
                    if (dep.head == word.id
                            and dep.deprel in _DEP_NOUN_RELS
                            and dep.upos in ("ADJ", "NOUN")):
                        # Skip demonym/nationality ADJ (always capitalized in Dutch,
                        # e.g. "Ierse", "Nederlandse") — not useful phrase components.
                        if dep.upos == "ADJ" and dep.text[0:1].isupper():
                            continue
                        # nmod (NOUN+NOUN genitive) is broad and noisy —
                        # only allow collocation-backed phrases.
                        # TODO: corpus extraction only captures ADJ+NOUN, VERB+NOUN,
                        # VERB+ADP — no NOUN+NOUN collocations. "liga šampiona" is
                        # blocked here. Need NOUN+NOUN collocation extraction or
                        # manual whitelist entries.
                        if dep.deprel == "nmod":
                            if not collocations:
                                continue
                            parts_sorted = sorted([dep, word], key=lambda w: w.id)
                            key = " ".join(_clean_lemma(p.lemma, freq)[0].lower() for p in parts_sorted)
                            if key not in collocations:
                                continue
                        parts = sorted([dep, word], key=lambda w: w.id)
                        candidates.append(_make_phrase(parts, "noun_phrase", "dep", freq))

            if word.upos == "VERB":
                for dep in words:
                    if (dep.head == word.id
                            and dep.deprel in _DEP_VERB_RELS
                            and dep.upos == "NOUN"):
                        parts = sorted([word, dep], key=lambda w: w.id)
                        candidates.append(_make_phrase(parts, "verb_phrase", "dep", freq))

        # --- VERB+ADP positional extraction (whitelist-gated) ---
        # Prepositions attach to nouns in dependency parse, not verbs,
        # so we use positional bigrams and require collocation whitelist match.
        for i, word in enumerate(words):
            if word.upos != "VERB":
                continue
            for j in range(i + 1, min(i + 3, len(words))):
                w2 = words[j]
                if w2.upos == "ADP":
                    lemma1 = (word.lemma or word.text).lower()
                    lemma2 = (w2.lemma or w2.text).lower()
                    colloc_key = f"{lemma1} {lemma2}"
                    if colloc_key in collocations:
                        candidates.append(_make_phrase([word, w2], "verb_phrase", "dep", freq))
                    break  # only first ADP after verb
                if w2.upos in ("VERB", "NOUN", "PROPN"):
                    break  # stop if we hit another content word

    # --- Deduplicate by component lemmas (not display text) ---
    # "liga šampiona" and "lige šampiona" are the same phrase in different cases.
    seen = set()
    unique = []
    for c in candidates:
        key = " ".join(c["_components"])
        if key not in seen:
            seen.add(key)
            unique.append(c)

    # --- Filter: both components must be in freq list ---
    # Phrases with unknown components are likely Stanza artifacts, not real collocations.
    unique = [c for c in unique if all(freq.get(comp) is not None for comp in c["_components"])]

    # --- Filter: skip phrases containing known proper nouns ---
    # Stanza sometimes mis-tags PROPN as NOUN mid-sentence (e.g. "CAB Payments").
    if propn_stems:
        unique = [c for c in unique if not any(comp in propn_stems for comp in c["_components"])]

    # --- Filter: skip redundant compounds where one component contains the other ---
    # e.g. "health healthcare" — healthcare already contains "health".
    unique = [c for c in unique if not any(
        a != b and (a in b or b in a)
        for a, b in [(c["_components"][0], c["_components"][1])]
    )]

    # --- Filter: limit phrases sharing a component word ---
    # Prevents spam like "trading platform", "trading bots", "trading choice"
    # all dominating the list. Keep at most 2 phrases per shared component.
    _comp_counts: dict[str, int] = {}
    _capped = []
    for c in unique:
        comps = c["_components"]
        if all(_comp_counts.get(w, 0) < 2 for w in comps):
            _capped.append(c)
            for w in comps:
                _comp_counts[w] = _comp_counts.get(w, 0) + 1
    unique = _capped

    # --- Score: max(component_weights) + adjustments ---
    collocations = get_collocations(lang)
    scored = []
    too_generic_phrases = []
    for c in unique:
        colloc_key = " ".join(c["_components"])
        npmi = collocations.get(colloc_key)
        in_whitelist = npmi is not None
        weights = [rank_to_weight(freq.get(comp), lang, level) for comp in c["_components"]]
        # VERB+ADP phrases are whitelist-gated at extraction, so both components
        # being known-band is expected — skip the weight filter for them.
        is_verb_adp = "ADP" in c.get("_component_pos", [])
        if not is_verb_adp and not any(w >= 0.6 for w in weights):
            continue  # at least one component must be in target or beyond band
        # VERB+NOUN phrases must be in whitelist — dep obj is too noisy otherwise.
        if c["type"] == "verb_phrase" and not is_verb_adp and not in_whitelist:
            score = max(weights)
            c["score"] = min(score, 1.0)
            too_generic_phrases.append(c)
            continue
        # Skip phrases where any component is too generic for its POS,
        # unless the phrase appears in the collocation whitelist.
        if not in_whitelist:
            too_generic = False
            lang_caps = _PHRASE_RANK_CAPS.get(lang, {})
            for comp, pos in zip(c["_components"], c["_component_pos"]):
                cap = lang_caps.get(pos)
                if isinstance(cap, dict):
                    cap = cap.get(level, 0)
                if cap and freq.get(comp, float("inf")) <= cap:
                    too_generic = True
                    break
            if too_generic:
                score = max(weights)
                c["score"] = min(score, 1.0)
                too_generic_phrases.append(c)
                continue
        score = max(weights)
        # VERB+ADP collocations: both components are known-band, but the
        # combination is the vocabulary item ("talk about", "sit down").
        # Score based on NPMI strength rather than component frequency.
        if is_verb_adp and in_whitelist:
            score = 0.6 + npmi * 0.4  # NPMI 0.5 → 0.80, NPMI 0.3 → 0.72
        else:
            if c["type"] == "verb_phrase":
                score += 0.05
            if all(0.3 < w <= 1.0 for w in weights):
                score += 0.05  # all target-band
        # Corpus-backed phrases get an NPMI boost so they compete with singles
        if not is_verb_adp and npmi is not None and npmi > 0:
            boost_factor = LANG_PRESETS.get(lang, {}).get("collocation_boost", 1.0)
            score *= (1 + npmi * boost_factor)
        c["score"] = min(score, 1.0)
        c["_colloc_backed"] = in_whitelist
        scored.append(c)

    scored.sort(key=lambda c: c["score"], reverse=True)
    too_generic_phrases.sort(key=lambda c: c["score"], reverse=True)
    return scored[:20], too_generic_phrases


def _make_phrase(parts: list, ptype: str, source: str, freq: dict[str, int] | None = None) -> dict:
    """Build a phrase candidate dict from a list of Stanza words."""
    components = [_clean_lemma(p.lemma, freq)[0].lower() for p in parts]
    # Display text: use surface form for ADJ, compound modifiers, and nmod
    # dependents (genitive nouns: "liga šampiona" not "liga šampion").
    # ADJ surface gives natural forms: "digitale munt" not "digitaal munt",
    # "bidding war" not "bid war", "swimming pool" not "swim pool".
    # TODO: SR ADJ surface shows inflected case ("veštačke inteligencije"
    # instead of "veštačka inteligencija"). NL is fine because Dutch ADJ
    # attributive form is consistent. Fix needs nominative case detection
    # from Stanza feats or SR-specific lemma form for ADJ.
    display = []
    for p in parts:
        if p.upos == "ADJ" or p.deprel in ("compound", "nmod"):
            display.append(p.text.lower())
        else:
            display.append(_clean_lemma(p.lemma, freq)[0].lower())
    return {
        "surface": " ".join(p.text for p in parts),
        "text": " ".join(display),
        "type": ptype,
        "source": source,
        "_components": components,
        "_component_pos": [p.upos for p in parts],
    }


def extract(doc, lang: str, freq: dict[str, int], level: str = "A0", join_separable: bool = False) -> dict:
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
    for sent_idx, sent in enumerate(doc.sentences):
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

        # Merge compound NOUNs: Stanza splits Dutch compounds like
        # "blockchaintechnologie" → "blockchain"(compound→technologie) + "technologie".
        # Rejoin when the joined form (with optional connector) exists in freq list.
        for word in sent.words:
            if (word.upos == "NOUN" and word.deprel == "compound"
                    and word.head > 0 and word.id not in _skip):
                head = words_by_id.get(word.head)
                if head and head.upos == "NOUN" and head.id not in _skip:
                    a = word.text.lower()
                    b = head.text.lower()
                    best, best_rank = None, float("inf")
                    for conn in _NL_CONNECTORS:
                        compound = a + conn + b
                        rank = freq.get(compound)
                        if rank is not None and rank < best_rank:
                            best, best_rank = compound, rank
                    if best is not None:
                        merged_fragments.append({
                            "parts": [word.text, head.text],
                            "merged": best,
                            "rule": "compound_noun",
                        })
                        head.text = best
                        head.lemma = best
                        _skip.add(word.id)

        for word in sent.words:
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
                item = {"text": word.lemma, "pos": word.upos, "_surface": word.text, "_sent_initial": word.id == 1, "_sent_idx": sent_idx}
                if word.upos == "VERB":
                    item["_verb_id"] = word.id
                    # SR reflexive verbs: "boriti se", "menjati se" — flag for
                    # display after scoring (keep plain lemma for freq lookup).
                    if lang == "sr":
                        has_se = any(
                            w.head == word.id and w.deprel == "expl" and w.lemma == "sebe"
                            for w in sent.words
                        )
                        if has_se:
                            item["_reflexive"] = True
                candidates.append(item)
            elif word.upos not in _DROPPED_POS:
                logging.getLogger("pipeline").warning(f"Unhandled POS: {word.upos} for '{word.text}'")

        # Separable verbs: "belt...op" → "op|bellen" (Dutch, German)
        if LANG_PRESETS[lang].get("separable_verbs", False):
            sep_verbs, sep_verb_ids = extract_separable_verbs(sent, freq)
            candidates = [c for c in candidates if c.get("_verb_id") not in sep_verb_ids]
            candidates.extend(sep_verbs)

    # --- Step 2: Clean compound lemmas ---
    # Stanza splits Dutch compounds with underscores; try to rejoin them.
    # Store parts tuple for compound-aware scoring.
    for item in candidates:
        cleaned, parts = _clean_lemma(item["text"], freq)
        item["text"] = cleaned
        if parts:
            item["_parts"] = parts

    # --- Step 3: Surface form fallback ---
    # When Stanza's lemma isn't in the freq list but the original surface form is,
    # use the surface form. Catches cases where Stanza over-strips:
    # e.g. surface "verzekerd" with bad lemma "verzekerd_zijn" → use "verzekerd"
    # Also: when _clean_lemma produced spaces but surface is a single word
    # (e.g. lemma "blockchain technologie" but surface "blockchaintechnologie"),
    # prefer the surface — it's the actual word the learner sees.
    for item in candidates:
        lemma = item["text"].lower()
        surface = item.get("_surface", "").lower()
        if lemma != surface:
            if " " in lemma and " " not in surface:
                item["text"] = surface
            elif lemma not in freq and surface in freq:
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

    # Hyphenated jargon not in freq list (e.g. "non-dom").
    # Allow compounds where both parts are in freq list and at least one
    # part ranks above the known band (not just two generic words).
    def _keep_hyphenated(text):
        if "-" not in text:
            return True
        if text.lower() in freq:
            return True
        parts = text.lower().split("-", 1)
        if len(parts) != 2 or not all(freq.get(p) is not None for p in parts):
            return False
        known = LANG_PRESETS[lang]["levels"][level]["band"]["known"]
        return all(freq.get(p) > known for p in parts)
    candidates = [item for item in candidates if _keep_hyphenated(item["text"])]

    # Probable proper nouns mis-tagged as NOUN/ADJ by Stanza.
    # If the surface form is capitalized mid-sentence and the lemma isn't in
    # the frequency list, it's almost certainly a name (e.g. "zelenski", "iPhona").
    # Sentence-initial words are skipped since capitalization is ambiguous there.
    if LANG_PRESETS[lang].get("filter_propn_by_surface", False):
        candidates = [item for item in candidates
                      if not (item.get("_surface", "")[0:1].isupper()
                              and not item.get("_sent_initial", False)
                              and item["text"].lower() not in freq)]

    # --- Step 5: Count occurrences + Deduplicate ---
    # Count how many times each lemma appears (before dedup) for repetition boost.
    from collections import Counter
    _lemma_counts = Counter(item["text"].lower() for item in candidates)
    _total_tokens = len(candidates)
    # Track which lemmas appear in the first sentence
    _in_first_sent = {item["text"].lower() for item in candidates if item.get("_sent_idx") == 0}

    # Pre-seed seen set with joined forms of separable verbs so standalone
    # duplicates like "plaatsvinden" are suppressed when "plaats|vinden" exists.
    seen = set()
    for item in candidates:
        if "|" in item["text"]:
            seen.add(item["text"].replace("|", "").lower())
    unique = []
    for item in candidates:
        key = item["text"].lower()
        if key not in seen:
            seen.add(key)
            item["_count"] = _lemma_counts[key]
            item["_in_first_sent"] = key in _in_first_sent
            unique.append(item)
        elif "|" in item["text"]:
            # Always keep the separable verb itself
            item["_count"] = 1
            item["_in_first_sent"] = key in _in_first_sent
            unique.append(item)

    # --- Step 6: Join separable verbs if requested (benchmark mode) ---
    # Must happen AFTER dedup so pipe-based dedup logic works.
    if join_separable:
        for item in unique:
            if "|" in item["text"]:
                item["text"] = item["text"].replace("|", "")

    # --- Step 7: Rank and score ---
    level_settings = LANG_PRESETS[lang]["levels"][level]
    band = level_settings["band"]
    for item in unique:
        item.pop("_surface", None)
        item.pop("_sent_initial", None)
        item.pop("_sent_idx", None)
        item.pop("_verb_id", None)
        parts = item.pop("_parts", None)
        rank_key = item.pop("_rank_key", item["text"].lower())
        rank = freq.get(rank_key)
        item["rank"] = rank
        # Compound-aware scoring: demote by parts only when the compound
        # itself is beyond target. Target-band compounds like "hoofdpijn"
        # (rank 3095) should keep their own score even if parts are common.
        # e.g. "plaatsvinden" (rank 8028, beyond target) → parts both known-band → score as known.
        # e.g. "hoofdpijn" (rank 3095, target-band) → keep score 1.0 despite common parts.
        if parts and rank is not None and rank > band["target"]:
            part_ranks = [freq.get(p) for p in parts]
            if all(r is not None and r <= band["known"] for r in part_ranks):
                weight = max(rank_to_weight(r, lang, level) for r in part_ranks)
            else:
                weight = rank_to_weight(rank, lang, level)
        elif parts and rank is not None:
            weight = rank_to_weight(rank, lang, level)
        elif parts and rank is None:
            # Compound not in freq list — score by the least common part
            part_ranks = [freq.get(p) for p in parts]
            known_ranks = [r for r in part_ranks if r is not None]
            if known_ranks:
                weight = rank_to_weight(max(known_ranks), lang, level)
            else:
                weight = rank_to_weight(None, lang, level)
        else:
            weight = rank_to_weight(rank, lang, level)
        if item["pos"] == "ADV":
            weight *= level_settings.get("adv_weight", 1.0)
        if item["pos"] == "VERB":
            weight += level_settings.get("verb_boost", 0)
        # Contextual boost: TF-IDF-like overrepresentation + first-sentence signal.
        # Words that appear more often than expected (given their corpus rank) in this
        # specific text are likely topical. This lets known-band words like "bedrijf"
        # (rank ~1200) cross the 0.5 threshold when they're central to the text.
        count = item.pop("_count", 1)
        in_first_sent = item.pop("_in_first_sent", False)
        if rank is not None and rank > 0 and _total_tokens > 0:
            overrep = count * rank / _total_tokens
            contextual_bonus = math.log2(max(1, overrep)) * 0.15
            if in_first_sent:
                contextual_bonus += 0.1
            weight = weight + contextual_bonus
        elif count > 1:
            weight = weight * count
        item["weight"] = min(weight, 1.0)  # capped, for output score
        item["in_target"] = rank is not None and band["known"] < rank <= band["target"]
        # Sort key: weight + count-based tiebreaker using log(rank) instead
        # of raw rank. This compresses the rarity advantage so "wedstrijd"
        # (rank 1022, 2x) can outrank "kwartfinale" (rank 76k, 1x).
        if rank is not None and rank > 0:
            sort_bonus = count * math.log2(max(2, rank)) * 0.02
        else:
            sort_bonus = count * 0.1
        if in_first_sent:
            sort_bonus += 0.1
        item["_sort_key"] = item["weight"] + sort_bonus

    unique.sort(key=lambda x: x["_sort_key"], reverse=True)

    # Append "se" to SR reflexive verbs after scoring (freq lookup used plain lemma).
    for item in unique:
        if item.pop("_reflexive", False):
            item["text"] = item["text"] + " se"

    # --- Step 7: Phrase extraction ---
    phrases, too_generic_phrases = extract_phrases(doc, lang, freq, level, propn_stems=propn_stems)

    # --- Step 8: Merge into unified items list ---
    # Only phrases above threshold swallow their component singles.
    # Rejected phrases must not eat singles — the single is the fallback.
    _THRESHOLD = level_settings.get("threshold", 0.5)
    for p in phrases:
        p.pop("_component_pos", None)

    # No hard cap — corpus-boosted scores let phrases compete with singles naturally
    accepted_phrases = [p for p in phrases if p["score"] > _THRESHOLD]

    # Build a map of component → best sort_key so phrases can inherit ranking.
    component_sort_keys: dict[str, float] = {}
    for item in unique:
        component_sort_keys[item["text"].lower()] = item["_sort_key"]

    # Assign phrase sort keys before popping _components.
    # Phrases inherit the best component sort_key (since they swallow those singles).
    for p in accepted_phrases:
        if "_sort_key" not in p:
            comp_keys = [component_sort_keys.get(c, 0) for c in p.get("_components", [])]
            base = max(comp_keys) if comp_keys else p["score"]
            boost = 0.2 if p.get("_colloc_backed") else 0.05
            p["_sort_key"] = base + boost

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
            "_sort_key": item["_sort_key"],
            "pos": item["pos"],
            "rank": item["rank"],
            "in_target": item["in_target"],
        })
    for p in accepted_phrases:
        items.append(p)

    items.sort(key=lambda x: x["_sort_key"], reverse=True)
    for item in items:
        item.pop("_sort_key", None)
        item.pop("_colloc_backed", None)

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
