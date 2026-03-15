"""Interactive CLI for testing the extract pipeline locally."""

import logging
import sys

from rich.console import Console
from rich.prompt import Prompt, FloatPrompt
from rich.table import Table

import stanza

from pipeline import FREQ_LOADERS, LANGUAGES, PROCESSORS, extract, trim_text

console = Console()


def show_tokens(doc):
    table = Table(title="Tokens", show_lines=False, pad_edge=False)
    table.add_column("Token", style="cyan")
    table.add_column("Lemma", style="green")
    table.add_column("POS", style="yellow")
    table.add_column("Deprel", style="magenta")
    table.add_column("Head", style="dim")

    for sent in doc.sentences:
        for word in sent.words:
            head_text = next((w.text for w in sent.words if w.id == word.head), "ROOT")
            table.add_row(word.text, word.lemma, word.upos, word.deprel, head_text)
        table.add_section()

    console.print(table)


def show_result(result):
    table = Table(title="Vocabulary Candidates", show_lines=False, pad_edge=False)
    table.add_column("Lemma", style="bold")
    table.add_column("POS", style="yellow")
    table.add_column("Weight", justify="right", style="cyan")
    table.add_column("A2", justify="center")

    for item in result["lemmas"]:
        a2 = "[green]✓[/green]" if item["is_a2"] else ""
        w = item["weight"]
        weight_style = "green" if w >= 0.9 else "yellow" if w >= 0.6 else "red"
        table.add_row(
            item["text"],
            item["pos"],
            f"[{weight_style}]{w:.2f}[/{weight_style}]",
            a2,
        )

    console.print(table)


def main():
    lang = sys.argv[1] if len(sys.argv) > 1 else None
    if lang not in LANGUAGES:
        lang = Prompt.ask("Language", choices=LANGUAGES)

    threshold = FloatPrompt.ask("Weight threshold", default=0.5)

    logging.getLogger("stanza").setLevel(logging.WARNING)

    with console.status("[bold]Downloading model..."):
        stanza.download(lang, processors=PROCESSORS, verbose=False)

    with console.status("[bold]Loading Stanza pipeline..."):
        nlp = stanza.Pipeline(lang, processors=PROCESSORS, use_gpu=False, logging_level="WARN")

    with console.status("[bold]Loading frequency list..."):
        freq = FREQ_LOADERS[lang]()

    console.print(f"[green]Ready.[/green] {len(freq)} frequency entries.\n")

    while True:
        try:
            text = Prompt.ask("[bold]Text[/bold]")
        except (EOFError, KeyboardInterrupt):
            console.print("\nBye!")
            break

        if not text.strip():
            continue

        text = trim_text(text)
        doc = nlp(text)

        show_tokens(doc)
        console.print()

        result = extract(doc, lang, freq, threshold=threshold)
        show_result(result)
        console.print()


if __name__ == "__main__":
    main()
