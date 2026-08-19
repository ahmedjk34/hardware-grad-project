#!/usr/bin/env python3
"""A tiny typed-command engine for the preview tools.

Why this exists
---------------
OpenCV's only input channel is cv2.waitKey, and it delivers a keystroke *only
while the image window itself has focus*. Typing into the terminal that launched
the tool does nothing, and over VNC or ssh -X the window often has to be clicked
before it receives anything at all. The usual symptom is "I press keys and
nothing happens", with no way to tell whether the key arrived.

So the tools accept the same commands from three places — an in-window prompt,
the terminal's stdin, and mouse-driven trackbars — and echo every one of them
back on screen. This module is the part none of that depends on: parsing,
dispatch, the edit buffer, and the message log, with no cv2, no argparse, no
stdin and no printing, so it stays unit-testable and importable anywhere.

    cmds = CommandSet()
    cmds.add("fov", set_fov, args="<deg|+N|-N>", help="lens FOV")
    result = cmds.execute("fov +2")     # -> Result(ok=True, message="lens FOV 162")
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field


class CommandError(Exception):
    """Raised by a handler to report a user error rather than a crash.

    The message is shown to the user as-is, so write it for them: say what was
    wrong AND what would have been right.
    """


@dataclass
class Result:
    ok: bool
    message: str


@dataclass
class Command:
    name: str
    handler: object
    args: str = ""
    help: str = ""
    aliases: tuple = ()

    @property
    def usage(self) -> str:
        return f"{self.name} {self.args}".strip()


class CommandSet:
    """Name -> handler, with alias support and generated help.

    Handlers take the argument list and return a message string (or None for the
    default acknowledgement). Raising CommandError reports a user mistake;
    anything else propagating is a real bug and is reported as such.
    """

    def __init__(self):
        self._by_name: dict[str, Command] = {}
        self._order: list[Command] = []

    def add(self, name, handler, args="", help="", aliases=()):
        cmd = Command(name, handler, args, help, tuple(aliases))
        self._order.append(cmd)
        for key in (name, *aliases):
            self._by_name[key] = cmd
        return cmd

    def __contains__(self, name):
        return name in self._by_name

    def execute(self, line: str) -> Result | None:
        """Run one command line. Returns None for blank input.

        Never raises: a bad command is a Result(ok=False), because this runs
        inside a render loop that must not die because of a typo.
        """
        parts = line.strip().split()
        if not parts:
            return None
        name, args = parts[0].lower(), parts[1:]

        cmd = self._by_name.get(name)
        if cmd is None:
            suggestion = self.closest(name)
            hint = f" Did you mean '{suggestion}'?" if suggestion else ""
            return Result(False, f"unknown command '{name}'.{hint} Try 'help'.")

        try:
            message = cmd.handler(args)
        except CommandError as exc:
            return Result(False, f"{cmd.name}: {exc}")
        except Exception as exc:  # a handler bug, not a user error
            return Result(False, f"{cmd.name}: internal error: {exc!r}")
        return Result(True, message if message else f"{cmd.name} ok")

    def closest(self, name):
        """Cheapest useful typo suggestion: a shared prefix, longest first.

        Falls back from a two-letter to a one-letter prefix, so a transposed
        first pair ('sacle') still suggests something.
        """
        for n_chars in (2, 1):
            candidates = [n for n in self._by_name if n.startswith(name[:n_chars])]
            if candidates:
                return max(candidates, key=len)
        return None

    def help_lines(self) -> list[str]:
        """One aligned line per command, for the on-screen and terminal help."""
        width = max((len(c.usage) for c in self._order), default=0)
        lines = []
        for cmd in self._order:
            alias = f"  ({', '.join(cmd.aliases)})" if cmd.aliases else ""
            lines.append(f"  {cmd.usage:<{width}}  {cmd.help}{alias}")
        return lines


# --- argument helpers -------------------------------------------------------
# Shared so every numeric command accepts the same "158" / "+2" / "-2" forms.

def parse_number(text: str, current: float, kind=float) -> float:
    """Absolute value, or a relative step when the text is signed.

    `fov 158` sets 158; `fov +2` and `fov -2` step from the current value. None
    of these parameters is ever meaningfully negative, so reading a leading sign
    as "relative" costs nothing and saves the user doing arithmetic while
    watching an edge for bow.
    """
    text = text.strip()
    try:
        value = kind(text)
    except ValueError:
        raise CommandError(f"'{text}' is not a number")
    return current + value if text[0] in "+-" else value


def parse_choice(text: str, choices) -> str:
    """Match a choice, allowing any unambiguous prefix of it."""
    text = text.strip().lower()
    if text in choices:
        return text
    hits = [c for c in choices if c.startswith(text)]
    if len(hits) == 1:
        return hits[0]
    raise CommandError(
        f"'{text}' is not one of: {', '.join(choices)}"
        if not hits else f"'{text}' is ambiguous: {', '.join(hits)}"
    )


def need_args(args, n, usage):
    """Enforce an exact argument count, quoting the usage on failure."""
    if len(args) != n:
        raise CommandError(f"expected {n} argument(s) — usage: {usage}")
    return args


# --- the in-window prompt ---------------------------------------------------

# waitKeyEx codes. GTK and Qt disagree on several of these and both appear on a
# Raspberry Pi desktop, so every key lists all the codes seen in practice.
KEY_ENTER = (13, 10)
KEY_BACKSPACE = (8, 127, 65288)
KEY_ESC = (27,)
KEY_UP = (65362, 2490368)
KEY_DOWN = (65364, 2621440)


@dataclass
class EditBuffer:
    """The `:` prompt: a text line, and a history you can arrow through.

    Deliberately pure — it takes key codes and returns a submitted string, so it
    can be tested without a window and reused by any of the tools.
    """

    text: str = ""
    active: bool = False
    history: list = field(default_factory=list)
    _history_pos: int = -1

    def open(self, initial=""):
        self.text = initial
        self.active = True
        self._history_pos = -1

    def close(self):
        self.text = ""
        self.active = False
        self._history_pos = -1

    def key(self, code: int):
        """Feed one key code. Returns the submitted line, or None.

        Returns "" (not None) when the user cancels, so the caller can tell
        "closed with nothing" from "still typing".
        """
        if code in KEY_ENTER:
            line = self.text.strip()
            if line:
                self.history.append(line)
            self.close()
            return line
        if code in KEY_ESC:
            self.close()
            return ""
        if code in KEY_BACKSPACE:
            self.text = self.text[:-1]
            return None
        if code in KEY_UP:
            self._recall(+1)
            return None
        if code in KEY_DOWN:
            self._recall(-1)
            return None
        if 32 <= code <= 126:
            self.text += chr(code)
        return None

    def _recall(self, direction):
        if not self.history:
            return
        self._history_pos = max(-1, min(self._history_pos + direction,
                                        len(self.history) - 1))
        self.text = "" if self._history_pos < 0 else self.history[-1 - self._history_pos]

    def render(self) -> str:
        """The prompt as drawn, with a block cursor."""
        return f":{self.text}_"


# --- feedback ---------------------------------------------------------------

@dataclass
class MessageLog:
    """Recent feedback, newest last, with per-entry age so it can fade out.

    Every accepted key, every command and every rejected key goes in here. That
    is the whole point: if a keystroke never reaches the window, nothing appears,
    which tells the user the problem is window focus rather than the command.
    """

    limit: int = 40
    entries: deque = field(default_factory=lambda: deque(maxlen=40))

    def add(self, ok: bool, text: str):
        self.entries.append((time.monotonic(), ok, text))
        return text

    def push(self, result: Result | None):
        if result is not None:
            self.add(result.ok, result.message)
        return result

    def recent(self, count=4, max_age=6.0):
        """The last `count` entries newer than `max_age` seconds."""
        now = time.monotonic()
        fresh = [(ok, text) for stamp, ok, text in self.entries
                 if now - stamp <= max_age]
        return fresh[-count:]
