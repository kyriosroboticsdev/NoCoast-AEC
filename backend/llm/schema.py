"""Rewrite Pydantic JSON schemas into the strict subset constrained decoders like.

- every property required (small models skip optional keys otherwise; optional fields are nullable anyway)
- objects closed (`additionalProperties: false`)
- tuples (`prefixItems`) as fixed-length arrays
- `oneOf` → `anyOf`, no `discriminator` (Anthropic's validator rejects the former)
- no `default` / `title` noise
"""

from __future__ import annotations

import copy


BOUND_KEYS = ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf",
              "minLength", "maxLength", "pattern", "minItems", "maxItems", "format")


def strict_schema(schema: dict, keep_bounds: bool = True) -> dict:
    """`keep_bounds=False` also drops value constraints (Anthropic's structured outputs reject them;
    Pydantic still enforces them on our side, so a violation just becomes a repair round)."""
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
        node.pop("discriminator", None)      # Pydantic's tagged-union hint; not JSON-schema-for-decoding
        if "oneOf" in node:                  # discriminated unions are mutually exclusive anyway; anyOf is universally accepted
            node["anyOf"] = node.pop("oneOf")
        if not keep_bounds:
            for k in BOUND_KEYS:
                node.pop(k, None)
        if "prefixItems" in node:  # tuple[float, float] → array of numbers, length 2
            items = node.pop("prefixItems")
            node["items"] = items[0] if all(i == items[0] for i in items) else {"anyOf": items}
            if keep_bounds:
                node.setdefault("minItems", len(items))
                node.setdefault("maxItems", len(items))
        if node.get("type") == "object" and "properties" in node:
            node["additionalProperties"] = False
            node["required"] = list(node["properties"])
        for v in node.values():
            walk(v)

    walk(s)
    return s
