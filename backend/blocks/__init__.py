"""Recipe cards: domain knowledge retrieved into the build prompt.

A card is a markdown file with YAML front matter and one fenced JSON block of `GeoStep`s.
The steps are a worked example, not a parameterized object — the model authors its own
geometry, and the card shows the convention (which IFC entity, which solid op, which
numbers are sane). `retrieve` is deterministic token scoring so it works offline, in tests,
and with the mock.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

CARDS_DIR = Path(__file__).resolve().parent / "cards"

_TOKEN = re.compile(r"[a-z0-9]+")
# One-letter words and articles otherwise score every card that says "a wall".
_STOP = frozenset("a an the of and with on for to in over up its is by or from at as be this that".split())
_FENCE = re.compile(r"```json\s*(.*?)```", re.DOTALL)


@dataclass(frozen=True)
class Card:
    id: str
    title: str
    keywords: tuple[str, ...]
    tags: tuple[str, ...]
    ifc: str
    ifc_type: str | None
    ifc4x3: str | None
    summary: str
    notes: str
    steps: tuple[dict, ...]
    path: Path

    def prompt_text(self) -> str:
        """What gets injected into the build prompt: the convention, then a worked example."""
        typing = self.ifc + (f" / {self.ifc_type}" if self.ifc_type else "")
        prefer = f"\nIFC4X3 would use {self.ifc4x3}; this card uses {self.ifc} because the backend targets IFC4." if self.ifc4x3 else ""
        body = self.notes.strip()
        example = json.dumps({"steps": list(self.steps)}, indent=1)
        return f"## {self.title} ({self.id})\n{self.summary}\nIFC: {typing}{prefer}\n{body}\n\nWorked example:\n{example}"


def _tokens(text: str) -> set[str]:
    return {t for t in _TOKEN.findall(text.lower()) if t not in _STOP and len(t) > 1}


def parse_card(path: Path) -> Card:
    raw = path.read_text(encoding="utf-8")
    if not raw.startswith("---"):
        raise ValueError(f"{path.name}: missing YAML front matter")
    _, front, body = raw.split("---", 2)
    meta = yaml.safe_load(front) or {}
    match = _FENCE.search(body)
    if not match:
        raise ValueError(f"{path.name}: no fenced JSON exemplar")
    payload = json.loads(match.group(1))
    steps = payload["steps"] if isinstance(payload, dict) else payload
    if not isinstance(steps, list) or not steps:
        raise ValueError(f"{path.name}: exemplar has no steps")
    return Card(
        id=str(meta["id"]),
        title=str(meta.get("title") or meta["id"]),
        keywords=tuple(str(k).lower() for k in meta.get("keywords") or []),
        tags=tuple(str(t).lower() for t in meta.get("tags") or []),
        ifc=str(meta.get("ifc") or "IfcBuildingElementProxy"),
        ifc_type=meta.get("ifc_type") or None,
        ifc4x3=meta.get("ifc4x3") or None,
        summary=str(meta.get("summary") or "").strip(),
        notes=body[: match.start()].strip(),
        steps=tuple(steps),
        path=path,
    )


@lru_cache(maxsize=1)
def load_cards() -> tuple[Card, ...]:
    paths = sorted(CARDS_DIR.glob("*.md"))
    cards = tuple(parse_card(p) for p in paths)
    ids = [c.id for c in cards]
    if len(ids) != len(set(ids)):
        raise ValueError(f"duplicate card ids: {ids}")
    return cards


def card_by_id(card_id: str) -> Card | None:
    return next((c for c in load_cards() if c.id == card_id), None)


def retrieve(prompt: str, k: int = 4) -> list[Card]:
    """Top-k cards for a prompt. Keyword hits dominate; title and summary tokens break ties.

    Stable: equal scores keep the card id order, so a test can assert the exact set."""
    want = _tokens(prompt)
    if not want:
        return []
    scored: list[tuple[int, str, Card]] = []
    for card in load_cards():
        keys = set()
        for keyword in card.keywords:
            keys |= _tokens(keyword)
        title = _tokens(card.title)
        summary = _tokens(card.summary) | _tokens(" ".join(card.tags))
        score = 5 * len(want & keys) + 2 * len(want & title) + len(want & summary)
        # A multi-word keyword that appears as a phrase scores extra, so "party wall" beats "wall".
        text = prompt.lower()
        score += 4 * sum(1 for keyword in card.keywords if " " in keyword and keyword in text)
        if score:
            scored.append((score, card.id, card))
    scored.sort(key=lambda row: (-row[0], row[1]))
    return [card for _, _, card in scored[:k]]
