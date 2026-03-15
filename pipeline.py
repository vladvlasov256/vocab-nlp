"""Core NLP pipeline — shared by app.py (Modal) and cli.py (local)."""

import csv
import re
from pathlib import Path

MAX_TEXT_BYTES = 4096
MAX_LEMMAS = 15

# Rank bands per CEFR level
LEVEL_BANDS = {
    "A0": {"known": 0,     "target": 500},
    "A1": {"known": 500,   "target": 1500},
    "A2": {"known": 1500,  "target": 3000},
    "B1": {"known": 3000,  "target": 6000},
}
LEVELS = list(LEVEL_BANDS.keys())

_modal_data = Path("/root/data")
DATA_DIR = _modal_data if _modal_data.exists() else Path(__file__).parent / "data"
PROCESSORS = "tokenize,pos,lemma,depparse"
LANGUAGES = ["nl", "sr"]


def trim_text(text: str) -> str:
    """Step 0: Collapse whitespace and cap length."""
    text = re.sub(r"\s+", " ", text).strip()
    return text[:MAX_TEXT_BYTES]


def load_freq_nl() -> dict[str, int]:
    """Load SUBTLEX-NL frequency list. Returns {lemma: rank}."""
    freq = {}
    with open(DATA_DIR / "nl.csv", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for rank, row in enumerate(reader, 1):
            lemma = row.get("dominant.pos.lemma", row.get("Word", "")).lower()
            if lemma and lemma not in freq:
                freq[lemma] = rank
    return freq


def load_freq_sr() -> dict[str, int]:
    """Load Serbian 50k frequency list. Returns {word: rank}."""
    freq = {}
    with open(DATA_DIR / "sr.txt", encoding="utf-8") as f:
        for rank, line in enumerate(f, 1):
            parts = line.strip().split()
            if parts:
                freq[parts[0].lower()] = rank
    return freq


FREQ_LOADERS = {"nl": load_freq_nl, "sr": load_freq_sr}


def rank_to_weight(rank: int | None, level: str = "A0") -> float:
    """Score a word based on its frequency rank and the learner's level.

    Words in the learner's "known" band score low (already learned).
    Words in the "target" band score highest (should learn next).
    Words beyond target are still useful but less relevant.
    Unknown words get a moderate score (domain-specific vocab).
    """
    band = LEVEL_BANDS[level]

    if rank is None:
        return 0.6  # unknown = potentially interesting domain vocab
    if rank <= band["known"]:
        return 0.3  # already known at this level
    if rank <= band["target"]:
        return 1.0  # target zone — learn these
    return 0.6  # beyond target — still useful


def extract_separable_verbs(sent) -> list[dict]:
    """Dutch: reconstruct separable verbs from depparse (e.g. 'bel...op' → 'opbellen').
    Returns the reconstructed form but keeps the base verb lemma for ranking."""
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


def extract_noun_chunks(sent) -> list[dict]:
    """Extract multi-word noun phrases from dependency parse."""
    chunks = []
    for word in sent.words:
        if word.upos == "NOUN" and word.deprel not in ("flat", "compound", "nmod"):
            deps = [w for w in sent.words
                    if w.head == word.id and w.deprel in ("amod", "flat", "compound", "nmod")]
            if deps:
                phrase_words = sorted(deps + [word], key=lambda w: w.id)
                phrase = " ".join(w.lemma for w in phrase_words)
                chunks.append({
                    "text": phrase,
                    "pos": "NOUN",
                })
    return chunks


def extract(doc, lang: str, freq: dict[str, int], level: str = "A0") -> dict:
    """Run Steps 1-2 on a Stanza doc. Returns the response dict."""
    candidates = []
    proper_nouns = []

    for sent in doc.sentences:
        for word in sent.words:
            if word.upos == "PROPN":
                proper_nouns.append({"text": word.lemma, "pos": "PROPN"})
            elif word.upos in ("NOUN", "VERB", "ADJ", "DET"):
                candidates.append({"text": word.lemma, "pos": word.upos})

        if lang == "nl":
            candidates.extend(extract_separable_verbs(sent))

        candidates.extend(extract_noun_chunks(sent))

    # Deduplicate
    seen = set()
    unique = []
    for item in candidates:
        key = item["text"].lower()
        if key not in seen:
            seen.add(key)
            unique.append(item)

    # Rank and score
    for item in unique:
        rank_key = item.pop("_rank_key", item["text"].lower())
        rank = freq.get(rank_key)
        item["rank"] = rank
        item["weight"] = rank_to_weight(rank, level)
        band = LEVEL_BANDS[level]
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

    return {"language": lang, "lemmas": unique, "proper_nouns": unique_propn}
