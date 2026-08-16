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
    """Return entity IDs while excluding action and service names."""
    return set(_entity_references(config))


def _entity_references(value: Any, owning_key: str | None = None) -> Iterator[str]:
    """Yield entity-like scalars except service identifiers in action mappings."""
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _entity_references(child, key)
    elif isinstance(value, list):
        for child in value:
            yield from _entity_references(child, owning_key)
    elif (
        isinstance(value, str)
        and owning_key not in {"perform_action", "service"}
        and ENTITY_ID.fullmatch(value)
    ):
        yield value


def unsafe_status_only_card_violations(card: dict) -> list[str]:
    """Return unsafe action channels or cover references on a status-only card."""
    violations: list[str] = []
    for key, value in card.items():
        if key.endswith("_action"):
            action = value.get("action") if isinstance(value, dict) else None
            if action not in {"more-info", "none"}:
                violations.append(f"{key} action {action!r} is unsafe")
    for scalar in _scalar_values(card):
        if scalar.startswith("cover."):
            violations.append(f"cover reference {scalar!r} is unsafe")
    return violations


def _scalar_values(value: Any) -> Iterator[str]:
    """Yield strings from a nested configuration value."""
    if isinstance(value, dict):
        for child in value.values():
            yield from _scalar_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from _scalar_values(child)
    elif isinstance(value, str):
        yield value


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
