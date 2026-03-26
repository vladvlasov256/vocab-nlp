"""Benchmark: compare our pipeline vs LLM baseline using a judge LLM."""

import argparse
import json
import logging
import os
import sys
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from statistics import mean, stdev

os.environ["TQDM_DISABLE"] = "1"
warnings.filterwarnings("ignore", category=DeprecationWarning)

from dotenv import load_dotenv
from openai import OpenAI
from rich.console import Console
from rich.table import Table

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline import FREQ_LOADERS, LANG_PRESETS, create_stanza_pipeline, extract, trim_text

BENCH_DIR = Path(__file__).resolve().parent
TEXTS_DIR = BENCH_DIR / "texts"
BASELINE_DIR = BENCH_DIR / "baseline"

JUDGE_MODEL = "gpt-5"

JUDGE_PROMPT = """\
You are evaluating vocabulary lists extracted from a short {language} text for a {level} language learner.

## Text
{text}

## List A
{list_a}

## List B
{list_b}

The learner is reading this text as part of a lesson. The goal is to help them understand and learn from it.

Scoring rules:
- Multi-word items count as covering each component word. Do not penalize a list for missing a word that appears as part of a multi-word item.
- Minor spelling imperfections are acceptable if the word is clearly recognizable.
- Accept dialect variants as correct. Accept standard lemmatization even when the lemma form differs from the surface form in the text.

Score each list 1-5 on:
- **Relevance**: Does the list help this {level} learner understand this specific text?
- **Coverage**: Does the list capture the important vocabulary from the text?
- **Noise**: Are there false picks — trivial words, proper nouns, or unrecognizable words?
{lang_hints}
Respond with ONLY valid JSON, no markdown:
{{"score_a": <int 1-5>, "score_b": <int 1-5>, "reasoning": "<1-2 sentences>"}}
"""

LANG_HINTS = {
    "nl": "Dutch and German have separable verbs where a particle splits from the verb in a sentence (e.g. \"Hij belt zijn moeder op\"). Treat the reconstructed infinitive form (\"opbellen\") as equivalent to the split form (\"bellen op\" / \"op bellen\"). Similarly, compound words like \"meespelen\" = \"spelen mee\", \"terugbrengen\" = \"brengen terug\".",
    "sr": "",
    "en": "",
}


def discover_texts(lang: str | None = None, level: str | None = None, text_name: str | None = None) -> list[dict]:
    """Find all text/baseline pairs matching filters."""
    texts = []
    for txt_path in sorted(TEXTS_DIR.glob("*.txt")):
        name = txt_path.stem  # e.g. nl_a0_01
        parts = name.split("_")
        if len(parts) != 3:
            continue
        t_lang, t_level, t_num = parts[0], parts[1].upper(), parts[2]

        if lang and t_lang != lang:
            continue
        if level and t_level != level:
            continue
        if text_name and name not in text_name:
            continue

        baseline_path = BASELINE_DIR / f"{name}.json"
        if not baseline_path.exists():
            continue

        texts.append({
            "name": name,
            "lang": t_lang,
            "level": t_level,
            "text_path": txt_path,
            "baseline_path": baseline_path,
        })
    return texts


def run_pipeline(text: str, lang: str, level: str, nlp, freq) -> list[str]:
    """Run our extraction pipeline, return lemma list."""
    trimmed = trim_text(text)
    doc = nlp(trimmed)
    result = extract(doc, lang, freq, level=level, join_separable=True)
    # Match LLM baseline counts per level: A0=4, A1=8, A2=12
    max_items = {"A0": 4, "A1": 8, "A2": 12, "B1": 15}
    lemmas = [item["text"] for item in result["items"] if item["score"] > 0.5][:max_items.get(level, 15)]
    return lemmas


def judge(client: OpenAI, text: str, lang: str, level: str, pipeline_lemmas: list[str], baseline_lemmas: list[str]) -> dict:
    """Ask judge LLM to score both lists."""
    language = LANG_PRESETS[lang]["name"]
    lang_hints = LANG_HINTS.get(lang, "")
    if lang_hints:
        lang_hints = "\n" + lang_hints
    prompt = JUDGE_PROMPT.format(
        language=language,
        level=level,
        text=text,
        list_a="\n".join(f"{i+1}. {w}" for i, w in enumerate(pipeline_lemmas)),
        list_b="\n".join(f"{i+1}. {w}" for i, w in enumerate(baseline_lemmas)),
        lang_hints=lang_hints,
    )
    logging.getLogger("bench").info(f"\n{'='*60}\nJUDGE PROMPT for {level} text:\n{'='*60}\n{prompt}\n{'='*60}")
    response = client.chat.completions.create(
        model=JUDGE_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=1,  # gpt-5 only supports temperature=1
    )
    content = response.choices[0].message.content.strip()
    return json.loads(content)


