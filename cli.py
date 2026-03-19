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

import stanza  # noqa: F401 — must import before Textual to apply tqdm patch above

from pipeline import FREQ_LOADERS, LANG_PRESETS, LANGUAGES, LEVELS, create_stanza_pipeline, extract, trim_text


class ListPicker(ModalScreen[str]):
    """Generic modal popup for selecting from a list of options."""

    CSS = """
    ListPicker {
        align: center middle;
    }
    #picker-list {
        width: 20;
        height: auto;
        max-height: 10;
        border: solid $accent;
        background: $surface;
    }
    """

    BINDINGS = [Binding("escape", "dismiss('')", "Cancel")]

    def __init__(self, options: list[str], current: str):
        super().__init__()
        self.options = options
        self.current = current

    def compose(self) -> ComposeResult:
        yield OptionList(*self.options, id="picker-list")

    def on_mount(self) -> None:
        ol = self.query_one("#picker-list", OptionList)
        idx = self.options.index(self.current) if self.current in self.options else 0
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
        self._input_mode = None  # "threshold" or None

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

        log.write(f"[dim][1/2] Loading Stanza pipeline for {self.lang}...[/dim]")
        self.nlp = create_stanza_pipeline(self.lang)

        log.write(f"[dim][2/2] Loading frequency list...[/dim]")
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
        all_items = result["items"]

        above = [item for item in all_items if item["score"] > self.threshold]
        below = [item for item in all_items if item["score"] <= self.threshold]

        bands = LANG_PRESETS[self.lang]["levels"][self.level]["band"]

        def _make_table(items):
            table = Table(show_lines=False, pad_edge=False, expand=True)
            table.add_column("Text", style="bold")
            table.add_column("Type", style="yellow")
            table.add_column("Score", justify="right")
            table.add_column("Band", style="dim")

            for item in items:
                s = item["score"]
                score_style = "green" if s >= 0.9 else "yellow" if s >= 0.5 else "red"
                rank = item.get("rank")
                if rank is None:
                    band = "?"
                elif rank <= bands["known"]:
                    band = "known"
                elif rank <= bands["target"]:
                    band = "target"
                else:
                    band = "beyond"
                label = item.get("pos", item["type"])
                table.add_row(item["text"], label, f"[{score_style}]{s:.2f}[/{score_style}]", band)
            return table

        # Build panels, skip empty ones
        panels = []

        if above:
            panels.append(Panel(_make_table(above), title="Candidates", border_style="green"))
        if below:
            panels.append(Panel(_make_table(below), title="Filtered out", border_style="dim"))

        propn = result.get("proper_nouns", [])
        if propn:
            propn_table = Table(show_lines=False, pad_edge=False, expand=True)
            propn_table.add_column("Name", style="bold")
            for item in propn:
                propn_table.add_row(item["text"])
            panels.append(Panel(propn_table, title="Proper nouns", border_style="cyan"))

        nums = result.get("numbers", [])
        if nums:
            num_table = Table(show_lines=False, pad_edge=False, expand=True)
            num_table.add_column("Number", style="bold")
            for item in nums:
                num_table.add_row(item["text"])
            panels.append(Panel(num_table, title="Numbers", border_style="magenta"))

        merged = result.get("merged_fragments", [])
        if merged:
            merge_table = Table(show_lines=False, pad_edge=False, expand=True)
            merge_table.add_column("Parts", style="bold")
            merge_table.add_column("Result", style="green")
            merge_table.add_column("Rule", style="dim")
            for item in merged:
                merge_table.add_row(
                    " + ".join(item["parts"]),
                    item["merged"],
                    item["rule"],
                )
            panels.append(Panel(merge_table, title="Merged fragments", border_style="yellow"))

        if not panels:
            log.write("[dim]No results[/dim]")
        else:
            log.write(Columns(panels, equal=True))

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

        self.push_screen(ListPicker(LEVELS, self.level), on_level_selected)

    def action_switch_lang(self) -> None:
        def on_lang_selected(lang: str) -> None:
            if lang and lang != self.lang:
                self.lang = lang
                self.nlp = None
                self.load_pipeline()

        self.push_screen(ListPicker(LANGUAGES, self.lang), on_lang_selected)


def main():
    app = VocabApp()
    app.run()


if __name__ == "__main__":
    main()
