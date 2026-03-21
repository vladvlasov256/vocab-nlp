"""Extract POS-tagged bigrams from a text corpus and compute PMI scores.

Usage:
    python scripts/build_collocations.py /tmp/nl_subs_sample.txt --lang nl --limit 1000
    python scripts/build_collocations.py /tmp/nl_subs_sample.txt --lang nl  # full file
"""

import argparse
import json
import math
import sys
import time
from collections import Counter
from pathlib import Path

import stanza

# POS bigram patterns we care about
PATTERNS = {
    ("ADJ", "NOUN"),
    ("VERB", "NOUN"),
    ("VERB", "ADP"),
}

# Minimum counts to consider a bigram
MIN_COUNT = 3
# Top N bigrams per pattern to keep
TOP_N = 5000


def process_corpus(path: str, lang: str, limit: int | None = None) -> dict:
    nlp = stanza.Pipeline(lang, processors="tokenize,pos,lemma", use_gpu=False, logging_level="WARN")

    unigram_counts: Counter = Counter()
    bigram_counts: Counter = Counter()
    total_tokens = 0

    lines = Path(path).read_text().strip().splitlines()
    if limit:
        lines = lines[:limit]

    batch_size = 50
    t0 = time.time()

    for i in range(0, len(lines), batch_size):
        batch = "\n\n".join(lines[i : i + batch_size])
        doc = nlp(batch)

        for sent in doc.sentences:
            words = sent.words
            for j, w in enumerate(words):
                if w.upos in ("PUNCT", "SYM", "X"):
                    continue
                lemma = w.lemma.lower() if w.lemma else w.text.lower()
                unigram_counts[lemma] += 1
                total_tokens += 1

                if j + 1 < len(words):
                    w2 = words[j + 1]
                    if w2.upos in ("PUNCT", "SYM", "X"):
                        continue
                    pair = (w.upos, w2.upos)
                    if pair in PATTERNS:
                        l1 = lemma
                        l2 = w2.lemma.lower() if w2.lemma else w2.text.lower()
                        bigram_counts[(l1, l2, pair[0], pair[1])] += 1

        done = min(i + batch_size, len(lines))
        elapsed = time.time() - t0
        rate = done / elapsed if elapsed > 0 else 0
        print(f"\r  {done}/{len(lines)} lines ({rate:.0f} lines/s, {total_tokens} tokens)", end="", flush=True)

    print()
    elapsed = time.time() - t0
    print(f"Processed {total_tokens} tokens in {elapsed:.1f}s ({total_tokens/elapsed:.0f} tok/s)")

    # Compute PMI and NPMI
    results = {}
    for (l1, l2, p1, p2), count in bigram_counts.items():
        if count < MIN_COUNT:
            continue
        p_xy = count / total_tokens
        p_x = unigram_counts[l1] / total_tokens
        p_y = unigram_counts[l2] / total_tokens
        if p_x == 0 or p_y == 0:
            continue
        pmi = math.log2(p_xy / (p_x * p_y))
        # NPMI normalizes to [-1, +1]: PMI / -log2(P(x,y))
        npmi = pmi / -math.log2(p_xy) if p_xy > 0 else 0
        # Weighted score: balances association strength with frequency
        score = npmi * math.log2(count)
        pattern = f"{p1}+{p2}"
        if pattern not in results:
            results[pattern] = []
        results[pattern].append({
            "bigram": f"{l1} {l2}",
            "count": count,
            "pmi": round(pmi, 2),
            "npmi": round(npmi, 3),
            "score": round(score, 2),
        })

    # Sort by weighted score descending, keep top N
    for pattern in results:
        results[pattern].sort(key=lambda x: x["score"], reverse=True)
        results[pattern] = results[pattern][:TOP_N]

    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("corpus", help="Path to text file (one sentence per line)")
    parser.add_argument("--lang", default="nl")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of lines to process")
    parser.add_argument("--output", default=None, help="Output JSON path")
    args = parser.parse_args()

    print(f"Processing {args.corpus} (lang={args.lang}, limit={args.limit})")
    results = process_corpus(args.corpus, args.lang, args.limit)

    for pattern, items in results.items():
        print(f"\n{pattern}: {len(items)} bigrams")
        for item in items[:20]:
            print(f"  {item['bigram']:30s}  count={item['count']:4d}  NPMI={item['npmi']:+.3f}  score={item['score']:+.2f}")

    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(results, indent=2, ensure_ascii=False))
        print(f"\nSaved to {out}")


if __name__ == "__main__":
    main()
