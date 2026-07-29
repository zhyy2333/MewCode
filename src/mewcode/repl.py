from __future__ import annotations

import sys
from collections.abc import Callable
from typing import TextIO

from .conversation import Conversation
from .providers import ProviderError

InputFunc = Callable[[str], str]


class Repl:
    def __init__(
        self,
        conversation: Conversation,
        stdout: TextIO = sys.stdout,
        stderr: TextIO = sys.stderr,
        input_func: InputFunc = input,
    ) -> None:
        self._conversation = conversation
        self._stdout = stdout
        self._stderr = stderr
        self._input = input_func

    def run(self) -> int:
        self._stdout.write("MewCode\n")
        self._stdout.write("Type /exit or /quit to exit.\n")
        self._stdout.flush()

        while True:
            try:
                user_text = self._input("mew> ").strip()
            except EOFError:
                self._stdout.write("\n")
                self._stdout.flush()
                return 0
            if not user_text:
                continue
            if user_text in {"/exit", "/quit"}:
                return 0

            try:
                for part in self._conversation.ask(user_text):
                    self._stdout.write(part)
                    self._stdout.flush()
                self._stdout.write("\n")
                self._stdout.flush()
            except ProviderError as exc:
                self._stderr.write(f"Error: {exc.message}\n")
                self._stderr.flush()
