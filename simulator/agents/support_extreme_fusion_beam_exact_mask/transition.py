"""Immutable analytical transitions over strict exact roots.

The transition consumes an existing receipt and creates a cloned child state.
Before cloning it requires independently issued, field-matching evidence from
the exact mask (or an equivalent trusted revalidator).  Proposal-to-root
authority therefore remains outside this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Sequence

import numpy as np

from .geometry import oriented_dimensions
from .mask import ExactMask
from .model import (
    AABB,
    ItemSpec,
    PackingState,
    PlacedItem,
    ValidatedRoot,
    _VALIDATION_TOKEN,
    _item_signature,
)
from .settings import SearchSettings
from .state import state_fingerprint


def _exact_nonnegative_int(value: object, name: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be an exact non-negative int")
    return value


@dataclass(frozen=True)
class SimState:
    """One analytical packing node with occurrence-preserving pool identity."""

    packing: PackingState
    pool: tuple[ItemSpec | dict, ...]
    original_pool_positions: tuple[int, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.packing, PackingState):
            raise TypeError("packing must be a PackingState")
        if type(self.pool) is not tuple:
            raise ValueError("pool must be a tuple")
        converted: list[ItemSpec] = []
        for raw_item in self.pool:
            if isinstance(raw_item, ItemSpec):
                converted.append(raw_item)
            elif isinstance(raw_item, dict):
                converted.append(ItemSpec.from_dict(raw_item))
            else:
                raise TypeError("pool entries must be ItemSpec instances or dictionaries")
        if type(self.original_pool_positions) is not tuple:
            raise ValueError("original_pool_positions must be a tuple")
        positions = tuple(
            _exact_nonnegative_int(value, "original pool position")
            for value in self.original_pool_positions
        )
        if len(converted) != len(positions):
            raise ValueError("pool and original_pool_positions lengths must match")
        if len(set(positions)) != len(positions):
            raise ValueError("original_pool_positions must identify unique occurrences")
        object.__setattr__(self, "pool", tuple(converted))
        object.__setattr__(self, "original_pool_positions", positions)

    @classmethod
    def from_current(
        cls,
        packing: PackingState,
        pool: Sequence[ItemSpec | dict],
    ) -> "SimState":
        values = tuple(pool)
        return cls(packing, values, tuple(range(len(values))))

    @property
    def packing_state(self) -> PackingState:
        return self.packing

    def fingerprint(self, settings: SearchSettings | None = None) -> str:
        profile = (settings or SearchSettings()).profile_digest()
        return state_fingerprint(self.packing, self.pool, profile_digest=profile)


@dataclass(frozen=True)
class SimPlacement:
    """Result of applying one already-authorized root to a simulation node."""

    parent: SimState
    child: SimState
    root: ValidatedRoot
    selected_pool_index: int
    original_pool_position: int
    container_ordinal: int

    @property
    def state(self) -> SimState:
        return self.child

    @property
    def child_state(self) -> SimState:
        return self.child


def apply_root(
    parent: SimState,
    root: ValidatedRoot,
    settings: SearchSettings | None = None,
    *,
    exact_revalidator: ExactMask | Callable[..., Any] | None = None,
    deadline: float | None = None,
) -> SimPlacement:
    """Return a cloned child after verifying every receipt binding.

    No proposal search occurs here.  The receipt must bind the exact current
    state, ordered pool occurrence, item metadata, orientation, container
    ordinal, position, and strict profile, then survive fresh exact
    revalidation before the child is cloned.
    """

    if not isinstance(parent, SimState):
        raise TypeError("parent must be a SimState")
    if not isinstance(root, ValidatedRoot):
        raise TypeError("root must be a ValidatedRoot")
    if root._proof is not _VALIDATION_TOKEN or not root.strict or root.rule_violations != 0:
        raise ValueError("forged or non-strict root")
    profile = settings or SearchSettings()
    profile_digest = profile.profile_digest()
    if root.profile_digest != profile_digest:
        raise ValueError("root profile does not match transition profile")

    proposal = root.proposal
    pool_index = _exact_nonnegative_int(proposal.pool_index, "pool index")
    if pool_index >= len(parent.pool):
        raise ValueError("stale root pool position is no longer present")
    item = parent.pool[pool_index]
    if proposal.item_index != item.index or tuple(root.item_signature) != _item_signature(item):
        raise ValueError("root item does not match the selected pool occurrence")

    ordinal = _exact_nonnegative_int(proposal.container_index, "container ordinal")
    if ordinal >= len(parent.packing.containers):
        raise ValueError("root container ordinal is outside the current state")
    container = parent.packing.containers[ordinal]
    if container.ordinal != ordinal:
        raise ValueError("root container ordinal is not canonical")

    expected_key = (
        proposal.item_index,
        proposal.pool_index,
        proposal.container_index,
        proposal.orientation,
        tuple(round(value, 7) for value in proposal.position),
    )
    if tuple(root.proposal_key) != expected_key:
        raise ValueError("root proposal key does not match its proposal")
    if root.source != proposal.source:
        raise ValueError("root source does not match proposal source")
    if not root.box.axis_aligned:
        raise ValueError("root box alignment does not match an official orientation")
    expected_dimensions = np.asarray(
        oriented_dimensions(item.dimensions, proposal.orientation), dtype=np.float64
    )
    if not np.allclose(
        root.box.dimensions, expected_dimensions, rtol=0.0, atol=1e-8
    ):
        raise ValueError("root box dimensions do not match item orientation")
    if not np.all(np.isfinite(root.box.center)) or not np.allclose(
        root.box.center,
        np.asarray(proposal.position, dtype=np.float64),
        rtol=0.0,
        atol=1e-8,
    ):
        raise ValueError("root box center does not match proposal position")
    current_fingerprint = state_fingerprint(
        parent.packing,
        parent.pool,
        pool_index,
        profile_digest,
    )
    if root.state_fingerprint != current_fingerprint:
        raise ValueError("stale or foreign root state fingerprint")

    if exact_revalidator is None:
        exact_revalidator = ExactMask(profile)
    if isinstance(exact_revalidator, ExactMask):
        if exact_revalidator.profile_digest != profile_digest:
            raise ValueError("exact revalidator profile does not match transition profile")
        verified = exact_revalidator.validate(
            parent.packing,
            parent.pool,
            proposal,
            deadline=deadline,
        )
    elif callable(exact_revalidator):
        verified = exact_revalidator(
            parent.packing,
            parent.pool,
            proposal,
            profile,
        )
    else:
        raise TypeError("exact revalidator must be an ExactMask or callable")
    if not isinstance(verified, ValidatedRoot):
        if verified is None:
            raise ValueError("exact revalidation rejected proposal geometry")
        raise TypeError("exact revalidation must return fresh ValidatedRoot evidence")
    if verified is root:
        raise ValueError("exact revalidation evidence must be freshly issued")
    if (
        verified._proof is not _VALIDATION_TOKEN
        or verified.proposal != root.proposal
        or not np.array_equal(verified.box.minimum, root.box.minimum)
        or not np.array_equal(verified.box.maximum, root.box.maximum)
        or verified.box.axis_aligned != root.box.axis_aligned
        or verified.profile_digest != root.profile_digest
        or verified.state_fingerprint != root.state_fingerprint
        or verified.item_signature != root.item_signature
        or verified.proposal_key != root.proposal_key
        or verified.support_ratio != root.support_ratio
        or verified.min_clearance != root.min_clearance
        or verified.source != root.source
        or verified.rule_violations != 0
        or not verified.strict
    ):
        raise ValueError("fresh exact revalidation evidence does not match supplied root")

    child_packing = parent.packing.clone()
    child_box = AABB(
        root.box.minimum.copy(),
        root.box.maximum.copy(),
        axis_aligned=root.box.axis_aligned,
    )
    child_packing.containers[ordinal].placed.append(PlacedItem(item, child_box))
    child_pool = parent.pool[:pool_index] + parent.pool[pool_index + 1 :]
    child_original_positions = (
        parent.original_pool_positions[:pool_index]
        + parent.original_pool_positions[pool_index + 1 :]
    )
    child = SimState(child_packing, child_pool, child_original_positions)
    return SimPlacement(
        parent=parent,
        child=child,
        root=root,
        selected_pool_index=pool_index,
        original_pool_position=parent.original_pool_positions[pool_index],
        container_ordinal=ordinal,
    )


__all__ = ["SimPlacement", "SimState", "apply_root"]
