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
    "webhook_secret",
    "access_token",
    "api_token",
    "private_key",
    "credentials",
    "credential",
    "authorization",
    "bearer",
    "password",
    "secret",
    "api_key",
    "token",
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


def iter_lovelace_cards(config: dict) -> Iterator[tuple[str, dict]]:
    """Yield every section card and nested card with its stable Lovelace path."""
    seen_card_ids: set[int] = set()
    for view_index, view in enumerate(config.get("views", [])):
        if not isinstance(view, dict):
            continue
        header = view.get("header")
        if isinstance(header, dict) and isinstance(header.get("card"), dict):
            yield from _iter_card_tree(
                header["card"], f"views[{view_index}].header.card", seen_card_ids
            )
        for section_index, section in enumerate(view.get("sections", [])):
            if not isinstance(section, dict):
                continue
            for card_index, card in enumerate(section.get("cards", [])):
                if isinstance(card, dict):
                    path = f"views[{view_index}].sections[{section_index}].cards[{card_index}]"
                    yield from _iter_card_tree(card, path, seen_card_ids)


def _iter_card_tree(card: dict, path: str, seen_card_ids: set[int]) -> Iterator[tuple[str, dict]]:
    """Yield a card and its embedded child-card configurations exactly once."""
    card_id = id(card)
    if card_id in seen_card_ids:
        return
    seen_card_ids.add(card_id)
    yield path, card
    nested_cards = card.get("cards", [])
    if isinstance(nested_cards, list):
        for card_index, nested_card in enumerate(nested_cards):
            if isinstance(nested_card, dict):
                yield from _iter_card_tree(nested_card, f"{path}.cards[{card_index}]", seen_card_ids)
    singular_card = card.get("card")
    if isinstance(singular_card, dict):
        yield from _iter_card_tree(singular_card, f"{path}.card", seen_card_ids)
    custom_fields = card.get("custom_fields", {})
    if not isinstance(custom_fields, dict):
        return
    for field_name, field_config in custom_fields.items():
        if not isinstance(field_config, dict):
            continue
        embedded_card = field_config.get("card")
        if isinstance(embedded_card, dict):
            embedded_path = f"{path}.custom_fields.{field_name}.card"
            yield from _iter_card_tree(embedded_card, embedded_path, seen_card_ids)


def explicit_action_records(config: dict) -> list[dict]:
    """Collect every top-level action mapping on every recursive Lovelace card."""
    records: list[dict] = []
    for path, card in iter_lovelace_cards(config):
        for channel, action_config in card.items():
            if not channel.endswith("_action") or not isinstance(action_config, dict):
                continue
            target = action_config.get("target")
            target = target if isinstance(target, dict) else {}
            records.append(
                {
                    "path": path,
                    "channel": channel,
                    "action": action_config.get("action"),
                    "perform_action": action_config.get("perform_action"),
                    "service": action_config.get("service"),
                    "target_entity_id": target.get("entity_id"),
                    "target_device_id": target.get("device_id"),
                    "target_area_id": target.get("area_id"),
                    "navigation_path": action_config.get("navigation_path"),
                    "has_confirmation": "confirmation" in action_config,
                }
            )
    return records


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
        if action == "none":
            continue
        if action in {"more-info", "toggle", "perform-action"}:
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
            marker = _credential_marker(key)
            if marker:
                violations.append(f"credential marker {marker!r} found in key {key!r}")
    for scalar in _scalar_values(config):
        marker = _credential_marker(scalar)
        if marker:
            violations.append(f"credential marker {marker!r} found in string {scalar!r}")
    return violations


def _credential_marker(value: str) -> str | None:
    normalized_value = "".join(character for character in value.casefold() if character.isalnum())
    for marker in CREDENTIAL_MARKERS:
        normalized_marker = "".join(
            character for character in marker.casefold() if character.isalnum()
        )
        if normalized_marker in normalized_value:
            return marker
    return None


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
