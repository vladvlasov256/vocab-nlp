import csv
import os
import re
from pathlib import Path

import modal
from fastapi import Header, HTTPException

MAX_TEXT_BYTES = 4096
MAX_LEMMAS = 15
A2_RANK_CUTOFF = 2000  # top-2000 = A1-A2
B1_RANK_CUTOFF = 5000  # 2000-5000 = A2-B1

DATA_DIR = Path(__file__).parent / "data"


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
                "_rank_key": verb.lemma.lower(),  # rank by base verb
            })
    return results


def extract_noun_chunks(sent) -> list[dict]:
    """Extract multi-word noun phrases from dependency parse."""
    chunks = []
    for word in sent.words:
        if word.upos == "NOUN" and word.deprel not in ("flat", "compound", "nmod"):
            # Collect dependents that form a noun chunk
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


app = modal.App("vocab-nlp")

image = modal.Image.debian_slim(python_version="3.13").pip_install(
    "fastapi[standard]",
    "stanza",
).run_commands(
    "python -c \"import stanza; stanza.download('nl', processors='tokenize,pos,lemma,depparse'); stanza.download('sr', processors='tokenize,pos,lemma,depparse')\"",
).add_local_dir(str(DATA_DIR), remote_path="/root/data")


@app.cls(
    image=image,
    secrets=[modal.Secret.from_name("vocab-nlp-api-key")],
    enable_memory_snapshot=True,
    min_containers=0,
    max_containers=1,
    timeout=120,
    memory=2048,
    cpu=1,
)
class VocabNlp:
    @modal.enter(snap=True)
    def load_models(self):
        import stanza

        self.pipelines = {}
        processors = "tokenize,pos,lemma,depparse"
        for lang in ["nl", "sr"]:
            stanza.download(lang, processors=processors)
            self.pipelines[lang] = stanza.Pipeline(
                lang,
                processors=processors,
                use_gpu=False,
            )

        # Load frequency lists
        self.freq = {
            "nl": load_freq_nl(),
            "sr": load_freq_sr(),
        }

    @modal.fastapi_endpoint(method="POST")
    def extract(self, request_data: dict, authorization: str = Header()):
        """Extract vocabulary candidates from text."""
        if authorization != f"Bearer {os.environ['API_KEY']}":
            raise HTTPException(status_code=401, detail="Unauthorized")

        text = request_data.get("text", "")
        lang = request_data.get("lang", "")

        if not text:
            return {"error": "'text' is required"}
        if lang not in self.pipelines:
            return {"error": f"Unsupported language '{lang}'. Supported: {list(self.pipelines.keys())}"}

        # Step 0: Trim text
        text = trim_text(text)

        # Step 1: Stanza NLP
        doc = self.pipelines[lang](text)
        freq = self.freq[lang]

        candidates = []

        for sent in doc.sentences:
            # Single-word lemmas
            for word in sent.words:
                if word.upos in ("NOUN", "VERB", "ADJ", "PROPN"):
                    candidates.append({
                        "text": word.lemma,
                        "pos": word.upos,
                    })

            # Step 2a: Dutch separable verbs
            if lang == "nl":
                candidates.extend(extract_separable_verbs(sent))

            # Step 2a: Noun chunks
            candidates.extend(extract_noun_chunks(sent))

        # Deduplicate by lemma text
        seen = set()
        unique = []
        for item in candidates:
            key = item["text"].lower()
            if key not in seen:
                seen.add(key)
                unique.append(item)

        # Step 2b: Rank and score
        for item in unique:
            rank_key = item.pop("_rank_key", item["text"].lower())
            rank = freq.get(rank_key)
            item["weight"] = rank_to_weight(rank)
            item["is_a2"] = rank is not None and rank <= A2_RANK_CUTOFF

        # Filter and sort: threshold > 0.5, top N by weight
        unique = [item for item in unique if item["weight"] > 0.5]
        unique.sort(key=lambda x: x["weight"], reverse=True)

        return {
            "language": lang,
            "lemmas": unique[:MAX_LEMMAS],
        }
