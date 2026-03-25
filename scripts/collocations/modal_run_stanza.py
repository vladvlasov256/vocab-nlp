"""Build dense collocation whitelist on Modal with Stanza + GPU.

For languages without a spaCy model (e.g. Serbian).
For NL/EN, use modal_run.py (spaCy + GPU) instead.

Usage:
    # One-time: upload corpus
    modal volume put vocab-data corpus/sr_opensubs_1m.txt sr_opensubs_1m.txt
    modal volume put vocab-data corpus/sr_opensubs_50m.txt sr_opensubs_50m.txt

    # Run
    modal run scripts/collocations/modal_run_stanza.py --lang sr --corpus sr_opensubs_1m.txt

    # Download result
    modal volume get vocab-data collocations_sr.json collocations_sr.json
"""

import json
import math
import time
from collections import Counter

import modal

app = modal.App("vocab-collocations-stanza")

image = (
    modal.Image.from_registry("nvidia/cuda:12.4.0-runtime-ubuntu22.04", add_python="3.12")
    .pip_install("stanza")
    .run_commands("python -c \"import stanza; stanza.download('sr')\"")
)

volume = modal.Volume.from_name("vocab-data")

PATTERNS = {("ADJ", "NOUN"), ("VERB", "NOUN"), ("VERB", "ADP")}
SKIP_UPOS = {"PUNCT", "SYM", "X"}
MIN_COUNT = 3
TOP_N = 5000
BATCH_LINES = 50_000


def count_doc(doc, unigram_counts, bigram_counts):
    """Count unigrams and POS-filtered bigrams from a single Stanza doc."""
    tokens = 0
    for sent in doc.sentences:
        words = sent.words
        for i, w in enumerate(words):
            if w.upos in SKIP_UPOS:
                continue
            lemma = (w.lemma.lower() if w.lemma else w.text.lower()).strip(".,;:!?\"'()-")
            if not lemma:
                continue
            unigram_counts[lemma] += 1
            tokens += 1
            if i + 1 < len(words):
                w2 = words[i + 1]
                if w2.upos in SKIP_UPOS:
                    continue
                if (w.upos, w2.upos) in PATTERNS:
                    l2 = (w2.lemma.lower() if w2.lemma else w2.text.lower()).strip(".,;:!?\"'()-")
                    if not l2:
                        continue
                    bigram_counts[(lemma, l2, w.upos, w2.upos)] += 1
    return tokens


@app.function(
    image=image,
    gpu="T4",
    memory=8192,
    volumes={"/data": volume},
    timeout=86400,
)
def build_collocations(lang: str = "sr", corpus: str | None = None, limit: int | None = None):
    import stanza

    nlp = stanza.Pipeline(lang, processors="tokenize,pos,lemma", use_gpu=True, verbose=False,
                           tokenize_pretokenized=True, pos_batch_size=10000, lemma_batch_size=10000)

    unigram_counts, bigram_counts, total_tokens = Counter(), Counter(), 0
    batch = []
    done = 0
    t0 = time.time()

    corpus_file = corpus or f"{lang}_opensubs.txt"
    corpus_path = f"/data/{corpus_file}"

    with open(corpus_path) as f:
        for line in f:
            text = line.strip()
            if not text:
                continue
            batch.append(text)

            if limit and done + len(batch) >= limit:
                batch = batch[:limit - done]

            if len(batch) >= BATCH_LINES:
                doc = nlp("\n".join(batch))
                total_tokens += count_doc(doc, unigram_counts, bigram_counts)
                done += len(batch)
                batch = []
                elapsed = time.time() - t0
                rate = done / elapsed if elapsed > 0 else 0
                if limit and done >= limit:
                    break
                if done % 50_000 == 0:
                    print(f"  {done:,} lines ({rate:,.0f} lines/s, {total_tokens:,} tok)")

    if batch:
        doc = nlp("\n".join(batch))
        total_tokens += count_doc(doc, unigram_counts, bigram_counts)
        done += len(batch)

    elapsed = time.time() - t0
    print(f"Done: {done:,} lines, {total_tokens:,} tokens in {elapsed:.1f}s ({total_tokens/elapsed:,.0f} tok/s)")

    # Compute PMI / NPMI
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
        npmi = pmi / -math.log2(p_xy) if p_xy > 0 else 0
        score = npmi * math.log2(count)
        pattern = f"{p1}+{p2}"
        results.setdefault(pattern, []).append({
            "bigram": f"{l1} {l2}",
            "count": count,
            "pmi": round(pmi, 2),
            "npmi": round(npmi, 3),
            "score": round(score, 2),
        })

    for p in results:
        results[p].sort(key=lambda x: x["score"], reverse=True)
        results[p] = results[p][:TOP_N]

    # Summary
    for p, items in results.items():
        print(f"\n{p}: {len(items)} bigrams")
        for it in items[:10]:
            print(f"  {it['bigram']:30s}  count={it['count']:6d}  NPMI={it['npmi']:+.3f}  score={it['score']:+.2f}")

    out_path = f"/data/collocations_{lang}.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    volume.commit()
    print(f"\nSaved to {out_path}")

    return {"total_tokens": total_tokens, "patterns": {p: len(v) for p, v in results.items()}}


@app.local_entrypoint()
def main(lang: str = "sr", corpus: str | None = None, limit: int | None = None):
    result = build_collocations.remote(lang=lang, corpus=corpus, limit=limit)
    print(f"\nResult: {result}")
