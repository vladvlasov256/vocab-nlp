import modal

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
    min_containers=0,
    max_containers=1,
    timeout=120,
    memory=2048,
    cpu=1,
)
@modal.fastapi_endpoint(method="POST")
def extract(request_data: dict):
    """Extract vocabulary candidates from text."""
    text = request_data.get("text", "")
    lang = request_data.get("lang", "")

    if not text:
        return {"error": "'text' is required"}
    if lang not in ("nl", "sr"):
        return {"error": f"Unsupported language '{lang}'. Supported: ['nl', 'sr']"}

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
