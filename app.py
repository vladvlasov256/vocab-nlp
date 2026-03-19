import os

import modal

from pipeline import (
    FREQ_LOADERS,
    LANG_PRESETS,
    MAX_LEMMAS,
    PROCESSORS,
    create_stanza_pipeline,
    extract,
    trim_text,
)

app = modal.App("vocab-nlp")

_pip_image = modal.Image.debian_slim(python_version="3.13").pip_install(
    "fastapi[standard]",
    "stanza",
)

_cls_config = dict(
    secrets=[modal.Secret.from_name("vocab-nlp-api-key")],
    enable_memory_snapshot=True,
    min_containers=0,
    max_containers=1,
    timeout=120,
    memory=1024,
    cpu=1,
)


def _make_image(lang: str) -> modal.Image:
    return _pip_image.run_commands(
        f"python -c \"import stanza; stanza.download('{lang}', processors='{PROCESSORS}')\"",
    ).add_local_dir("data", remote_path="/root/data"
    ).add_local_python_source("pipeline")


def _make_fastapi_app(cls_instance):
    """Build a single-route FastAPI app at runtime (inside the container)."""
    from fastapi import FastAPI, Header, HTTPException

    web_app = FastAPI()

    @web_app.post("/")
    def endpoint(request_data: dict, authorization: str = Header()):
        if authorization != f"Bearer {os.environ['API_KEY']}":
            raise HTTPException(status_code=401, detail="Unauthorized")

        text = request_data.get("text", "")
        level = request_data.get("level", "A0")

        if not text:
            return {"error": "'text' is required"}
        lang = cls_instance._lang
        supported_levels = list(LANG_PRESETS[lang]["levels"].keys())
        if level not in supported_levels:
            return {"error": f"Unsupported level '{level}'. Supported: {supported_levels}"}

        text = trim_text(text)
        doc = cls_instance.pipeline(text)
        result = extract(doc, lang, cls_instance.freq, level=level)
        result["items"] = [c for c in result["items"] if c["score"] > 0.5][:MAX_LEMMAS]
        return result

    return web_app


@app.cls(image=_make_image("nl"), **_cls_config)
class Nl:
    _lang = "nl"

    @modal.enter(snap=True)
    def load(self):
        self.pipeline = create_stanza_pipeline(self._lang)
        self.freq = FREQ_LOADERS[self._lang]()

    @modal.asgi_app()
    def extract(self):
        return _make_fastapi_app(self)


@app.cls(image=_make_image("en"), **_cls_config)
class En:
    _lang = "en"

    @modal.enter(snap=True)
    def load(self):
        self.pipeline = create_stanza_pipeline(self._lang)
        self.freq = FREQ_LOADERS[self._lang]()

    @modal.asgi_app()
    def extract(self):
        return _make_fastapi_app(self)


@app.cls(image=_make_image("sr"), **_cls_config)
class Sr:
    _lang = "sr"

    @modal.enter(snap=True)
    def load(self):
        self.pipeline = create_stanza_pipeline(self._lang)
        self.freq = FREQ_LOADERS[self._lang]()

    @modal.asgi_app()
    def extract(self):
        return _make_fastapi_app(self)
