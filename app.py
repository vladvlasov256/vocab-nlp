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
).run_commands(
    "python -c \"import stanza; stanza.download('nl'); stanza.download('sr')\"",
)


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
        for lang in ["nl", "sr"]:
            stanza.download(lang, processors="tokenize,pos,lemma,depparse,ner")
            self.pipelines[lang] = stanza.Pipeline(
                lang,
                processors="tokenize,pos,lemma,depparse,ner",
                use_gpu=False,
            )

    @modal.fastapi_endpoint(method="POST")
    def extract(self, request_data: dict, authorization: str = Header()):
        """Extract vocabulary candidates from text."""
        if authorization != f"Bearer {os.environ['API_KEY']}":
            raise HTTPException(status_code=401, detail="Unauthorized")

        text = request_data.get("text", "")
        lang = request_data.get("lang", "")

        if not text:
            return {"error": "'text' is required"}
        if lang not in self.pipelines:
            return {"error": f"Unsupported language '{lang}'. Supported: {list(self.pipelines.keys())}"}

        # Step 0: Trim text
        text = trim_text(text)

        doc = self.pipelines[lang](text)

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
