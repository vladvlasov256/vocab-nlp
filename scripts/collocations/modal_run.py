"""Build dense collocation whitelist on Modal with spaCy + GPU.

Usage:
    # One-time: create volume and upload corpus
    modal volume create vocab-data
    modal volume put vocab-data corpus/nl_opensubs.txt nl_opensubs.txt
    modal volume put vocab-data corpus/en_opensubs.txt en_opensubs.txt

    # Run (default: nl)
    modal run scripts/collocations/modal_run.py
    modal run scripts/collocations/modal_run.py --lang en

    # Download result
    modal volume get vocab-data collocations_nl.json collocations_nl.json
    modal volume get vocab-data collocations_en.json collocations_en.json
"""

import json
import math
import time
from collections import Counter

import modal

SPACY_MODELS = {
    "nl": "nl_core_news_sm",
    "en": "en_core_web_sm",
    "sr": "sr_core_news_sm",
}

app = modal.App("vocab-collocations")

image = (
    modal.Image.from_registry("nvidia/cuda:12.4.0-runtime-ubuntu22.04", add_python="3.12")
    .pip_install("spacy", "cupy-cuda12x")
    .run_commands(*[f"python -m spacy download {m}" for m in SPACY_MODELS.values()])
)

volume = modal.Volume.from_name("vocab-data")

PATTERNS = {("ADJ", "NOUN"), ("VERB", "NOUN"), ("VERB", "ADP")}
MIN_COUNT = 3
TOP_N = 5000


@app.function(
    image=image,
    gpu="T4",
    memory=8192,
    volumes={"/data": volume},
    timeout=86400,
)
def build_collocations(lang: str = "nl", limit: int | None = None):
    import spacy

    model_name = SPACY_MODELS[lang]
    spacy.require_gpu()
    nlp = spacy.load(model_name)

    unigram_counts, bigram_counts, total_tokens = Counter(), Counter(), 0
    batch_size = 500
    batch = []
    done = 0
    t0 = time.time()

    corpus_path = f"/data/{lang}_opensubs.txt"

    with open(corpus_path) as f:
        for line in f:
            batch.append(line.strip())

            if limit and done + len(batch) >= limit:
                batch = batch[:limit - done]

            if len(batch) >= batch_size:
                doc = nlp("\n\n".join(batch))
                words = list(doc)
                for j, w in enumerate(words):
                    if w.pos_ in ("PUNCT", "SYM", "X", "SPACE"):
                        continue
                    lemma = w.lemma_.lower()
                    unigram_counts[lemma] += 1
                    total_tokens += 1
                    if j + 1 < len(words):
                        w2 = words[j + 1]
                        if w2.pos_ in ("PUNCT", "SYM", "X", "SPACE"):
                            continue
                        if (w.pos_, w2.pos_) in PATTERNS:
                            l2 = w2.lemma_.lower()
                            bigram_counts[(lemma, l2, w.pos_, w2.pos_)] += 1
                done += len(batch)
                batch = []
                elapsed = time.time() - t0
                rate = done / elapsed if elapsed > 0 else 0
                if limit and done >= limit:
                    break
                if done % 50_000 == 0:
                    print(f"  {done:,} lines ({rate:,.0f} lines/s, {total_tokens:,} tok)")

    if batch:
        doc = nlp("\n\n".join(batch))
        words = list(doc)
        for j, w in enumerate(words):
            if w.pos_ in ("PUNCT", "SYM", "X", "SPACE"):
                continue
            lemma = w.lemma_.lower()
            unigram_counts[lemma] += 1
            total_tokens += 1
            if j + 1 < len(words):
                w2 = words[j + 1]
                if w2.pos_ in ("PUNCT", "SYM", "X", "SPACE"):
                    continue
                if (w.pos_, w2.pos_) in PATTERNS:
                    l2 = w2.lemma_.lower()
                    bigram_counts[(lemma, l2, w.pos_, w2.pos_)] += 1
        done += len(batch)

    elapsed = time.time() - t0
    print(f"Done: {total_tokens:,} tokens in {elapsed:.1f}s ({total_tokens/elapsed:,.0f} tok/s)")

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
def main(lang: str = "nl"):
    result = build_collocations.remote(lang=lang)
    print(f"\nResult: {result}")
