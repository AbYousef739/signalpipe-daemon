"""Server-Sent-Events frame parser — pure stdlib (json only), no transport.

Kept separate from client.py so it carries no `requests` dependency and can be
unit-tested against a plain list of lines.
"""
from __future__ import annotations

import json
from typing import Iterable, Iterator, Tuple


def parse_sse(lines: Iterable[str]) -> Iterator[Tuple[str, dict]]:
    """Turn a stream of SSE text lines into (event_name, data_dict) frames.

    A frame ends on a blank line. `event:` sets the name (default "message");
    `data:` lines are concatenated with newlines then JSON-decoded. Comment
    lines (starting with ":") and id/retry fields are ignored. Malformed JSON is
    surfaced as {"_raw": <text>} rather than silently dropped.
    """
    event: str | None = None
    data_lines: list[str] = []
    for raw in lines:
        if raw is None:
            continue
        line = raw.rstrip("\r")
        if line == "":
            if event is not None or data_lines:
                payload = "\n".join(data_lines)
                try:
                    data = json.loads(payload) if payload else {}
                except json.JSONDecodeError:
                    data = {"_raw": payload}
                yield (event or "message", data)
            event, data_lines = None, []
            continue
        if line.startswith(":"):
            continue  # SSE comment / keep-alive ping
        field, _, value = line.partition(":")
        if value.startswith(" "):
            value = value[1:]
        if field == "event":
            event = value
        elif field == "data":
            data_lines.append(value)
        # id / retry fields are intentionally ignored
