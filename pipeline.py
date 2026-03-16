"""Core NLP pipeline — shared by app.py (Modal) and cli.py (local)."""

import csv
import logging
import re
from pathlib import Path

MAX_TEXT_BYTES = 4096
MAX_LEMMAS = 15

# Per-language presets: CEFR level bands + display name.
# "known" = top N most frequent words (skip these, too easy)
# "target" = words ranked up to this position (prioritize these)
# Words beyond "target" still appear but score lower.
LANG_PRESETS = {
    "nl": {
        "name": "Dutch",
        "level_bands": {
            "A0": {"known": 0,     "target": 1000},
            "A1": {"known": 500,   "target": 3000},
            "A2": {"known": 1500,  "target": 5000},
            "B1": {"known": 3000,  "target": 8000},
        },
    },
    "sr": {
        "name": "Serbian",
        "level_bands": {
            "A0": {"known": 0,     "target": 1500},
            "A1": {"known": 200,   "target": 3000},
            "A2": {"known": 1000,  "target": 5000},
            "B1": {"known": 2000,  "target": 8000},
        },
    },
}
LANGUAGES = list(LANG_PRESETS.keys())
LEVELS = list(LANG_PRESETS["nl"]["level_bands"].keys())

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


FREQ_LOADERS = {"nl": load_freq_nl, "sr": load_freq_sr}


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
        0.3 — word is in "known" band (too easy, learner already knows it)
        1.0 — word is in "target" band (sweet spot, should learn next)
        0.6 — word is beyond target or not in freq list (still useful but less relevant)

    The 0.5 threshold in the API filters out known-band words (0.3),
    keeping target (1.0) and beyond/unknown (0.6).
    """
    band = LANG_PRESETS[lang]["level_bands"][level]

    if rank is None:
        return 0.6  # not in freq list — potentially interesting domain vocab
    if rank <= band["known"]:
        return 0.3  # already known at this level
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
    for particle in particles:
        verb = verbs.get(particle.head)
        if verb:
            reconstructed = particle.text.lower() + verb.lemma
            results.append({
                "text": reconstructed,
                "pos": "VERB",
                "_rank_key": verb.lemma.lower(),
            })
    return results


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
    propn_stems = set()

    # --- Step 1: Collect tokens by POS ---
    # Every UPOS must be handled explicitly — never silently ignore a tag.
    # Candidates: extracted and ranked for learners
    # Separate lists: shown in their own card (proper nouns, numbers)
    # Dropped: function words / structural tokens, not useful for learners
    _CANDIDATE_POS = {"NOUN", "VERB", "ADJ", "DET"}
    _DROPPED_POS = {
        "ADP",    # prepositions (u, na, za) — function words
        "AUX",    # auxiliary verbs (je, sam, će) — function words
        "CCONJ",  # coordinating conjunctions (i, ali, ili)
        "SCONJ",  # subordinating conjunctions (da, jer, kad)
        "PRON",   # pronouns (ja, on, to)
        "PART",   # particles (ne, li)
        "INTJ",   # interjections — rare
        "PUNCT",  # punctuation
        "SYM",    # symbols
        "X",      # foreign/other
    }
    for sent in doc.sentences:
        for word in sent.words:
            if word.upos == "PROPN":
                proper_nouns.append({"text": word.lemma, "pos": "PROPN"})
                propn_stems.add(word.lemma.lower())
            elif word.upos == "NUM":
                numbers.append({"text": word.text, "pos": "NUM"})
            elif word.upos in _CANDIDATE_POS:
                candidates.append({"text": word.lemma, "pos": word.upos, "_surface": word.text})
            elif word.upos not in _DROPPED_POS:
                logging.getLogger("pipeline").warning(f"Unhandled POS: {word.upos} for '{word.text}'")

        # Dutch separable verbs: "belt...op" → "opbellen"
        if lang == "nl":
            candidates.extend(extract_separable_verbs(sent))

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

    # --- Step 5: Deduplicate ---
    seen = set()
    unique = []
    for item in candidates:
        key = item["text"].lower()
        if key not in seen:
            seen.add(key)
            unique.append(item)

    # --- Step 6: Rank and score ---
    for item in unique:
        item.pop("_surface", None)
        rank_key = item.pop("_rank_key", item["text"].lower())
        rank = freq.get(rank_key)
        item["rank"] = rank
        item["weight"] = rank_to_weight(rank, lang, level)
        band = LANG_PRESETS[lang]["level_bands"][level]
        item["in_target"] = rank is not None and band["known"] < rank <= band["target"]

    unique.sort(key=lambda x: x["weight"], reverse=True)

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

    return {"language": lang, "lemmas": unique, "proper_nouns": unique_propn, "numbers": unique_num}
