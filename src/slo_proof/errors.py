"""The one error type every parser raises: a file, a line, and what is wrong."""

from __future__ import annotations


class InputError(Exception):
    """Bad input. ``line`` is 1-based, or 0 when the problem is not on one line."""

    def __init__(self, source: str, line: int, message: str) -> None:
        self.source = source
        self.line = line
        self.message = message
        where = f"{source}: line {line}" if line else source
        super().__init__(f"{where}: {message}")
