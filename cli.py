"""Interactive TUI for testing the extract pipeline locally."""

import logging
import os
import sys
import warnings
from pathlib import Path

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
from textual.screen import ModalScreen
from textual.widgets import Footer, Header, Input, OptionList, RichLog

import stanza

from pipeline import FREQ_LOADERS, LANGUAGES, LEVEL_BANDS, LEVELS, PROCESSORS, extract, trim_text


class LevelPicker(ModalScreen[str]):
    """Modal popup for selecting learner level."""

    CSS = """
    LevelPicker {
        align: center middle;
    }
    #level-list {
        width: 20;
        height: auto;
        max-height: 10;
        border: solid $accent;
        background: $surface;
    }
    """

    BINDINGS = [Binding("escape", "dismiss('')", "Cancel")]

    def __init__(self, current: str):
        super().__init__()
        self.current = current

    def compose(self) -> ComposeResult:
        options = OptionList(*LEVELS, id="level-list")
        yield options

    def on_mount(self) -> None:
        ol = self.query_one("#level-list", OptionList)
        idx = LEVELS.index(self.current) if self.current in LEVELS else 0
        ol.highlighted = idx
        ol.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(str(event.option.prompt))


HISTORY_FILE = Path.home() / ".local" / "share" / "vocab-nlp" / "history.txt"
MAX_HISTORY = 100


class HistoryInput(Input):
    """Input with history (up/down) and persistent storage."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.history: list[str] = self._load_history()
        self.history_index: int = -1

    @staticmethod
    def _load_history() -> list[str]:
        if HISTORY_FILE.exists():
            lines = HISTORY_FILE.read_text().strip().splitlines()
            return lines[:MAX_HISTORY]
        return []

    def _save_history(self) -> None:
        HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        HISTORY_FILE.write_text("\n".join(self.history[:MAX_HISTORY]))

    BINDINGS = [
        Binding("ctrl+e", "app.set_level", "Level", priority=True),
        Binding("ctrl+t", "app.set_threshold", "Threshold", priority=True),
        Binding("ctrl+l", "app.switch_lang", "Language", priority=True),
    ]

    def on_key(self, event) -> None:
        if event.key == "up":
            if self.history and self.history_index < len(self.history) - 1:
                self.history_index += 1
                self.value = self.history[self.history_index]
                self.cursor_position = len(self.value)
            event.stop()
            event.prevent_default()
        elif event.key == "down":
            if self.history_index > 0:
                self.history_index -= 1
                self.value = self.history[self.history_index]
                self.cursor_position = len(self.value)
            elif self.history_index == 0:
                self.history_index = -1
                self.value = ""
            event.stop()
            event.prevent_default()

    def push_history(self, text: str) -> None:
        if text and (not self.history or self.history[0] != text):
            self.history.insert(0, text)
        self.history_index = -1
        self._save_history()


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
        Binding("ctrl+e", "set_level", "Level"),
        Binding("ctrl+t", "set_threshold", "Threshold"),
        Binding("ctrl+l", "switch_lang", "Language"),
        Binding("ctrl+c", "quit", "Quit"),
    ]

    TITLE = "vocab-nlp"

    def __init__(self):
        super().__init__()
        self.lang = "nl"
        self.level = "A0"
        self.threshold = 0.5
        self.nlp = None
        self.freq = None
        self._input_mode = None  # "threshold", "level", "lang", or None

    def compose(self) -> ComposeResult:
        yield Header()
        yield RichLog(id="output", wrap=True, highlight=True, markup=True)
        yield HistoryInput(placeholder="Enter text to analyze...", id="text-input")
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

        log.write(f"[green]Ready.[/green] {len(self.freq)} entries | Level: {self.level} | Threshold: {self.threshold}\n")
        self.query_one("#text-input", HistoryInput).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        inp = self.query_one("#text-input", HistoryInput)
        text = event.value.strip()

        if self._input_mode == "threshold":
            self._input_mode = None
            inp.placeholder = "Enter text to analyze..."
            try:
                self.threshold = float(text)
                log = self.query_one("#output", RichLog)
                log.write(f"[dim]Threshold set to {self.threshold}[/dim]\n")
            except ValueError:
                pass
            inp.clear()
            return

        if self._input_mode == "lang":
            self._input_mode = None
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

        inp.push_history(text)
        inp.clear()
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
        result = extract(doc, self.lang, self.freq, level=self.level)
        all_lemmas = result["lemmas"]

        above = [item for item in all_lemmas if item["weight"] > self.threshold]
        below = [item for item in all_lemmas if item["weight"] <= self.threshold]

        bands = LEVEL_BANDS[self.level]

        def _make_table(items):
            table = Table(show_lines=False, pad_edge=False, expand=True)
            table.add_column("Lemma", style="bold")
            table.add_column("POS", style="yellow")
            table.add_column("Weight", justify="right")
            table.add_column("Band", style="dim")

            for item in items:
                w = item["weight"]
                weight_style = "green" if w >= 0.9 else "yellow" if w >= 0.5 else "red"
                rank = item.get("rank")
                if rank is None:
                    band = "?"
                elif rank <= bands["known"]:
                    band = "known"
                elif rank <= bands["target"]:
                    band = "target"
                else:
                    band = "beyond"
                table.add_row(item["text"], item["pos"], f"[{weight_style}]{w:.2f}[/{weight_style}]", band)
            return table

        # Proper nouns panel
        propn = result.get("proper_nouns", [])
        propn_table = Table(show_lines=False, pad_edge=False, expand=True)
        propn_table.add_column("Name", style="bold")
        for item in propn:
            propn_table.add_row(item["text"])

        panels = Columns([
            Panel(_make_table(above), title="Candidates", border_style="green"),
            Panel(_make_table(below), title="Filtered out", border_style="dim"),
            Panel(propn_table, title="Proper nouns", border_style="cyan"),
        ], equal=True)

        log.write(panels)
        log.write("")

    def action_set_threshold(self) -> None:
        inp = self.query_one("#text-input", HistoryInput)
        inp.value = ""
        inp.placeholder = f"Threshold ({self.threshold}):"
        self._input_mode = "threshold"

    def action_set_level(self) -> None:
        def on_level_selected(level: str) -> None:
            if level:
                self.level = level
                log = self.query_one("#output", RichLog)
                log.write(f"[dim]Level set to {self.level}[/dim]\n")

        self.push_screen(LevelPicker(self.level), on_level_selected)

    def action_switch_lang(self) -> None:
        inp = self.query_one("#text-input", HistoryInput)
        inp.value = ""
        inp.placeholder = f"Language ({', '.join(LANGUAGES)}):"
        self._input_mode = "lang"


def main():
    app = VocabApp()
    app.run()


if __name__ == "__main__":
    main()
