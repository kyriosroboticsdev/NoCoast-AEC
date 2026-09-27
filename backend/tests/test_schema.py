import json

from core.pipeline import REQUIREMENTS_SCHEMA, STEPS_SCHEMA
from llm.schema import BOUND_KEYS, strict_schema
from schemas.geo import GeoModel


def _walk(node, seen):
    if isinstance(node, dict):
        seen.update(node.keys())
        for v in node.values():
            _walk(v, seen)
    elif isinstance(node, list):
        for v in node:
            _walk(v, seen)


def test_strict_schema_shape():
    for schema in (REQUIREMENTS_SCHEMA, STEPS_SCHEMA):
        s = strict_schema(schema)
        keys = set()
        _walk(s, keys)
        assert "oneOf" not in keys and "discriminator" not in keys and "default" not in keys and "prefixItems" not in keys
        assert "anyOf" in keys
        text = json.dumps(s)
        assert '"additionalProperties": false' in text


def test_anthropic_variant_drops_bounds():
    s = strict_schema(STEPS_SCHEMA, keep_bounds=False)
    keys = set()
    _walk(s, keys)
    assert not (keys & set(BOUND_KEYS)), keys & set(BOUND_KEYS)
    assert "minimum" in json.dumps(strict_schema(GeoModel.model_json_schema()))
