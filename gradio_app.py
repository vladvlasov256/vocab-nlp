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


def analyze(text: str, lang: str, level: str):
    if not text.strip():
        return [], [], []

    text = trim_text(text)
    doc = _pipelines[lang](text)
    result = extract(doc, lang, _freqs[lang], level=level)
    result["lemmas"] = [l for l in result["lemmas"] if l["weight"] > 0.5][:MAX_LEMMAS]

    candidates = [
        [item["text"], item["pos"], item.get("rank") or "—", "target" if item["in_target"] else "beyond"]
        for item in result["lemmas"]
    ]
    propn = [[item["text"]] for item in result.get("proper_nouns", [])]
    nums = [[item["text"]] for item in result.get("numbers", [])]

    return candidates, propn, nums


with gr.Blocks(title="vocab-nlp") as demo:
    gr.Markdown("# vocab-nlp\nExtract vocabulary candidates from short texts for language learners (A0–B1).")

    with gr.Row():
        with gr.Column():
            text_input = gr.Textbox(label="Text", lines=4, placeholder="Enter text to analyze...")
            lang_input = gr.Dropdown(choices=LANGUAGES, value="nl", label="Language")
            level_input = gr.Dropdown(choices=LEVELS, value="A0", label="CEFR Level")
            btn = gr.Button("Submit", variant="primary")

        with gr.Column():
            candidates_out = gr.Dataframe(
                headers=["Lemma", "POS", "Rank", "Band"],
                label="Candidates",
            )
            with gr.Row():
                propn_out = gr.Dataframe(headers=["Name"], label="Proper Nouns")
                nums_out = gr.Dataframe(headers=["Number"], label="Numbers")

    btn.click(analyze, inputs=[text_input, lang_input, level_input], outputs=[candidates_out, propn_out, nums_out])
    text_input.submit(analyze, inputs=[text_input, lang_input, level_input], outputs=[candidates_out, propn_out, nums_out])

if __name__ == "__main__":
    demo.launch()
