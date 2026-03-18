"""Gradio UI for Hugging Face Spaces — wraps the same pipeline as Modal and CLI."""

import json
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

# Pre-load all pipelines and frequency lists at startup
_pipelines = {}
_freqs = {}
for lang in LANGUAGES:
    _pipelines[lang] = create_stanza_pipeline(lang)
    _freqs[lang] = FREQ_LOADERS[lang]()


def analyze(text: str, lang: str, level: str) -> str:
    if not text.strip():
        return json.dumps({"error": "'text' is required"}, indent=2)

    text = trim_text(text)
    doc = _pipelines[lang](text)
    result = extract(doc, lang, _freqs[lang], level=level)
    result["lemmas"] = [l for l in result["lemmas"] if l["weight"] > 0.5][:MAX_LEMMAS]
    return json.dumps(result, indent=2, ensure_ascii=False)


lang_names = {code: LANG_PRESETS[code]["name"] for code in LANGUAGES}

demo = gr.Interface(
    fn=analyze,
    inputs=[
        gr.Textbox(label="Text", lines=4, placeholder="Enter text to analyze..."),
        gr.Dropdown(choices=LANGUAGES, value="nl", label="Language"),
        gr.Dropdown(choices=LEVELS, value="A0", label="CEFR Level"),
    ],
    outputs=gr.JSON(label="Extracted vocabulary"),
    title="vocab-nlp",
    description="Extract vocabulary candidates from short texts for language learners (A0–B1).",
)

if __name__ == "__main__":
    demo.launch()
