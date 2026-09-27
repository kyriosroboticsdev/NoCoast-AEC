"""Skills: short playbooks on writing and assembling assets, one markdown file each.

A skill file starts with a front-matter block:

    ---
    name: kitchen-layout
    title: Kitchen layout
    tags: kitchen, plumbing
    triggers: kitchen, cooking, island, galley
    bricks: kitchen_counter, kitchen_sink, oven, fridge
    ---

followed by the playbook itself. The model lists skills and reads the ones that fit the
request during the research phase; `match` also picks them for requests up front so a
model that never asks still gets the right playbook.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from bricks.registry import tokens

SKILLS_DIR = Path(__file__).resolve().parent / "library"


@dataclass
class Skill:
    name: str
    title: str
    body: str
    tags: list[str] = field(default_factory=list)
    triggers: list[str] = field(default_factory=list)
    bricks: list[str] = field(default_factory=list)

    def line(self) -> str:
        return f"{self.name} — {self.title} ({', '.join(self.tags)})"

    def text(self) -> str:
        return f"SKILL {self.name}: {self.title}\n{self.body.strip()}"


def _parse(path: Path) -> Skill:
    raw = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", raw, re.DOTALL)
    if not m:
        raise ValueError(f"{path.name}: missing front matter")
    meta: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    def split(key: str) -> list[str]:
        return [s.strip() for s in meta.get(key, "").split(",") if s.strip()]

    if "name" not in meta or "title" not in meta:
        raise ValueError(f"{path.name}: front matter needs name and title")
    return Skill(meta["name"], meta["title"], m.group(2), split("tags"), split("triggers"), split("bricks"))


class SkillBook:
    def __init__(self, skills: list[Skill]):
        self.skills = {s.name: s for s in skills}

    def get(self, name: str) -> Skill | None:
        return self.skills.get((name or "").strip().lower())

    def all(self) -> list[Skill]:
        return sorted(self.skills.values(), key=lambda s: s.name)

    def match(self, text: str, limit: int = 4) -> list[Skill]:
        """Skills whose triggers appear in the text, best first."""
        words = set(tokens(text))
        low = text.lower()
        scored = []
        def hit(trigger: str) -> bool:
            if " " in trigger:
                return trigger in low
            toks = set(tokens(trigger))
            return bool(toks) and toks <= words

        for s in self.skills.values():
            hits = sum(1 for t in s.triggers if hit(t))
            if hits:
                scored.append((hits, s.name, s))
        scored.sort(key=lambda x: (-x[0], x[1]))
        return [s for _, _, s in scored[:limit]]

    def index_text(self) -> str:
        return "\n".join(f"  {s.line()}" for s in self.all())


@lru_cache(maxsize=1)
def skillbook() -> SkillBook:
    return SkillBook([_parse(p) for p in sorted(SKILLS_DIR.glob("*.md"))])
