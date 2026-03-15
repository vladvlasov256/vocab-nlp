"""Interactive CLI for testing the extract pipeline locally."""

import sys

import stanza

from pipeline import FREQ_LOADERS, LANGUAGES, PROCESSORS, extract, trim_text


def print_result(result):
    print(f"\n  {'LEMMA':<25} {'POS':<6} {'WEIGHT':>6}  {'A2'}")
    print(f"  {'─' * 25} {'─' * 6} {'─' * 6}  {'─' * 3}")
    for item in result["lemmas"]:
        a2 = "✓" if item["is_a2"] else ""
        print(f"  {item['text']:<25} {item['pos']:<6} {item['weight']:>6.2f}  {a2}")
    print()


def print_tokens(doc):
    print(f"\n  {'TOKEN':<15} {'LEMMA':<15} {'POS':<6} {'DEPREL':<15} {'HEAD'}")
    print(f"  {'─' * 15} {'─' * 15} {'─' * 6} {'─' * 15} {'─' * 15}")
    for sent in doc.sentences:
        for word in sent.words:
            head_text = next((w.text for w in sent.words if w.id == word.head), "ROOT")
            print(f"  {word.text:<15} {word.lemma:<15} {word.upos:<6} {word.deprel:<15} {head_text}")
        print()


def main():
    lang = sys.argv[1] if len(sys.argv) > 1 else None
    while lang not in LANGUAGES:
        lang = input(f"Language ({', '.join(LANGUAGES)}): ").strip()

    import logging
    logging.getLogger("stanza").setLevel(logging.WARNING)

    print(f"[1/3] Downloading {lang} model...", flush=True)
    stanza.download(lang, processors=PROCESSORS, verbose=False)
    print(f"[2/3] Loading Stanza pipeline...", flush=True)
    nlp = stanza.Pipeline(lang, processors=PROCESSORS, use_gpu=False, logging_level="WARN")
    print(f"[3/3] Loading frequency list...", flush=True)
    freq = FREQ_LOADERS[lang]()
    print(f"Ready. {len(freq)} frequency entries.\n")

    while True:
        try:
            text = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not text:
            continue

        text = trim_text(text)
        doc = nlp(text)

        print_tokens(doc)

        result = extract(doc, lang, freq)
        print_result(result)


if __name__ == "__main__":
    main()
