#!/usr/bin/env python3
"""Build a lemma override dictionary from Wiktionary data (kaikki.org).

Downloads the Dutch Wiktionary extract and builds a reverse mapping from
inflected forms to lemmas, output as a TSV file for runtime injection into
Stanza's composite_dict.

Usage:
    python scripts/build_lemma_dict.py
"""

import gzip
import json
import sys
import urllib.request
from pathlib import Path

URL = "https://kaikki.org/dictionary/downloads/nl/nl-extract.jsonl.gz"
OUTPUT = Path(__file__).resolve().parent.parent / "data" / "nl_lemmas.tsv"

# Wiktionary POS → Stanza UPOS
POS_MAP = {
    "noun": "NOUN",
    "verb": "VERB",
    "adj": "ADJ",
    "adv": "ADV",
}


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def download(url: str) -> bytes:
    log(f"Downloading {url} ...")
    req = urllib.request.Request(url, headers={"User-Agent": "vocab-nlp/1.0"})
    with urllib.request.urlopen(req) as resp:
        data = resp.read()
    log(f"Downloaded {len(data) / 1024 / 1024:.1f} MB")
    return data


def build_dict(raw_gz: bytes) -> dict[tuple[str, str], str]:
    """Parse JSONL and build {(inflected_form, UPOS): lemma} mapping."""
    overrides: dict[tuple[str, str], str] = {}
    total = 0
    kept = 0

    raw = gzip.decompress(raw_gz)
    for line in raw.decode("utf-8").splitlines():
        if not line.strip():
            continue
        total += 1
        if total % 50_000 == 0:
            log(f"  processed {total} entries, {kept} overrides so far...")

        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue

        if entry.get("lang_code") != "nl":
            continue

        wikt_pos = entry.get("pos", "").lower()
        upos = POS_MAP.get(wikt_pos)
        if not upos:
            continue

        lemma = entry.get("word", "").strip()
        if not lemma:
            continue

        forms = entry.get("forms", [])
        if not forms:
            continue

        for form_entry in forms:
            inflected = form_entry.get("form", "").strip()
            if not inflected or inflected == lemma:
                continue
            # Skip multi-word forms (e.g. "heeft gespeeld")
            if " " in inflected:
                continue

            key = (inflected, upos)
            # First entry wins (most common lemma listed first in Wiktionary)
            if key not in overrides:
                overrides[key] = lemma
                kept += 1

    log(f"Done: {total} entries processed, {kept} overrides extracted.")
    return overrides


def write_tsv(overrides: dict[tuple[str, str], str], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("# Dutch lemma overrides from Wiktionary (CC-BY-SA 3.0) via wiktextract/kaikki.org\n")
        f.write("# Format: inflected_form\\tpos\\tlemma\n")
        for (form, pos), lemma in sorted(overrides.items()):
            f.write(f"{form}\t{pos}\t{lemma}\n")
    log(f"Wrote {len(overrides)} entries to {path}")


def main() -> None:
    raw_gz = download(URL)
    overrides = build_dict(raw_gz)
    write_tsv(overrides, OUTPUT)


if __name__ == "__main__":
    main()
