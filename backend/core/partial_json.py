"""Parse the JSON a model has produced *so far*.

Streaming replies are cut mid-token. This trims the unfinished tail (an open string,
a dangling `"key":`, a half literal like `tru`), closes every open bracket, and
parses. Incomplete trailing values are dropped rather than guessed, so a partial
`{"rooms": [{"name": "Kitchen", "kind": "kitc` becomes `{"rooms": []}`, and the
next chunk that completes the room makes it appear.
"""

from __future__ import annotations

import json
import re

_DANGLING_KEY = re.compile(r',?\s*"(?:[^"\\]|\\.)*"\s*:\s*$')
_TAIL_TOKEN = re.compile(r'[,\[{:]\s*([^\s,\[\]{}:"]+)\s*$')


def _scan(text: str) -> tuple[list[tuple[str, int]], int | None]:
    """Return (open brackets as (char, index) in order, start index of an unterminated string or None)."""
    stack: list[tuple[str, int]] = []
    in_str = False
    esc = False
    str_start = None
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str, str_start = True, i
        elif ch in "[{":
            stack.append((ch, i))
        elif ch in "]}":
            if stack:
                stack.pop()
    return stack, (str_start if in_str else None)


def _drop_truncated_elements(text: str) -> str:
    """An object that is an array element and still open was cut mid-way: drop it entirely, so a
    half-generated room or op never shows up with default values."""
    while True:
        stack, _ = _scan(text)
        cut = next((idx for k, (ch, idx) in reversed(list(enumerate(stack))) if ch == "{" and k > 0 and stack[k - 1][0] == "["), None)
        if cut is None:
            return text
        text = text[:cut].rstrip().rstrip(",").rstrip()


def parse_partial(text: str):
    """Best-effort value for a JSON prefix; None if nothing parseable yet."""
    text = text.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    for _ in range(64):  # each round removes one unfinished tail token
        stack, str_start = _scan(text)
        if str_start is not None:
            text = text[:str_start]
        text = text.rstrip().rstrip(",").rstrip()
        text = _DANGLING_KEY.sub("", text).rstrip().rstrip(",").rstrip()
        m = _TAIL_TOKEN.search(text)
        if m:  # unfinished literal/number such as `tru` or `12.` — drop it (and its key)
            tail = m.group(1)
            if tail not in ("true", "false", "null") and not re.fullmatch(r"-?\d+(\.\d+)?([eE][-+]?\d+)?", tail):
                text = text[: m.start(1)].rstrip().rstrip(":").rstrip()
                text = _DANGLING_KEY.sub("", text).rstrip().rstrip(",").rstrip()
        text = _drop_truncated_elements(text)
        stack, _ = _scan(text)
        candidate = text + "".join("]" if b == "[" else "}" for b, _ in reversed(stack))
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            # Cut back to the last structural boundary and try again.
            cut = max(text.rfind(","), text.rfind("["), text.rfind("{"))
            if cut <= 0:
                return None
            text = text[:cut] if text[cut] == "," else text[: cut + 1]
    return None
