"""Incremental sentence segmentation for a stream of text deltas.

The app speaks each sentence as soon as it is complete, which is what makes the agent
live. A sentence ends at `.`, `!`, `?`, the Arabic question mark `؟`, the Arabic full stop
`۔` or a newline, provided the terminator is followed by whitespace (so "9.30" survives)
or the stream ends. Abbreviations such as "e.g." are split; that is a known limit.
"""

from __future__ import annotations

import re

_BOUNDARY = re.compile(r"([.!?؟۔]+)(\s+)|(\n+)")


class SentenceSplitter:
    def __init__(self) -> None:
        self._buffer = ""

    def feed(self, delta: str) -> list[str]:
        """Add text; return every sentence completed by it, in order."""
        self._buffer += delta
        out: list[str] = []
        while True:
            m = _BOUNDARY.search(self._buffer)
            if not m:
                break
            end = m.end(1) if m.group(1) else m.start(3)
            sentence = self._buffer[:end].strip()
            self._buffer = self._buffer[m.end() :]
            if sentence:
                out.append(sentence)
        return out

    def flush(self) -> list[str]:
        """The stream ended: whatever is left is the last sentence."""
        rest = self._buffer.strip()
        self._buffer = ""
        return [rest] if rest else []
