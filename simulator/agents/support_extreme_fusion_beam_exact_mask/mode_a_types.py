"""Immutable fail-closed Mode-A occurrence and plan boundaries."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import math
from typing import Any, Sequence

from .model import ItemSpec, _item_signature


MODE_A_PLAN_PROFILE_VERSION = "layered-proxy-order-beam-exact-skeleton-repair-v1"


def _nonnegative_int(value: object, name: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be an exact non-negative int")
    return value


def _finite_float(value: object, name: str, *, nonnegative: bool = False) -> float:
    if type(value) is not float or not math.isfinite(value):
        raise ValueError(f"{name} must be an exact finite float")
    if nonnegative and value < 0.0:
        raise ValueError(f"{name} must be non-negative")
    return value


def _canonical_item_signature(value: object) -> tuple:
    if type(value) is not tuple or len(value) != 8:
        raise TypeError("item_signature must be the canonical immutable 8-tuple")
    index, length, width, height, mass, priority, soft, belongs_to = value
    _nonnegative_int(index, "signature index")
    for name, scalar in (
        ("signature length", length),
        ("signature width", width),
        ("signature height", height),
        ("signature mass", mass),
    ):
        _finite_float(scalar, name, nonnegative=True)
    if min(length, width, height) <= 0.0:
        raise ValueError("signature dimensions must be positive")
    if type(priority) is not bool or type(soft) is not bool:
        raise TypeError("signature protection flags must be exact bools")
    if belongs_to is not None:
        _nonnegative_int(belongs_to, "signature belongs_to")
    return value


@dataclass(frozen=True)
class OfflineOccurrence:
    original_position: int
    item_index: int
    item_signature: tuple
    duplicate_ordinal: int

    def __post_init__(self) -> None:
        _nonnegative_int(self.original_position, "original_position")
        _nonnegative_int(self.item_index, "item_index")
        _nonnegative_int(self.duplicate_ordinal, "duplicate_ordinal")
        signature = _canonical_item_signature(self.item_signature)
        if signature[0] != self.item_index:
            raise ValueError("item_index must match item_signature")

    @property
    def stable_key(self) -> tuple:
        return (
            self.original_position,
            self.item_index,
            self.item_signature,
            self.duplicate_ordinal,
        )


class SupportKind(str, Enum):
    FLOOR = "floor"
    SHELF = "shelf"
    PLACED_TOP = "placed_top"
    PROXY_TOP = "proxy_top"


@dataclass(frozen=True)
class SkeletonIntent:
    occurrence: OfflineOccurrence
    container_ordinal: int
    orientation: int
    local_position: tuple[float, float, float]
    support_kind: SupportKind
    supporter_occurrences: tuple[OfflineOccurrence, ...]
    alternative_count: int
    support_margin: float
    clearance_margin: float

    def __post_init__(self) -> None:
        if type(self.occurrence) is not OfflineOccurrence:
            raise TypeError("occurrence must be an exact OfflineOccurrence")
        _nonnegative_int(self.container_ordinal, "container_ordinal")
        if type(self.orientation) is not int or self.orientation not in range(6):
            raise ValueError("orientation must be an exact int in range(6)")
        if type(self.local_position) is not tuple or len(self.local_position) != 3:
            raise TypeError("local_position must be an exact tuple of three floats")
        for component in self.local_position:
            _finite_float(component, "local_position component")
        if type(self.support_kind) is not SupportKind:
            raise TypeError("support_kind must be an exact SupportKind")
        if type(self.supporter_occurrences) is not tuple:
            raise TypeError("supporter_occurrences must be an exact tuple")
        if any(
            type(value) is not OfflineOccurrence
            for value in self.supporter_occurrences
        ):
            raise TypeError("supporters must be exact OfflineOccurrence values")
        if len({value.stable_key for value in self.supporter_occurrences}) != len(
            self.supporter_occurrences
        ):
            raise ValueError("supporter occurrences must be unique")
        if type(self.alternative_count) is not int or self.alternative_count < 1:
            raise ValueError("alternative_count must be a positive exact int")
        _finite_float(self.support_margin, "support_margin")
        _finite_float(self.clearance_margin, "clearance_margin")

    @property
    def stable_key(self) -> tuple:
        return (
            self.occurrence.stable_key,
            self.container_ordinal,
            self.orientation,
            self.local_position,
            self.support_kind.value,
            tuple(value.stable_key for value in self.supporter_occurrences),
            self.alternative_count,
            self.support_margin,
            self.clearance_margin,
        )


@dataclass(frozen=True)
class ModeAOptimizeTrace:
    nodes: int
    fit_tests: int
    candidates: int
    elapsed_seconds: float
    complete: bool
    fallback_reason: str = ""

    def __post_init__(self) -> None:
        _nonnegative_int(self.nodes, "nodes")
        _nonnegative_int(self.fit_tests, "fit_tests")
        _nonnegative_int(self.candidates, "candidates")
        _finite_float(self.elapsed_seconds, "elapsed_seconds", nonnegative=True)
        if type(self.complete) is not bool:
            raise TypeError("complete must be an exact bool")
        if type(self.fallback_reason) is not str:
            raise TypeError("fallback_reason must be an exact str")
        if self.complete and self.fallback_reason:
            raise ValueError("a complete trace cannot carry a fallback reason")
        if not self.complete and not self.fallback_reason:
            raise ValueError("an incomplete trace requires a fallback reason")


def build_offline_occurrences(raw_items: Sequence[dict[str, Any]]) -> tuple[OfflineOccurrence, ...]:
    if not isinstance(raw_items, Sequence) or isinstance(raw_items, (str, bytes)):
        raise TypeError("raw_items must be an ordered sequence")
    counts: Counter[tuple] = Counter()
    result: list[OfflineOccurrence] = []
    for position, raw in enumerate(raw_items):
        if type(raw) is not dict:
            raise TypeError("each raw item must be an exact dict")
        item = ItemSpec.from_dict(raw)
        signature = _item_signature(item)
        ordinal = counts[signature]
        counts[signature] += 1
        result.append(
            OfflineOccurrence(position, item.index, signature, ordinal)
        )
    return tuple(result)


def _validate_occurrence_sequence(
    occurrences: object,
) -> tuple[OfflineOccurrence, ...]:
    if type(occurrences) is not tuple or any(
        type(value) is not OfflineOccurrence for value in occurrences
    ):
        raise TypeError("occurrences must be an exact tuple of OfflineOccurrence")
    duplicate_counts: Counter[tuple] = Counter()
    for position, occurrence in enumerate(occurrences):
        if occurrence.original_position != position:
            raise ValueError("occurrences must be in canonical dense position order")
        expected_ordinal = duplicate_counts[occurrence.item_signature]
        if occurrence.duplicate_ordinal != expected_ordinal:
            raise ValueError("duplicate ordinal is not canonical for item signature")
        duplicate_counts[occurrence.item_signature] += 1
    return occurrences


def compute_mode_a_plan_digest(
    occurrences: tuple[OfflineOccurrence, ...],
    returned_order: tuple[int, ...],
    skeleton: tuple[SkeletonIntent, ...],
    trace: ModeAOptimizeTrace,
    profile_version: str = MODE_A_PLAN_PROFILE_VERSION,
) -> str:
    _validate_plan_parts(
        occurrences, returned_order, skeleton, trace, profile_version,
        require_complete=True,
    )
    payload = (
        profile_version,
        tuple(value.stable_key for value in occurrences),
        returned_order,
        tuple(value.stable_key for value in skeleton),
    )
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_plan_parts(
    occurrences: object,
    returned_order: object,
    skeleton: object,
    trace: object,
    profile_version: object,
    *,
    require_complete: bool,
) -> None:
    occurrences = _validate_occurrence_sequence(occurrences)
    positions = tuple(value.original_position for value in occurrences)
    if type(returned_order) is not tuple or any(
        type(value) is not int or value < 0 for value in returned_order
    ):
        raise TypeError("returned_order must be an exact tuple of non-negative ints")
    if Counter(returned_order) != Counter(positions):
        raise ValueError("returned_order must contain every occurrence exactly once")
    if type(skeleton) is not tuple or any(
        type(value) is not SkeletonIntent for value in skeleton
    ):
        raise TypeError("skeleton must be an exact tuple of SkeletonIntent")
    if len(skeleton) != len(occurrences):
        raise ValueError("publishable skeleton must cover every occurrence")
    if Counter(value.occurrence.original_position for value in skeleton) != Counter(positions):
        raise ValueError("skeleton occurrences must cover inputs exactly once")
    authoritative = {value.original_position: value for value in occurrences}
    for intent in skeleton:
        expected = authoritative.get(intent.occurrence.original_position)
        if expected is None or intent.occurrence.stable_key != expected.stable_key:
            raise ValueError("skeleton occurrence identity is not authoritative")
        for supporter in intent.supporter_occurrences:
            expected_supporter = authoritative.get(supporter.original_position)
            if (
                expected_supporter is None
                or supporter.stable_key != expected_supporter.stable_key
            ):
                raise ValueError("skeleton supporter identity is not authoritative")
    if type(trace) is not ModeAOptimizeTrace:
        raise TypeError("trace must be an exact ModeAOptimizeTrace")
    if require_complete and (not trace.complete or trace.fallback_reason):
        raise ValueError("only complete non-fallback plans are publishable")
    if type(profile_version) is not str or profile_version != MODE_A_PLAN_PROFILE_VERSION:
        raise ValueError("profile_version must match the current Mode-A profile")


@dataclass(frozen=True)
class ModeAPlan:
    occurrences: tuple[OfflineOccurrence, ...]
    returned_order: tuple[int, ...]
    skeleton: tuple[SkeletonIntent, ...]
    plan_digest: str
    trace: ModeAOptimizeTrace
    profile_version: str = MODE_A_PLAN_PROFILE_VERSION

    def __post_init__(self) -> None:
        _validate_plan_parts(
            self.occurrences,
            self.returned_order,
            self.skeleton,
            self.trace,
            self.profile_version,
            require_complete=True,
        )
        if type(self.plan_digest) is not str or len(self.plan_digest) != 64:
            raise ValueError("plan_digest must be a SHA-256 hex string")
        try:
            int(self.plan_digest, 16)
        except ValueError as error:
            raise ValueError("plan_digest must be hexadecimal") from error
        expected = compute_mode_a_plan_digest(
            self.occurrences,
            self.returned_order,
            self.skeleton,
            self.trace,
            self.profile_version,
        )
        if self.plan_digest != expected:
            raise ValueError("plan_digest does not match canonical plan contents")


def finalize_mode_a_plan(
    occurrences: tuple[OfflineOccurrence, ...],
    returned_order: tuple[int, ...],
    skeleton: tuple[SkeletonIntent, ...],
    trace: ModeAOptimizeTrace,
    profile_version: str = MODE_A_PLAN_PROFILE_VERSION,
) -> tuple[tuple[int, ...], ModeAPlan | None]:
    try:
        original_order = tuple(value.original_position for value in occurrences)
    except Exception:
        return (), None
    try:
        digest = compute_mode_a_plan_digest(
            occurrences, returned_order, skeleton, trace, profile_version
        )
        plan = ModeAPlan(
            occurrences,
            returned_order,
            skeleton,
            digest,
            trace,
            profile_version,
        )
    except Exception:
        return original_order, None
    return returned_order, plan


__all__ = [
    "MODE_A_PLAN_PROFILE_VERSION",
    "ModeAOptimizeTrace",
    "ModeAPlan",
    "OfflineOccurrence",
    "SkeletonIntent",
    "SupportKind",
    "build_offline_occurrences",
    "compute_mode_a_plan_digest",
    "finalize_mode_a_plan",
]
