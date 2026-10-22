"""Human setup output is stderr-only; never used by MCP transports."""

from __future__ import annotations

import os
import shutil
import sys
import textwrap

BANNER = r""" _  ___           ____       _     _
| |/ (_)_ __ __ _| __ ) _ __(_) __| | __ _  ___
| ' /| | '__/ _` |  _ \| '__| |/ _` |/ _` |/ _ \
| . \| | | | (_| | |_) | |  | | (_| | (_| |  __/
|_|\_\_|_|  \__,_|____/|_|  |_|\__,_|\__, |\___|
                                    |___/"""


class SetupUI:
    def __init__(self, language="de", stream=None):
        self.language = language
        self.stream = stream or sys.stderr

    def text(self, de, en):
        return de if self.language == "de" else en

    def say(self, de, en=None):
        value = self.text(de, en or de)
        width = max(24, min(88, shutil.get_terminal_size((80, 24)).columns))
        print(textwrap.fill(value, width=width), file=self.stream, flush=True)

    def banner(self):
        width = shutil.get_terminal_size((80, 24)).columns
        banner = BANNER if width >= 50 else "=== KiraBridge ==="
        color = self.stream.isatty() and "NO_COLOR" not in os.environ
        print(
            ("\033[36m" if color else "") + banner + ("\033[0m" if color else ""),
            file=self.stream,
            flush=True,
        )

    def step(self, number, de, en):
        self.say(f"[{number}] {de}", f"[{number}] {en}")

    def ask(self, de, en, default=""):
        print(
            self.text(de, en) + (f" [{default}]" if default else "") + ": ",
            file=self.stream,
            end="",
            flush=True,
        )
        return input().strip() or default

    def confirm(self, de, en, *, default=False):
        answer = self.ask(
            de,
            en,
            "J/n"
            if default and self.language == "de"
            else "Y/n"
            if default
            else "j/N"
            if self.language == "de"
            else "y/N",
        )
        if answer in {"J/n", "Y/n", "j/N", "y/N"}:
            return default
        return answer.lower() in {"y", "yes", "j", "ja"}
