"""Shared rich console helpers for run.py/verify.py's step logging.

log() is a drop-in replacement for print(f"[prefix] {msg}", file=sys.stderr):
the exact plaintext "[prefix] <msg>" content is still emitted verbatim (msg
itself is never altered/truncated/reworded), only color/styling is added
around it. rich auto-detects non-TTY output (piped/redirected) and disables
animation, so this degrades to plain, identical text when not in a terminal.

msg is assembled as a rich Text rather than interpolated into a markup
string, because msg carries third-party data (search result URLs and titles,
exception messages). Markup-parsing those would silently delete anything
that looks like a tag -- e.g. a URL containing "[x]" would print without it
-- and would raise MarkupError on an unmatched closing tag like "[/x]",
killing a run mid-pipeline.
"""
from __future__ import annotations

from contextlib import contextmanager

from rich.console import Console
from rich.text import Text

console = Console(stderr=True)


def log(msg: str, prefix: str = "run") -> None:
    console.print(Text.assemble((f"[{prefix}] ", "bold cyan"), msg))


def rule(title: str) -> None:
    console.rule(f"[bold]{title}[/bold]", style="cyan")


@contextmanager
def spinner(description: str):
    with console.status(description, spinner="dots"):
        yield
