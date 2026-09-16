"""Deterministic Mode-A order seeds independent of placement search."""

from __future__ import annotations

from typing import Any, Sequence

from .mode_a_types import OfflineOccurrence, _validate_occurrence_sequence
from .model import ItemSpec, _item_signature


def _static_seed_key(item: ItemSpec, occurrence: OfflineOccurrence) -> tuple:
    length, width, height = item.dimensions
    volume = length * width * height
    footprint = max(length * width, length * height, width * height)
    group = 2 if item.is_soft else (1 if item.is_prioritized else 0)
    return (
        group,
        -item.mass,
        -footprint,
        -volume,
        -max(length, width, height),
        item.index,
        occurrence.original_position,
    )


def historical_static_order_seed(
    raw_items: Sequence[dict[str, Any]],
    occurrences: tuple[OfflineOccurrence, ...],
) -> tuple[int, ...]:
    """Return occurrence positions using the historical rigid/heavy seed key.

    The final occurrence-position tie-break is new and solely prevents duplicate
    IDs/signatures from collapsing or depending on object identity.
    """

    if not isinstance(raw_items, Sequence) or isinstance(raw_items, (str, bytes)):
        raise TypeError("raw_items must be an ordered sequence")
    occurrences = _validate_occurrence_sequence(occurrences)
    if len(raw_items) != len(occurrences):
        raise ValueError("raw items and occurrences must have equal length")
    keyed: list[tuple[tuple, int]] = []
    positions: set[int] = set()
    for occurrence in occurrences:
        position = occurrence.original_position
        if position in positions or position >= len(raw_items):
            raise ValueError("occurrence positions must be unique and in range")
        positions.add(position)
        raw = raw_items[position]
        if type(raw) is not dict:
            raise TypeError("each raw item must be an exact dict")
        item = ItemSpec.from_dict(raw)
        if item.index != occurrence.item_index or _item_signature(item) != occurrence.item_signature:
            raise ValueError("occurrence does not match the raw item at its position")
        keyed.append((_static_seed_key(item, occurrence), position))
    return tuple(position for _key, position in sorted(keyed))


__all__ = ["historical_static_order_seed"]
