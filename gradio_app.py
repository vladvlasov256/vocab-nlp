"""Gradio UI for Hugging Face Spaces — wraps the same pipeline as Modal and CLI."""

import logging
import os
import warnings

os.environ["TQDM_DISABLE"] = "1"
warnings.filterwarnings("ignore", category=DeprecationWarning)

import gradio as gr

from pipeline import (
    FREQ_LOADERS,
    LANG_PRESETS,
    LANGUAGES,
    LEVELS,
    MAX_LEMMAS,
    create_stanza_pipeline,
    extract,
    trim_text,
)

logging.getLogger("stanza").setLevel(logging.WARNING)

_pipelines = {}
_freqs = {}
for lang in LANGUAGES:
    _pipelines[lang] = create_stanza_pipeline(lang)
    _freqs[lang] = FREQ_LOADERS[lang]()

_THRESHOLD = 0.5

_DEFAULT_TEXT = "Anna lives in Amsterdam and works at a hospital. She earns 3500 euros per month. Last Wednesday she bought 12 tulips for her grandmother. The flowers were expensive but very beautiful."


def analyze(text: str, lang: str, level: str):
    empty = [], [], [], [], []
    if not text.strip():
        return empty

    text = trim_text(text)
    doc = _pipelines[lang](text)
    result = extract(doc, lang, _freqs[lang], level=level)

    bands = LANG_PRESETS[lang]["levels"][level]["band"]
    all_lemmas = result["candidates"]

    def _band(item):
        rank = item.get("rank")
        if rank is None:
            return "?"
        if rank <= bands["known"]:
            return "known"
        if rank <= bands["target"]:
            return "target"
        return "beyond"

    above = [item for item in all_lemmas if item["weight"] > _THRESHOLD][:MAX_LEMMAS]
    below = [item for item in all_lemmas if item["weight"] <= _THRESHOLD]

    candidates = [[i["text"], i["pos"], i.get("rank") or "—", _band(i)] for i in above]
    filtered = [[i["text"], i["pos"], i.get("rank") or "—", _band(i)] for i in below]
    propn = [[i["text"]] for i in result.get("proper_nouns", [])]
    nums = [[i["text"]] for i in result.get("numbers", [])]
    merged = [
        [" + ".join(i["parts"]), i["merged"], i["rule"]]
        for i in result.get("merged_fragments", [])
    ]

    return candidates, filtered, propn, nums, merged


with gr.Blocks(title="vocab-nlp") as demo:
    gr.Markdown("# vocab-nlp\nExtract vocabulary candidates from short texts for language learners (A0–B1).")

    with gr.Row():
        with gr.Column():
            text_input = gr.Textbox(label="Text", lines=4, value=_DEFAULT_TEXT)
            lang_input = gr.Dropdown(choices=LANGUAGES, value="en", label="Language")
            level_input = gr.Dropdown(choices=LEVELS, value="A1", label="CEFR Level")
            btn = gr.Button("Submit", variant="primary")

        with gr.Column():
            candidates_out = gr.Dataframe(headers=["Candidate", "POS", "Rank", "Band"], label="Candidates")
            filtered_out = gr.Dataframe(headers=["Candidate", "POS", "Rank", "Band"], label="Filtered out")
            with gr.Row():
                propn_out = gr.Dataframe(headers=["Name"], label="Proper Nouns")
                nums_out = gr.Dataframe(headers=["Number"], label="Numbers")
            merged_out = gr.Dataframe(headers=["Parts", "Result", "Rule"], label="Merged Fragments")

    inputs = [text_input, lang_input, level_input]
    outputs = [candidates_out, filtered_out, propn_out, nums_out, merged_out]
    btn.click(analyze, inputs=inputs, outputs=outputs)
    text_input.submit(analyze, inputs=inputs, outputs=outputs)

if __name__ == "__main__":
    demo.launch()