def main():
    load_dotenv()

    parser = argparse.ArgumentParser(description="Run vocab-nlp benchmark")
    parser.add_argument("--level", type=str, help="Filter by level (A0, A1, A2)")
    parser.add_argument("--text", type=str, help="Filter by text name (e.g. en_a2_03)")
    parser.add_argument("--lang", type=str, help="Filter by language (nl, sr)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Print judge prompts")
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger("bench").setLevel(logging.INFO)
        logging.getLogger("bench").addHandler(logging.StreamHandler())

    level_filter = args.level.upper() if args.level else None
    lang_filter = args.lang if args.lang else None

    text_filter = args.text.split(",") if args.text else None
    texts = discover_texts(lang=lang_filter, level=level_filter, text_name=text_filter)
    if not texts:
        print("No matching texts found.")
        return

    console = Console()
    console.print(f"[dim]Found {len(texts)} texts to evaluate[/dim]")

    # Load pipeline resources per language
    pipelines = {}
    freq_data = {}

    logging.getLogger("stanza").setLevel(logging.WARNING)

    for entry in texts:
        lang = entry["lang"]
        if lang not in pipelines:
            console.print(f"[dim]Loading {lang} pipeline...[/dim]")
            pipelines[lang] = create_stanza_pipeline(lang)
            freq_data[lang] = FREQ_LOADERS[lang]()

    # Judge LLM
    client = OpenAI()
    console.print(f"[dim]Judge model: {JUDGE_MODEL}[/dim]\n")

    # Run NLP pipeline (fast, sequential — Stanza is not thread-safe)
    prepared = []
    for entry in texts:
        text = entry["text_path"].read_text().strip()
        baseline = json.loads(entry["baseline_path"].read_text())
        baseline_lemmas = baseline["lemmas"]

        nlp = pipelines[entry["lang"]]
        freq = freq_data[entry["lang"]]

        pipeline_lemmas = run_pipeline(text, entry["lang"], entry["level"], nlp, freq)
        prepared.append({
            "name": entry["name"],
            "lang": entry["lang"],
            "level": entry["level"],
            "text": text,
            "pipeline_lemmas": pipeline_lemmas,
            "baseline_lemmas": baseline_lemmas,
        })

    # Judge in parallel (API-bound)
    console.print(f"[dim]Judging {len(prepared)} texts in parallel...[/dim]")

    def judge_entry(p):
        scores = judge(client, p["text"], p["lang"], p["level"], p["pipeline_lemmas"], p["baseline_lemmas"])
        return {**p, **scores}

    results = []
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {pool.submit(judge_entry, p): p["name"] for p in prepared}
        for future in as_completed(futures):
            name = futures[future]
            r = future.result()
            console.print(f"[dim]  {name} done[/dim]")
            results.append({
                "name": r["name"],
                "level": r["level"],
                "pipeline_lemmas": r["pipeline_lemmas"],
                "baseline_lemmas": r["baseline_lemmas"],
                "score_a": r["score_a"],
                "score_b": r["score_b"],
                "delta": r["score_a"] - r["score_b"],
                "reasoning": r["reasoning"],
            })

    results.sort(key=lambda r: r["name"])

    # Results table
    table = Table(title="Benchmark Results")
    table.add_column("Text")
    table.add_column("Level")
    table.add_column("Pipeline", justify="right")
    table.add_column("LLM", justify="right")
    table.add_column("Delta", justify="right")
    table.add_column("Reasoning")

    for r in results:
        d = r["delta"]
        delta_style = "green" if d > 0 else "red" if d < 0 else "dim"
        table.add_row(
            r["name"],
            r["level"],
            str(r["score_a"]),
            str(r["score_b"]),
            f"[{delta_style}]{d:+d}[/{delta_style}]",
            r["reasoning"],
        )

    console.print(table)

    # Aggregates per level
    console.print()
    levels_seen = sorted(set(r["level"] for r in results))
    agg_table = Table(title="Mean Delta per Level")
    agg_table.add_column("Level")
    agg_table.add_column("Pipeline avg", justify="right")
    agg_table.add_column("LLM avg", justify="right")
    agg_table.add_column("Delta", justify="right")
    agg_table.add_column("n", justify="right")

    all_deltas = [r["delta"] for r in results]

    for level in levels_seen:
        level_results = [r for r in results if r["level"] == level]
        avg_a = mean(r["score_a"] for r in level_results)
        avg_b = mean(r["score_b"] for r in level_results)
        delta = mean(r["delta"] for r in level_results)
        delta_style = "green" if delta > 0 else "red" if delta < 0 else "dim"
        agg_table.add_row(
            level,
            f"{avg_a:.1f}",
            f"{avg_b:.1f}",
            f"[{delta_style}]{delta:+.2f}[/{delta_style}]",
            str(len(level_results)),
        )

    # Overall
    avg_a = mean(r["score_a"] for r in results)
    avg_b = mean(r["score_b"] for r in results)
    delta = mean(all_deltas)
    delta_style = "green" if delta > 0 else "red" if delta < 0 else "dim"
    agg_table.add_section()
    agg_table.add_row(
        "[bold]Overall[/bold]",
        f"[bold]{avg_a:.1f}[/bold]",
        f"[bold]{avg_b:.1f}[/bold]",
        f"[bold][{delta_style}]{delta:+.2f}[/{delta_style}][/bold]",
        f"[bold]{len(results)}[/bold]",
    )

    console.print(agg_table)

    # Cohen's d
    if len(all_deltas) > 1:
        d = mean(all_deltas) / stdev(all_deltas) if stdev(all_deltas) > 0 else float("inf")
        console.print(f"\n[bold]Cohen's d: {d:.2f}[/bold]")
    else:
        console.print("\n[dim]Cohen's d: not enough data[/dim]")


if __name__ == "__main__":
    main()
