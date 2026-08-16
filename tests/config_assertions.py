"""Reusable assertions for Home Assistant dashboard configuration tests."""

from pathlib import Path
import re
from typing import Any, Iterator

import yaml


ENTITY_ID = re.compile(r"^[a-z_]+\.[a-z0-9_]+$")


def load_config(root: Path, relative_path: str) -> dict:
    """Load a UTF-8 YAML dashboard configuration relative to *root*."""
    with (root / relative_path).open(encoding="utf-8") as config_file:
        return yaml.safe_load(config_file)


def walk(value: Any) -> Iterator[dict | list]:
    """Yield every dictionary and list in a nested configuration value."""
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        yield value
        for child in value:
            yield from walk(child)


def referenced_entities(config: dict) -> set[str]:
    """Return valid entity IDs used under entity and entity_id keys."""
    entities: set[str] = set()
    for node in walk(config):
        if not isinstance(node, dict):
            continue
        for key in ("entity", "entity_id"):
            value = node.get(key)
            values = value if isinstance(value, list) else [value]
            entities.update(
                entity_id
                for entity_id in values
                if isinstance(entity_id, str) and ENTITY_ID.fullmatch(entity_id)
            )
    return entities


def cards_for_entity(config: dict, entity_id: str) -> list[dict]:
    """Return configuration dictionaries whose entity matches *entity_id*."""
    return [
        node
        for node in walk(config)
        if isinstance(node, dict) and node.get("entity") == entity_id
    ]


def assert_sections_view(testcase, config: dict, max_columns: int) -> None:
    """Assert that a config contains one dense sections view of the expected width."""
    views = config.get("views", [])
    testcase.assertEqual(len(views), 1)
    view = views[0]
    testcase.assertEqual(view.get("type"), "sections")
    testcase.assertEqual(view.get("max_columns"), max_columns)
    testcase.assertTrue(view.get("dense_section_placement"))
    testcase.assertTrue(view.get("sections"))
