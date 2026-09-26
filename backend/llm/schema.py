"""Rewrite Pydantic JSON schemas into the strict subset constrained decoders like.

- every property required (small models skip optional keys otherwise; optional fields are nullable anyway)
- objects closed (`additionalProperties: false`)
- tuples (`prefixItems`) as fixed-length arrays
- no `default` / `title` noise
"""

from __future__ import annotations

import copy


def strict_schema(schema: dict) -> dict:
    s = copy.deepcopy(schema)

    def walk(node):
        if isinstance(node, list):
            for n in node:
                walk(n)
            return
        if not isinstance(node, dict):
            return
        node.pop("default", None)
        node.pop("title", None)
        if "prefixItems" in node:  # tuple[float, float] → array of numbers, length 2
            items = node.pop("prefixItems")
            node["items"] = items[0] if all(i == items[0] for i in items) else {"anyOf": items}
            node.setdefault("minItems", len(items))
            node.setdefault("maxItems", len(items))
        if node.get("type") == "object" and "properties" in node:
            node["additionalProperties"] = False
            node["required"] = list(node["properties"])
        for v in node.values():
            walk(v)

    walk(s)
    return s
