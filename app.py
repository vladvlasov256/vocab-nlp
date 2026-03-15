import os

import modal
from fastapi import Header, HTTPException

from pipeline import (
    DATA_DIR,
    FREQ_LOADERS,
    LANGUAGES,
    PROCESSORS,
    extract,
    trim_text,
)

app = modal.App("vocab-nlp")

image = modal.Image.debian_slim(python_version="3.13").pip_install(
    "fastapi[standard]",
    "stanza",
).run_commands(
    "python -c \"import stanza; stanza.download('nl', processors='tokenize,pos,lemma,depparse'); stanza.download('sr', processors='tokenize,pos,lemma,depparse')\"",
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
        import stanza

        self.pipelines = {}
        for lang in LANGUAGES:
            stanza.download(lang, processors=PROCESSORS)
            self.pipelines[lang] = stanza.Pipeline(
                lang,
                processors=PROCESSORS,
                use_gpu=False,
            )

        self.freq = {lang: FREQ_LOADERS[lang]() for lang in LANGUAGES}

    @modal.fastapi_endpoint(method="POST")
    def extract(self, request_data: dict, authorization: str = Header()):
        if authorization != f"Bearer {os.environ['API_KEY']}":
            raise HTTPException(status_code=401, detail="Unauthorized")

        text = request_data.get("text", "")
        lang = request_data.get("lang", "")

        if not text:
            return {"error": "'text' is required"}
        if lang not in self.pipelines:
            return {"error": f"Unsupported language '{lang}'. Supported: {list(self.pipelines.keys())}"}

        text = trim_text(text)
        doc = self.pipelines[lang](text)
        return extract(doc, lang, self.freq[lang])
