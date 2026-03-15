import os
import re

import modal
from fastapi import Header, HTTPException

MAX_TEXT_BYTES = 4096


def trim_text(text: str) -> str:
    """Step 0: Collapse whitespace and cap length."""
    text = re.sub(r"\s+", " ", text).strip()
    return text[:MAX_TEXT_BYTES]

app = modal.App("vocab-nlp")

image = modal.Image.debian_slim(python_version="3.13").pip_install(
    "fastapi[standard]",
    "stanza",
)


pipelines = {}


def _get_pipeline(lang: str):
    if lang not in pipelines:
        import stanza

        stanza.download(lang, processors="tokenize,pos,lemma,depparse,ner")
        pipelines[lang] = stanza.Pipeline(
            lang,
            processors="tokenize,pos,lemma,depparse,ner",
            use_gpu=False,
        )
    return pipelines[lang]


@app.function(
    image=image,
    secrets=[modal.Secret.from_name("vocab-nlp-api-key")],
    min_containers=0,
    max_containers=1,
    timeout=120,
    memory=2048,
    cpu=1,
)
@modal.fastapi_endpoint(method="POST")
def extract(request_data: dict, authorization: str = Header()):
    """Extract vocabulary candidates from text."""
    if authorization != f"Bearer {os.environ['API_KEY']}":
        raise HTTPException(status_code=401, detail="Unauthorized")

    text = request_data.get("text", "")
    lang = request_data.get("lang", "")

    if not text:
        return {"error": "'text' is required"}
    if lang not in ("nl", "sr"):
        return {"error": f"Unsupported language '{lang}'. Supported: ['nl', 'sr']"}

    # Step 0: Trim text
    text = trim_text(text)

    doc = _get_pipeline(lang)(text)

    lemmas = []
    for sent in doc.sentences:
        for word in sent.words:
            if word.upos in ("NOUN", "VERB", "ADJ", "PROPN"):
                lemmas.append({
                    "text": word.lemma,
                    "pos": word.upos,
                    "weight": 0.5,
                    "is_a2": False,
                })

    # Deduplicate by lemma text, keep first occurrence
    seen = set()
    unique = []
    for item in lemmas:
        key = item["text"].lower()
        if key not in seen:
            seen.add(key)
            unique.append(item)

    return {
        "language": lang,
        "lemmas": unique,
    }
