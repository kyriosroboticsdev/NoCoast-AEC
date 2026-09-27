"""The brick library: loading, lookup and search.

Bricks live as JSON files in `bricks/library/` (one file per discipline). Adding a brick
is adding a JSON object — no code. `search` is a small BM25 over the id, name, category,
tags and description, with a few trade synonyms, so the model can ask in its own words
("somewhere to hang coats", "fresh air", "stop the floor sagging").
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path

from bricks.model import Brick

LIBRARY_DIR = Path(__file__).resolve().parent / "library"
FIELD_WEIGHTS = {"id": 3.0, "name": 3.0, "tags": 2.0, "category": 1.5, "discipline": 1.0, "description": 1.0}
SYNONYMS = {
    "toilet": ["wc"], "wc": ["toilet"], "loo": ["wc", "toilet"], "tub": ["bath", "bathtub"], "bathtub": ["bath"],
    "fridge": ["refrigerator"], "refrigerator": ["fridge"], "stove": ["cooker", "hob", "oven"], "cooker": ["oven", "hob"],
    "couch": ["sofa"], "sofa": ["couch"], "lift": ["elevator"], "elevator": ["lift"], "ac": ["air", "conditioning"],
    "aircon": ["air", "conditioning"], "hvac": ["heating", "ventilation", "air"], "pv": ["solar", "photovoltaic"],
    "solar": ["pv", "photovoltaic"], "sprinklers": ["sprinkler"], "detector": ["sensor", "alarm"], "wifi": ["router", "data"],
    "heater": ["heating"], "radiator": ["heating"], "footing": ["foundation"], "foundation": ["footing"],
    "girder": ["beam"], "joist": ["beam"], "post": ["column"], "pillar": ["column"], "sag": ["beam", "span"],
    "sagging": ["beam", "span", "support"], "deflection": ["beam", "span"], "cantilever": ["transfer", "beam", "column"],
    "overhang": ["transfer", "column", "support"], "load": ["beam", "column", "support"], "bearing": ["beam", "column"],
    "span": ["beam"], "tree": ["planting"], "plant": ["planting"], "fence": ["fencing"], "pool": ["swimming"],
    "charger": ["ev", "charging"], "car": ["parking", "ev"], "tv": ["television", "display"], "bed": ["sleeping"],
    "storage": ["cabinet", "shelf"], "wardrobe": ["closet"], "closet": ["wardrobe"], "desk": ["workstation"],
}
STOP = {"a", "an", "the", "of", "for", "to", "in", "on", "and", "with", "some", "i", "want", "need", "add", "put", "me",
        "my", "is", "it", "that", "this", "be", "or", "as", "at", "by", "we", "our", "please", "room", "rooms"}
_TOKEN = re.compile(r"[a-z0-9]+")


def tokens(text: str) -> list[str]:
    out = []
    for t in _TOKEN.findall(text.lower().replace("_", " ")):
        if t in STOP:
            continue
        out.append(t[:-1] if len(t) > 4 and t.endswith("s") and not t.endswith("ss") else t)
    return out


class Library:
    def __init__(self, bricks: list[Brick]):
        ids = [b.id for b in bricks]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            raise ValueError(f"duplicate brick ids: {dupes}")
        self.bricks = {b.id: b for b in bricks}
        self._docs: dict[str, Counter] = {}
        for b in bricks:
            doc: Counter = Counter()
            for field, weight in FIELD_WEIGHTS.items():
                value = getattr(b, field)
                text = " ".join(value) if isinstance(value, list) else str(value)
                for t in tokens(text):
                    doc[t] += weight
            self._docs[b.id] = doc
        self._avg = sum(sum(d.values()) for d in self._docs.values()) / max(1, len(self._docs))
        df: Counter = Counter()
        for doc in self._docs.values():
            df.update(set(doc))
        n = len(self._docs)
        self._idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}

    def __len__(self) -> int:
        return len(self.bricks)

    def get(self, brick_id: str) -> Brick | None:
        if brick_id is None:
            return None
        key = brick_id.strip().lower().replace("-", "_").replace(" ", "_")
        return self.bricks.get(key)

    def by_legacy(self, fixture_kind: str) -> Brick | None:
        return next((b for b in self.bricks.values() if b.legacy_fixture == fixture_kind), None)

    def disciplines(self) -> dict[str, list[Brick]]:
        out: dict[str, list[Brick]] = {}
        for b in self.bricks.values():
            out.setdefault(b.discipline, []).append(b)
        return out

    def search(self, query: str, discipline: str | None = None, limit: int = 8) -> list[tuple[Brick, float]]:
        q = tokens(query or "")
        expanded: Counter = Counter()
        for t in q:
            expanded[t] += 1.0
            for s in SYNONYMS.get(t, []):
                expanded[s] += 0.5
        k1, b = 1.2, 0.75
        scored = []
        for bid, doc in self._docs.items():
            brick = self.bricks[bid]
            if discipline and brick.discipline != discipline and brick.category != discipline:
                continue
            length = sum(doc.values())
            score = 0.0
            for t, qw in expanded.items():
                tf = doc.get(t, 0.0)
                if not tf:
                    continue
                score += qw * self._idf.get(t, 0.0) * tf * (k1 + 1) / (tf + k1 * (1 - b + b * length / self._avg))
            if query and query.strip().lower().replace(" ", "_") == bid:
                score += 10.0
            if score > 0 or (not q and discipline):
                scored.append((brick, round(score, 3)))
        scored.sort(key=lambda s: (-s[1], s[0].id))
        return scored[:limit]

    def suggest(self, text: str, limit: int = 5) -> list[str]:
        return [b.id for b, _ in self.search(text, limit=limit)]

    def index_text(self) -> str:
        """Every brick id grouped by discipline: small enough for a system prompt (~2k chars)."""
        lines = []
        for disc, bricks in sorted(self.disciplines().items()):
            lines.append(f"  {disc}: " + ", ".join(sorted(b.id for b in bricks)))
        return "\n".join(lines)


def _load_file(path: Path) -> list[Brick]:
    data = json.loads(path.read_text(encoding="utf-8"))
    defaults = {k: v for k, v in data.items() if k != "bricks"} if isinstance(data, dict) else {}
    items = data["bricks"] if isinstance(data, dict) else data
    out = []
    for raw in items:
        merged = {**defaults, **raw}
        try:
            out.append(Brick.model_validate(merged))
        except ValueError as exc:
            raise ValueError(f"{path.name}: brick {raw.get('id')!r}: {exc}") from exc
    return out


@lru_cache(maxsize=1)
def library() -> Library:
    bricks: list[Brick] = []
    for path in sorted(LIBRARY_DIR.glob("*.json")):
        bricks += _load_file(path)
    return Library(bricks)
