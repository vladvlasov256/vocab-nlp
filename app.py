import os

import modal
from fastapi import Header, HTTPException

from pipeline import (
    DATA_DIR,
    FREQ_LOADERS,
    LANG_PRESETS,
    LANGUAGES,
    MAX_LEMMAS,
    create_stanza_pipeline,
    extract,
    trim_text,
)

app = modal.App("vocab-nlp")

image = modal.Image.debian_slim(python_version="3.13").pip_install(
    "fastapi[standard]",
    "stanza",
).run_commands(
    "python -c \"import stanza; stanza.download('nl', processors='tokenize,pos,lemma,depparse'); stanza.download('sr', processors='tokenize,pos,lemma,depparse'); stanza.download('en', processors='tokenize,pos,lemma,depparse')\"",
).add_local_dir(str(DATA_DIR), remote_path="/root/data"
).add_local_python_source("pipeline")


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
        self.pipelines = {}
        for lang in LANGUAGES:
            self.pipelines[lang] = create_stanza_pipeline(lang)

        self.freq = {lang: FREQ_LOADERS[lang]() for lang in LANGUAGES}

    @modal.fastapi_endpoint(method="POST")
    def extract(self, request_data: dict, authorization: str = Header()):
        if authorization != f"Bearer {os.environ['API_KEY']}":
            raise HTTPException(status_code=401, detail="Unauthorized")

        text = request_data.get("text", "")
        lang = request_data.get("lang", "")
        level = request_data.get("level", "A0")

        if not text:
            return {"error": "'text' is required"}
        if lang not in self.pipelines:
            return {"error": f"Unsupported language '{lang}'. Supported: {list(self.pipelines.keys())}"}
        supported_levels = list(LANG_PRESETS[lang]["levels"].keys())
        if level not in supported_levels:
            return {"error": f"Unsupported level '{level}'. Supported: {supported_levels}"}

        text = trim_text(text)
        doc = self.pipelines[lang](text)
        result = extract(doc, lang, self.freq[lang], level=level)
        result["lemmas"] = [l for l in result["lemmas"] if l["weight"] > 0.5][:MAX_LEMMAS]
        return result
