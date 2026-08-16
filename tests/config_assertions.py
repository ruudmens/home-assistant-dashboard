"""Reusable assertions for Home Assistant dashboard configuration tests."""

from pathlib import Path
import re
from collections import Counter
from typing import Any, Iterator

import yaml


ENTITY_ID = re.compile(r"^[a-z_]+\.[a-z0-9_]+$")
ALLOWED_REMOTE_SERVICE_ACTIONS = {"scene.turn_on", "script.turn_on"}
ALLOWED_REMOTE_ACTIONS = {"more-info", "toggle", "perform-action", "navigate"}
CREDENTIAL_MARKERS = (
    "access_token",
    "authorization",
    "bearer",
    "password",
    "secret",
    "api_key",
)


class UniqueKeySafeLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate mapping keys."""


def _construct_unique_mapping(
    loader: UniqueKeySafeLoader, node: yaml.nodes.MappingNode, deep: bool = False
) -> dict:
    loader.flatten_mapping(node)
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate mapping key ({key!r})",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueKeySafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique_mapping
)


def load_config(root: Path, relative_path: str) -> dict:
    """Load a UTF-8 YAML dashboard configuration relative to *root*."""
    with (root / relative_path).open(encoding="utf-8") as config_file:
        return yaml.load(config_file, Loader=UniqueKeySafeLoader)


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


def referenced_entity_counts(config: dict) -> Counter[str]:
    """Count entity references while excluding action and service names."""
    return Counter(_entity_references(config))


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


def security_action_violations(card: dict) -> list[str]:
    """Return top-level security actions that are unsafe or lack confirmation."""
    violations: list[str] = []
    for key, value in card.items():
        if not key.endswith("_action"):
            continue
        if not isinstance(value, dict):
            violations.append(f"{key} action {None!r} is unsupported")
            continue
        action = value.get("action")
        if action in {"more-info", "none"}:
            continue
        if action in {"toggle", "perform-action"}:
            if not value.get("confirmation"):
                violations.append(f"{key} action {action!r} requires confirmation")
            continue
        violations.append(f"{key} action {action!r} is unsupported")
    return violations


def action_contract_violations(config: dict) -> list[str]:
    """Return actions and services outside the Remote dashboard allowlists."""
    violations: list[str] = []
    for node in walk(config):
        if not isinstance(node, dict):
            continue
        if "action" in node and node["action"] not in ALLOWED_REMOTE_ACTIONS:
            violations.append(f"action {node['action']!r} is not allowed")
        for key in ("perform_action", "service"):
            if key in node and node[key] not in ALLOWED_REMOTE_SERVICE_ACTIONS:
                violations.append(f"{key} {node[key]!r} is not allowed")
    return violations


def credential_hygiene_violations(config: dict) -> list[str]:
    """Return credential-like key or scalar markers found anywhere in a config."""
    violations: list[str] = []
    for node in walk(config):
        if not isinstance(node, dict):
            continue
        for key in node:
            if not isinstance(key, str):
                continue
            lowered_key = key.casefold()
            for marker in CREDENTIAL_MARKERS:
                if marker in lowered_key:
                    violations.append(f"credential marker {marker!r} found in key {key!r}")
    for scalar in _scalar_values(config):
        lowered_scalar = scalar.casefold()
        for marker in CREDENTIAL_MARKERS:
            if marker in lowered_scalar:
                violations.append(f"credential marker {marker!r} found in string {scalar!r}")
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
