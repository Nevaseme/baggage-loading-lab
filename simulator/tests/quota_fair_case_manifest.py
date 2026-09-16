"""Literal generated-case manifest used by the Phase-0 diagnostic runner."""

from __future__ import annotations

import copy
import hashlib
import json
import random
from typing import Any, Mapping


# Keep this as a literal tuple.  Do not replace it with a Cartesian product:
# the case numbers are part of the benchmark's reproducibility contract.
FIXED_CASES: tuple[dict[str, Any], ...] = (
    {"lookahead": 1, "containers": 1, "shelf": False, "initial_state": "empty", "attributes": "normal", "item_order": "large-to-small", "density": "early"},
    {"lookahead": 1, "containers": 2, "shelf": True, "initial_state": "preloaded", "attributes": "combined", "item_order": "random", "density": "high"},
    {"lookahead": 3, "containers": 1, "shelf": True, "initial_state": "empty", "attributes": "soft", "item_order": "small-to-large", "density": "middle"},
    {"lookahead": 3, "containers": 2, "shelf": False, "initial_state": "preloaded", "attributes": "priority", "item_order": "repeated", "density": "high"},
    {"lookahead": 10, "containers": 1, "shelf": False, "initial_state": "preloaded", "attributes": "combined", "item_order": "random", "density": "middle"},
    {"lookahead": 10, "containers": 2, "shelf": True, "initial_state": "empty", "attributes": "normal", "item_order": "large-to-small", "density": "high"},
    {"lookahead": 20, "containers": 1, "shelf": True, "initial_state": "preloaded", "attributes": "priority", "item_order": "small-to-large", "density": "high"},
    {"lookahead": 20, "containers": 2, "shelf": False, "initial_state": "empty", "attributes": "soft", "item_order": "repeated", "density": "middle"},
    {"lookahead": 20, "containers": 1, "shelf": False, "initial_state": "empty", "attributes": "combined", "item_order": "large-to-small", "density": "early"},
    {"lookahead": 20, "containers": 2, "shelf": True, "initial_state": "preloaded", "attributes": "normal", "item_order": "random", "density": "high"},
    {"lookahead": 20, "containers": 1, "shelf": True, "initial_state": "preloaded", "attributes": "soft", "item_order": "repeated", "density": "middle"},
    {"lookahead": 20, "containers": 2, "shelf": False, "initial_state": "empty", "attributes": "priority", "item_order": "small-to-large", "density": "high"},
    {"lookahead": 40, "containers": 1, "shelf": False, "initial_state": "preloaded", "attributes": "normal", "item_order": "repeated", "density": "high"},
    {"lookahead": 40, "containers": 2, "shelf": True, "initial_state": "empty", "attributes": "combined", "item_order": "random", "density": "middle"},
    {"lookahead": 40, "containers": 1, "shelf": True, "initial_state": "empty", "attributes": "priority", "item_order": "large-to-small", "density": "high"},
    {"lookahead": 40, "containers": 2, "shelf": False, "initial_state": "preloaded", "attributes": "soft", "item_order": "small-to-large", "density": "early"},
)

EXPECTED_TEMPLATE_COUNT = 16
# Hand-recorded from FIXED_CASES using manifest_hash; changing a tuple requires
# deliberately changing this value and the benchmark evidence.
EXPECTED_MANIFEST_SHA256 = "251d613dcd464f557a209923272c41d83656c0373dd88d18d747364dde213bef"


def build_fixed_manifest() -> tuple[dict[str, Any], ...]:
    return FIXED_CASES


def manifest_hash(cases: Any) -> str:
    payload = json.dumps(tuple(cases), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _template_number(template: Mapping[str, Any]) -> int:
    for number, fixed in enumerate(FIXED_CASES, 1):
        if template is fixed or dict(template) == fixed:
            return number
    return 1


def _source_items(config: Mapping[str, Any]) -> list[dict[str, Any]]:
    return config["item_stream"]["item_list"]


def materialize_case(template: Mapping[str, Any], seed: int, sample_config: Mapping[str, Any]) -> dict[str, Any]:
    """Materialize one deterministic JSON-only case from sample config 001."""
    result = copy.deepcopy(sample_config["001"])
    item_stream = result["item_stream"]
    item_stream["look_ahead"] = int(template["lookahead"])
    containers = result["containers"]["container_list"]
    if int(template["containers"]) == 2:
        second = copy.deepcopy(containers[0])
        second["index"] = 1
        containers.append(second)
        two_container_templates = [fixed for fixed in FIXED_CASES if fixed["containers"] == 2]
        ordinal = next(
            (index for index, fixed in enumerate(two_container_templates) if dict(template) == fixed),
            0,
        )
        designated = ordinal % 2 == 0
        priority_index = (ordinal // 2) % 2
        for container in containers:
            container["is_prioritized"] = designated and container["index"] == priority_index
        result["camera"]["num_containers"] = 2
    else:
        result["camera"]["num_containers"] = 1
    for container in containers:
        container["require_shelf"] = bool(template["shelf"])

    items = copy.deepcopy(_source_items(result))
    attributes = template["attributes"]
    for position, item in enumerate(items):
        item["is_soft"] = bool(attributes in {"soft", "combined"} and position % 3 == 0)
        item["is_prioritized"] = bool(attributes in {"priority", "combined"} and position % 4 == 0)
    order = template["item_order"]
    if order == "large-to-small":
        items.sort(key=lambda item: (float(item["length"]) * float(item["width"]) * float(item["height"]), int(item["index"])), reverse=True)
    elif order == "small-to-large":
        items.sort(key=lambda item: (float(item["length"]) * float(item["width"]) * float(item["height"]), int(item["index"])))
    elif order == "random":
        random.Random(seed).shuffle(items)
    elif order == "repeated":
        if items:
            dimensions = {key: items[0][key] for key in ("length", "width", "height")}
            for item in items:
                item.update(dimensions)
    else:
        raise ValueError(f"unsupported item order: {order}")

    # Warm-up/pose capture is performed by the runner.  Keep a stable empty
    # packed-items field here so materialized inputs are always JSON-only.
    for container in containers:
        container["packed_items"] = copy.deepcopy(container.get("packed_items", []))
    item_stream["item_list"] = items
    return result


def materialized_case_hash(case: Mapping[str, Any]) -> str:
    """Hash one materialized JSON case using canonical JSON serialization."""
    payload = json.dumps(case, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def materialize_case_with_metadata(
    template: Mapping[str, Any], seed: int, sample_config: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    case = materialize_case(template, seed, sample_config)
    warmup_target_steps = {"early": 0, "middle": 8, "high": 16}[str(template["density"])]
    metadata = {
        "initial_state": str(template["initial_state"]),
        "density": str(template["density"]),
        "warmup_target_steps": warmup_target_steps,
        "materialized_sha256": materialized_case_hash(case),
    }
    return case, metadata
