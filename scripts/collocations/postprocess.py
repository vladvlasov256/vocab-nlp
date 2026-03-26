"""Post-process collocations: merge inflected duplicates, filter subtitle junk.

Usage:
    uv run python scripts/collocations/postprocess.py --lang sr
    uv run python scripts/collocations/postprocess.py --lang sr --dry-run   # preview only
"""

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[2] / "data"

# Subtitle corpus junk — common artifacts from OpenSubtitles
SUBTITLE_JUNK = {
    "titl", "neprevedeni", "podnaslov", "prevod", "prevesti",
    "titlovan", "sinhronizovan", "titlovi",
}


def load_collocations(lang: str) -> dict:
    path = DATA_DIR / f"collocations_{lang}.json"
    return json.loads(path.read_text())


def save_collocations(lang: str, data: dict, suffix: str = ""):
    path = DATA_DIR / f"collocations_{lang}{suffix}.json"
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    print(f"Saved to {path}")


def merge_inflected(data: dict) -> dict:
    """Merge entries that share the same first lemma but differ in noun inflection.

    Groups by (word1, first 4 chars of word2) and keeps the highest-count form
    as canonical, summing counts across all forms.
    """
    merged = {}
    for pattern, items in data.items():
        groups: dict[str, list[dict]] = defaultdict(list)
        for item in items:
            w1, w2 = item["bigram"].split(maxsplit=1)
            stem2 = w2[:min(4, len(w2))]
            key = f"{w1}|{stem2}"
            groups[key].append(item)

        merged_items = []
        for key, group in groups.items():
            if len(group) == 1:
                merged_items.append(group[0])
                continue

            total_count = sum(it["count"] for it in group)
            canonical = max(group, key=lambda x: x["count"])
            avg_npmi = sum(it["npmi"] * it["count"] for it in group) / total_count

            merged_items.append({
                "bigram": canonical["bigram"],
                "count": total_count,
                "pmi": canonical["pmi"],
                "npmi": round(avg_npmi, 3),
                "score": round(avg_npmi * math.log2(total_count), 2),
                "variants": len(group),
            })

        merged_items.sort(key=lambda x: x["score"], reverse=True)
        merged[pattern] = merged_items

    return merged


def filter_junk(data: dict) -> dict:
    """Remove subtitle-specific artifacts."""
    filtered = {}
    for pattern, items in data.items():
        clean = []
        for item in items:
            words = item["bigram"].split()
            if any(w in SUBTITLE_JUNK for w in words):
                continue
            clean.append(item)
        filtered[pattern] = clean
    return filtered


def print_stats(label: str, data: dict):
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    for pattern, items in data.items():
        print(f"  {pattern}: {len(items)} entries")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--lang", required=True)
    parser.add_argument("--dry-run", action="store_true", help="Preview without saving")
    args = parser.parse_args()

    data = load_collocations(args.lang)
    print_stats("Original", data)

    # Step 1: Filter junk
    data = filter_junk(data)
    print_stats("After junk filter", data)

    # Step 2: Merge inflected duplicates
    data = merge_inflected(data)
    print_stats("After merge", data)

    # Show top merge examples
    print("\nTop merged entries (variants > 1):")
    for pattern, items in data.items():
        multi = [it for it in items if it.get("variants", 1) > 1][:5]
        if multi:
            print(f"\n  {pattern}:")
            for it in multi:
                print(f"    {it['bigram']:30s}  count={it['count']:6d}  npmi={it['npmi']}  variants={it['variants']}")

    if not args.dry_run:
        save_collocations(args.lang, data, suffix="_merged")
    else:
        print("\n(dry run — nothing saved)")


if __name__ == "__main__":
    main()
