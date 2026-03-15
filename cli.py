"""Interactive TUI for testing the extract pipeline locally."""

import logging
import os
import sys
import warnings

os.environ["TQDM_DISABLE"] = "1"
warnings.filterwarnings("ignore", category=DeprecationWarning)

# Patch tqdm to avoid multiprocessing lock issues inside Textual's event loop
import tqdm
import tqdm.std
tqdm.std.TqdmDefaultWriteLock.create_mp_lock = classmethod(lambda cls: setattr(cls, 'mp_lock', None))

from rich.columns import Columns
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.widgets import Footer, Header, Input, RichLog

import stanza

from pipeline import FREQ_LOADERS, LANGUAGES, PROCESSORS, extract, trim_text


class VocabApp(App):
    CSS = """
    #output {
        height: 1fr;
        border: solid $primary-background;
    }
    #text-input {
        dock: bottom;
        margin: 0 0 1 0;
    }
    """

    BINDINGS = [
        Binding("ctrl+t", "set_threshold", "Threshold"),
        Binding("ctrl+l", "switch_lang", "Language"),
        Binding("ctrl+c", "quit", "Quit"),
    ]

    TITLE = "vocab-nlp"

    def __init__(self):
        super().__init__()
        self.lang = "nl"
        self.threshold = 0.5
        self.nlp = None
        self.freq = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield RichLog(id="output", wrap=True, highlight=True, markup=True)
        yield Input(placeholder="Enter text to analyze...", id="text-input")
        yield Footer()

    def on_mount(self) -> None:
        self.load_pipeline()

    @work(thread=True)
    def load_pipeline(self) -> None:
        log = self.query_one("#output", RichLog)
        logging.getLogger("stanza").setLevel(logging.WARNING)

        log.write(f"[dim][1/3] Downloading {self.lang} model...[/dim]")
        stanza.download(self.lang, processors=PROCESSORS, verbose=False)

        log.write(f"[dim][2/3] Loading Stanza pipeline...[/dim]")
        self.nlp = stanza.Pipeline(self.lang, processors=PROCESSORS, use_gpu=False, logging_level="WARN")

        log.write(f"[dim][3/3] Loading frequency list...[/dim]")
        self.freq = FREQ_LOADERS[self.lang]()

        log.write(f"[green]Ready.[/green] {len(self.freq)} frequency entries. Threshold: {self.threshold}\n")
        self.query_one("#text-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text or not self.nlp:
            return

        event.input.clear()
        self.process_text(text)

    @work(thread=True)
    def process_text(self, text: str) -> None:
        log = self.query_one("#output", RichLog)
        log.write(Text(f"> {text}", style="bold cyan"))
        log.write("")

        text = trim_text(text)
        doc = self.nlp(text)

        # Tokens table
        tokens_table = Table(show_lines=False, pad_edge=False, title="Tokens")
        tokens_table.add_column("Token", style="cyan")
        tokens_table.add_column("Lemma", style="green")
        tokens_table.add_column("POS", style="yellow")
        tokens_table.add_column("Deprel", style="magenta")
        tokens_table.add_column("Head", style="dim")

        for sent in doc.sentences:
            for word in sent.words:
                head_text = next((w.text for w in sent.words if w.id == word.head), "ROOT")
                tokens_table.add_row(word.text, word.lemma, word.upos, word.deprel, head_text)
            tokens_table.add_section()

        log.write(tokens_table)
        log.write("")

        # Vocab tables
        result = extract(doc, self.lang, self.freq)
        all_lemmas = result["lemmas"]

        above = [item for item in all_lemmas if item["weight"] > self.threshold]
        below = [item for item in all_lemmas if item["weight"] <= self.threshold]

        # Candidates panel
        above_table = Table(show_lines=False, pad_edge=False, expand=True)
        above_table.add_column("Lemma", style="bold")
        above_table.add_column("POS", style="yellow")
        above_table.add_column("Weight", justify="right")

        for item in above:
            w = item["weight"]
            weight_style = "green" if w >= 0.9 else "yellow" if w >= 0.6 else "red"
            above_table.add_row(item["text"], item["pos"], f"[{weight_style}]{w:.2f}[/{weight_style}]")

        # Filtered out panel
        below_table = Table(show_lines=False, pad_edge=False, expand=True)
        below_table.add_column("Lemma", style="bold")
        below_table.add_column("POS", style="yellow")
        below_table.add_column("Weight", justify="right")

        for item in below:
            w = item["weight"]
            below_table.add_row(item["text"], item["pos"], f"[red]{w:.2f}[/red]")

        panels = Columns([
            Panel(above_table, title="Candidates", border_style="green"),
            Panel(below_table, title="Filtered out", border_style="dim"),
        ], equal=True)

        log.write(panels)
        log.write("")

    def action_set_threshold(self) -> None:
        inp = self.query_one("#text-input", Input)
        inp.value = ""
        inp.placeholder = f"Enter threshold (current: {self.threshold}):"
        inp._threshold_mode = True

    def action_switch_lang(self) -> None:
        inp = self.query_one("#text-input", Input)
        inp.value = ""
        choices = ", ".join(LANGUAGES)
        inp.placeholder = f"Enter language ({choices}):"
        inp._lang_mode = True

    def on_input_submitted_special(self, event: Input.Submitted) -> None:
        """Handled via overriding on_input_submitted."""
        pass

    # Override to handle special modes
    _original_on_input_submitted = None

    def on_input_submitted(self, event: Input.Submitted) -> None:
        inp = event.input
        text = event.value.strip()

        if getattr(inp, "_threshold_mode", False):
            inp._threshold_mode = False
            inp.placeholder = "Enter text to analyze..."
            try:
                self.threshold = float(text)
                log = self.query_one("#output", RichLog)
                log.write(f"[dim]Threshold set to {self.threshold}[/dim]\n")
            except ValueError:
                pass
            inp.clear()
            return

        if getattr(inp, "_lang_mode", False):
            inp._lang_mode = False
            inp.placeholder = "Enter text to analyze..."
            if text in LANGUAGES:
                self.lang = text
                self.nlp = None
                inp.clear()
                self.load_pipeline()
            else:
                inp.clear()
            return

        if not text or not self.nlp:
            return

        inp.clear()
        self.process_text(text)


def main():
    app = VocabApp()
    app.run()


if __name__ == "__main__":
    main()
