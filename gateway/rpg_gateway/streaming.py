"""SSE framing and incremental extraction of the narrator's public text only."""
from __future__ import annotations

import json
from typing import BinaryIO, Iterator

NARRATIVE_KEYS = {"narrative", "text", "叙述", "正文"}


def sse_data(response: BinaryIO) -> Iterator[str]:
    lines: list[str] = []
    for raw in response:
        line = raw.decode("utf-8").rstrip("\r\n")
        if not line:
            if lines:
                yield "\n".join(lines)
                lines = []
        elif line.startswith("data:"):
            lines.append(line[5:].lstrip(" "))
    if lines:
        yield "\n".join(lines)


def _partial_string(text: str, start: int) -> str:
    """Decode only complete escape sequences; never expose half a surrogate pair."""
    out: list[str] = []
    i = start + 1
    escapes = {"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f", '"': '"', "\\": "\\", "/": "/"}
    while i < len(text):
        char = text[i]
        if char == '"':
            break
        if char != "\\":
            out.append(char)
            i += 1
            continue
        if i + 1 >= len(text):
            break
        escaped = text[i + 1]
        if escaped == "u":
            if i + 6 > len(text):
                break
            try:
                value = int(text[i + 2:i + 6], 16)
            except ValueError:
                break
            if 0xD800 <= value <= 0xDBFF:
                if i + 12 > len(text) or text[i + 6:i + 8] != "\\u":
                    break
                try:
                    low = int(text[i + 8:i + 12], 16)
                except ValueError:
                    break
                if not 0xDC00 <= low <= 0xDFFF:
                    break
                out.append(chr(0x10000 + ((value - 0xD800) << 10) + low - 0xDC00))
                i += 12
            else:
                if 0xDC00 <= value <= 0xDFFF:
                    break
                out.append(chr(value))
                i += 6
        elif escaped in escapes:
            out.append(escapes[escaped])
            i += 2
        else:
            break
    return "".join(out)


def partial_narrative(content: str) -> str:
    """Extract a top-level narrative string without leaking JSON/options/tool data."""
    text = content.lstrip()
    if text.startswith("`"):
        if "\n" not in text:
            return ""
        text = text.split("\n", 1)[1].lstrip()
    if not text:
        return ""
    if text[0] != "{":
        return text.rstrip()
    decoder = json.JSONDecoder()
    i = 1
    while i < len(text):
        while i < len(text) and text[i] in " \r\n\t,":
            i += 1
        try:
            key, i = decoder.raw_decode(text, i)
        except (ValueError, json.JSONDecodeError):
            return ""
        if not isinstance(key, str):
            return ""
        while i < len(text) and text[i].isspace():
            i += 1
        if i >= len(text) or text[i] != ":":
            return ""
        i += 1
        while i < len(text) and text[i].isspace():
            i += 1
        if i >= len(text):
            return ""
        if key in NARRATIVE_KEYS and text[i] == '"':
            return _partial_string(text, i).strip()
        try:
            _, i = decoder.raw_decode(text, i)
        except (ValueError, json.JSONDecodeError):
            return ""
    return ""
