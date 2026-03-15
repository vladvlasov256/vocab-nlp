"""Core NLP pipeline — shared by app.py (Modal) and cli.py (local)."""

import csv
import re
from pathlib import Path

MAX_TEXT_BYTES = 4096
MAX_LEMMAS = 15
A2_RANK_CUTOFF = 2000  # top-2000 = A1-A2
B1_RANK_CUTOFF = 5000  # 2000-5000 = A2-B1

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


def rank_to_weight(rank: int | None) -> float:
    """Convert frequency rank to 0-1 weight. Lower rank = higher weight."""
    if rank is None:
        return 0.3
    if rank <= A2_RANK_CUTOFF:
        return 1.0
    if rank <= B1_RANK_CUTOFF:
        return 0.7 - 0.2 * (rank - A2_RANK_CUTOFF) / (B1_RANK_CUTOFF - A2_RANK_CUTOFF)
    return 0.3


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


def extract(doc, lang: str, freq: dict[str, int], threshold: float = 0.5) -> dict:
    """Run Steps 1-2 on a Stanza doc. Returns the response dict."""
    candidates = []

    for sent in doc.sentences:
        for word in sent.words:
            if word.upos in ("NOUN", "VERB", "ADJ", "PROPN", "DET"):
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
        item["weight"] = rank_to_weight(rank)
        item["is_a2"] = rank is not None and rank <= A2_RANK_CUTOFF

    # Filter and sort
    unique = [item for item in unique if item["weight"] > threshold]
    unique.sort(key=lambda x: x["weight"], reverse=True)

    return {"language": lang, "lemmas": unique[:MAX_LEMMAS]}
