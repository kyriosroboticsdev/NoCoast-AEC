"""Which library bricks a prompt names — the rule-based stand-in for a model reading the request.

Matches brick names, ids and multi-word tags ("heat pump", "solar panels"), plus a short list of
single words that are unambiguous on their own ("elevator", "sprinklers"). Generic words ("panel",
"outdoor", "table") and things the template planner already builds (fences, decks, porches) are left
out, so a plain house prompt names no bricks. Bricks that generalise a catalogue fixture are skipped
too: the template furnishes rooms with those itself, and so is anything written as a style ("a wood
stove-style fireplace" is a fireplace).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from bricks import library

NUMBERS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4}
SINGLE_WORDS = {
    "elevator", "lift", "stairlift", "pool", "jacuzzi", "sprinkler", "cctv", "mvhr", "boiler", "radiator", "pv",
    "photovoltaic", "tree", "hedge", "generator", "wifi", "router", "skylight", "rooflight", "ramp", "chimney", "beam",
    "footing", "pile", "wallbox", "intercom", "doorbell", "thermostat", "extinguisher", "powerwall", "turbine", "shed",
    "bollard", "flagpole", "urinal", "bidet", "sauna", "trampoline", "greenhouse",
}
MAX_COUNT = 4


ROOM_KINDS = {"bedroom": "bedroom", "bathroom": "bathroom", "kitchen": "kitchen", "living": "living", "lounge": "living",
              "office": "office", "hall": "hall", "garage": "garage", "utility": "utility", "dining": "dining"}
EACH = ("both", "all", "each", "every")


@dataclass(frozen=True)
class Mention:
    brick: str
    phrase: str
    count: int
    room_kind: str | None = None     # "radiators in the bedrooms"
    each: bool = False               # "… in both/all/each bedroom(s)": one per room of that kind


@lru_cache(maxsize=1)
def _phrases() -> list[tuple[str, list[str]]]:
    """(phrase, candidate brick ids), longest phrase first."""
    by_phrase: dict[str, list[str]] = {}
    for b in library().bricks.values():
        if b.legacy_fixture:
            continue
        words = {b.name.lower(), b.id.replace("_", " ")} | {t.lower() for t in b.tags if "-" not in t}
        for w in words:
            w = re.sub(r"[^a-z0-9 ]+", " ", w).strip()
            if w and (" " in w or w in SINGLE_WORDS):
                by_phrase.setdefault(w, []).append(b.id)
    return sorted(by_phrase.items(), key=lambda kv: (-len(kv[0]), kv[0]))


def mentioned_bricks(prompt: str) -> list[Mention]:
    text = " " + re.sub(r"[^a-z0-9]+", " ", prompt.lower()) + " "
    taken: list[tuple[int, int]] = []
    found: dict[str, Mention] = {}
    for phrase, ids in _phrases():
        for m in re.finditer(r"(?:\b(" + "|".join(NUMBERS) + r"|\d+) )?\b" + re.escape(phrase) + r"(?:e?s)?\b", text):
            start, end = m.span()
            if text.startswith(" style ", end) or any(start < b and a < end for a, b in taken):
                continue
            taken.append((start, end))
            brick = ids[0] if len(ids) == 1 else next((b.id for b, _ in library().search(phrase, limit=10) if b.id in ids), ids[0])
            n = m.group(1)
            count = min(MAX_COUNT, int(n) if n and n.isdigit() else NUMBERS.get(n or "a", 1))
            where = re.match(r" in (?:the |a |an |(" + "|".join(EACH) + r") )?([a-z]+?)s? ", text[end:])
            kind = ROOM_KINDS.get(where.group(2)) if where else None
            if brick not in found:
                found[brick] = Mention(brick, phrase, count, kind, bool(kind and where.group(1)))
    return list(found.values())
