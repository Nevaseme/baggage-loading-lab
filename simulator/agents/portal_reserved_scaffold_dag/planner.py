"""Mode-A scaffold construction and bounded portal-aware repair."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import math
import time
from typing import Any, Iterable, Mapping, Sequence

from .portal import PortalEdge, build_portal_edges, portal_capacity
from .scaffold import ScaffoldSlot, build_scaffold_slots


_ORIENTATION_PERMS = (
    (0, 1, 2),
    (0, 2, 1),
    (2, 1, 0),
    (1, 0, 2),
    (1, 2, 0),
    (2, 0, 1),
)
_EPS = 1.0e-9
_BEAM_WIDTH = 6


def _float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return float(default)
    return result if math.isfinite(result) else float(default)


def _dimensions(item: Mapping[str, Any], orientation: int = 0) -> tuple[float, float, float]:
    raw = (
        max(0.0, _float(item.get("length"))),
        max(0.0, _float(item.get("width"))),
        max(0.0, _float(item.get("height"))),
    )
    permutation = _ORIENTATION_PERMS[int(orientation) % len(_ORIENTATION_PERMS)]
    return tuple(raw[index] for index in permutation)


def _item_id(item: Mapping[str, Any], ordinal: int) -> Any:
    value = item.get("index", ordinal)
    try:
        return int(value)
    except (TypeError, ValueError):
        return str(value)


def _item_mass(item: Mapping[str, Any]) -> float:
    return max(0.0, _float(item.get("mass"), 1.0))


def _item_volume(item: Mapping[str, Any], orientation: int = 0) -> float:
    dimensions = _dimensions(item, orientation)
    return dimensions[0] * dimensions[1] * dimensions[2]


def _deadline_reached(deadline: Any) -> bool:
    if deadline is None:
        return False
    if hasattr(deadline, "expired") and callable(deadline.expired):
        try:
            return bool(deadline.expired())
        except Exception:
            return True
    try:
        value = float(deadline)
    except (TypeError, ValueError):
        return True
    return not math.isfinite(value) or time.perf_counter() >= value


def _canonical(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _canonical(value[key]) for key in sorted(value, key=lambda key: str(key))}
    if isinstance(value, (tuple, list)):
        return [_canonical(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_canonical(item) for item in value), key=lambda item: repr(item))
    if hasattr(value, "tolist") and callable(value.tolist):
        try:
            return _canonical(value.tolist())
        except Exception:
            pass
    if isinstance(value, float):
        if math.isnan(value):
            return "NaN"
        if math.isinf(value):
            return "Infinity" if value > 0 else "-Infinity"
        return float(value)
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    return repr(value)


def _digest(value: Any) -> str:
    payload = json.dumps(_canonical(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _rect_width(rect: Sequence[float]) -> float:
    return max(0.0, _float(rect[1]) - _float(rect[0]))


def _rect_depth(rect: Sequence[float]) -> float:
    return max(0.0, _float(rect[3]) - _float(rect[2]))


def _candidate_center(
    slot: ScaffoldSlot,
    dimensions: Sequence[float],
    item: Mapping[str, Any],
    container: Mapping[str, Any],
) -> tuple[float, float, float]:
    rect = slot.support_rect
    half_x, half_y, half_z = (0.5 * _float(value) for value in dimensions[:3])
    preferred = item.get("preferred_position", item.get("place_pos", item.get("position")))
    if isinstance(preferred, Sequence) and not isinstance(preferred, (str, bytes)) and len(preferred) >= 3:
        x, y = _float(preferred[0]), _float(preferred[1])
    else:
        x = (rect[0] + rect[1]) * 0.5
        # Keep floor/scaffold placements deep by default, preserving a usable
        # entrance-side sweep for future items.
        y = rect[3] - half_y
    x = min(max(x, rect[0] + half_x), rect[1] - half_x)
    y = min(max(y, rect[2] + half_y), rect[3] - half_y)
    gap = 0.008
    if slot.kind == "shelf":
        gap = 0.018
    elif slot.kind == "item_top":
        gap = 0.006
    z = slot.support_height + gap + half_z
    # Use a provided preferred Z only when it is physically above the support;
    # planned coordinates are still proposal-side and are checked again online.
    if isinstance(preferred, Sequence) and not isinstance(preferred, (str, bytes)) and len(preferred) >= 3:
        preferred_z = _float(preferred[2], z)
        if preferred_z >= slot.support_height + half_z:
            z = preferred_z
    del container
    return (float(x), float(y), float(z))


def _protection_compatible(slot: ScaffoldSlot, item: Mapping[str, Any]) -> bool:
    if "soft" in slot.protection_tags and not bool(item.get("is_soft", False)):
        return False
    if "priority" in slot.protection_tags and not bool(item.get("is_prioritized", False)):
        return False
    return True


def _aabb(center: Sequence[float], dimensions: Sequence[float]) -> tuple[float, float, float, float, float, float]:
    half = tuple(0.5 * _float(value) for value in dimensions[:3])
    return (
        _float(center[0]) - half[0], _float(center[0]) + half[0],
        _float(center[1]) - half[1], _float(center[1]) + half[1],
        _float(center[2]) - half[2], _float(center[2]) + half[2],
    )


def _aabb_overlap(first: Sequence[float], second: Sequence[float], margin: float = 0.001) -> bool:
    return not (
        first[1] <= second[0] + margin or second[1] <= first[0] + margin
        or first[3] <= second[2] + margin or second[3] <= first[2] + margin
        or first[5] <= second[4] + margin or second[5] <= first[4] + margin
    )


def _slot_sort_key(slot: ScaffoldSlot, item: Mapping[str, Any], prioritized_container: bool) -> tuple[Any, ...]:
    item_priority = bool(item.get("is_prioritized", False))
    slot_priority = "priority" in slot.protection_tags
    compatible = _protection_compatible(slot, item)
    # A priority item gets eligible priority containers first; compatible top
    # surfaces precede protected violations for all other items.
    return (
        0 if (item_priority and prioritized_container) else (1 if item_priority else 0),
        0 if compatible else 1,
        0 if slot_priority == item_priority and item_priority else 1,
        0 if slot.kind == "item_top" and compatible else (1 if slot.kind == "floor" else 2),
        -slot.support_height,
        -(slot.support_rect[3]),
        slot.slot_id,
    )


@dataclass(frozen=True)
class SupportEdge:
    """Directed supporter-before-child dependency."""

    before: Any
    after: Any
    slot_id: str = ""
    support_height: float = 0.0
    overlap_area: float = 0.0
    required: bool = True
    reason: str = "support"

    @property
    def source(self) -> Any:
        return self.before

    @property
    def target(self) -> Any:
        return self.after

    @property
    def supporter(self) -> Any:
        return self.before

    @property
    def child(self) -> Any:
        return self.after

    def as_dict(self) -> dict[str, Any]:
        return {
            "before": self.before,
            "after": self.after,
            "slot_id": self.slot_id,
            "support_height": self.support_height,
            "overlap_area": self.overlap_area,
            "required": self.required,
            "reason": self.reason,
        }

    def __getitem__(self, key: str) -> Any:
        return self.as_dict()[key]


@dataclass(frozen=True)
class PlacementIntent:
    """Proposal-side placement target retained in a plan."""

    item_index: Any
    pool_ordinal: int
    container_idx: int
    orientation: int
    position: tuple[float, float, float]
    dimensions: tuple[float, float, float]
    slot_id: str
    route: str = "planned"
    protection_feasible: bool = True
    supporter_index: Any = None

    @property
    def item_idx(self) -> Any:
        return self.item_index

    @property
    def container_index(self) -> int:
        return self.container_idx

    @property
    def place_pos(self) -> tuple[float, float, float]:
        return self.position

    @property
    def node_id(self) -> tuple[Any, int]:
        return (self.item_index, self.pool_ordinal)

    def as_dict(self) -> dict[str, Any]:
        return {
            "item_index": self.item_index,
            "item_idx": self.item_index,
            "pool_ordinal": self.pool_ordinal,
            "container_idx": self.container_idx,
            "orientation": self.orientation,
            "position": self.position,
            "place_pos": self.position,
            "dimensions": self.dimensions,
            "slot_id": self.slot_id,
            "route": self.route,
            "protection_feasible": self.protection_feasible,
            "supporter_index": self.supporter_index,
        }

    def as_action(self) -> dict[str, Any]:
        # Keep this a plain proposal dictionary.  The agent converts it through
        # proposal_from_action and the Task 3 authorizer before formatting.
        return {
            "item_idx": int(self.pool_ordinal),
            "container_idx": int(self.container_idx),
            "place_pos": self.position,
            "orientation": int(self.orientation),
        }

    def __getitem__(self, key: str) -> Any:
        return self.as_dict()[key]


@dataclass(frozen=True)
class Plan:
    """Immutable plan snapshot and its deterministic evidence hashes."""

    placements: tuple[PlacementIntent, ...] = ()
    slots: tuple[ScaffoldSlot, ...] = ()
    support_edges: tuple[SupportEdge, ...] = ()
    portal_edges: tuple[PortalEdge, ...] = ()
    unplaced_indices: tuple[Any, ...] = ()
    partial: bool = False
    deadline_expired: bool = False
    mode: str = "A"
    reservation_enabled: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)
    plan_hash: str = ""
    action_hash: str = ""

    def __post_init__(self) -> None:
        placements = tuple(self.placements)
        slots = tuple(self.slots)
        support_edges = tuple(self.support_edges)
        portal_edges = tuple(self.portal_edges)
        unplaced = tuple(self.unplaced_indices)
        object.__setattr__(self, "placements", placements)
        object.__setattr__(self, "slots", slots)
        object.__setattr__(self, "support_edges", support_edges)
        object.__setattr__(self, "portal_edges", portal_edges)
        object.__setattr__(self, "unplaced_indices", unplaced)
        payload = {
            "placements": [intent.as_dict() for intent in placements],
            "slots": [slot.as_dict() for slot in slots],
            "support_edges": [edge.as_dict() for edge in support_edges],
            "portal_edges": [edge.as_dict() for edge in portal_edges],
            "unplaced_indices": list(unplaced),
            "partial": bool(self.partial),
            "deadline_expired": bool(self.deadline_expired),
            "mode": self.mode,
            "reservation_enabled": bool(self.reservation_enabled),
            "metadata": self.metadata,
        }
        if not self.plan_hash:
            object.__setattr__(self, "plan_hash", _digest(payload))
        if not self.action_hash:
            actions = [intent.as_action() for intent in placements]
            object.__setattr__(self, "action_hash", _digest(actions))

    @property
    def complete(self) -> bool:
        return not self.unplaced_indices and not self.partial and not self.deadline_expired

    @property
    def actions(self) -> tuple[dict[str, Any], ...]:
        return tuple(intent.as_action() for intent in self.placements)

    @property
    def proposals(self) -> tuple[PlacementIntent, ...]:
        return self.placements

    def as_dict(self) -> dict[str, Any]:
        return {
            "placements": self.placements,
            "slots": self.slots,
            "support_edges": self.support_edges,
            "portal_edges": self.portal_edges,
            "unplaced_indices": self.unplaced_indices,
            "partial": self.partial,
            "deadline_expired": self.deadline_expired,
            "complete": self.complete,
            "plan_hash": self.plan_hash,
            "action_hash": self.action_hash,
            "mode": self.mode,
            "reservation_enabled": self.reservation_enabled,
            "metadata": self.metadata,
        }

    def __getitem__(self, key: str) -> Any:
        return self.as_dict()[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.as_dict().get(key, default)

    def __len__(self) -> int:
        return len(self.placements)

    def __iter__(self):
        return iter(self.placements)


@dataclass(frozen=True)
class _BeamState:
    placements: tuple[PlacementIntent, ...]
    used_slots: frozenset[str]
    skipped: tuple[Any, ...]
    protection_count: int
    portal_area: float
    portal_depth: float


def _state_rank(state: _BeamState, items_by_ordinal: Mapping[int, Mapping[str, Any]], containers: Sequence[Mapping[str, Any]]) -> tuple[Any, ...]:
    placed_volume = sum(intent.dimensions[0] * intent.dimensions[1] * intent.dimensions[2] for intent in state.placements)
    cog = sum(_item_mass(items_by_ordinal.get(intent.pool_ordinal, {})) * intent.position[2] for intent in state.placements)
    tie = tuple((-int(intent.item_index) if isinstance(intent.item_index, int) else str(intent.item_index), -intent.pool_ordinal) for intent in state.placements)
    return (
        len(state.placements),
        placed_volume,
        state.protection_count,
        -cog,
        state.portal_area,
        state.portal_depth,
        tuple(reversed(tie)),
    )


def _candidate_intents(
    item: Mapping[str, Any],
    pool_ordinal: int,
    slots: Sequence[ScaffoldSlot],
    containers: Sequence[Mapping[str, Any]],
    existing: Sequence[PlacementIntent],
    used_slots: frozenset[str],
    *,
    route: str = "planned",
) -> list[PlacementIntent]:
    item_index = _item_id(item, pool_ordinal)
    prioritized_available = any(bool(container.get("is_prioritized", False)) for container in containers)
    options: list[PlacementIntent] = []
    slot_order = sorted(
        slots,
        key=lambda slot: _slot_sort_key(slot, item, prioritized_available),
    )
    # Try stable orientations in a compact low-height / broad-footprint order.
    orientations = sorted(
        range(len(_ORIENTATION_PERMS)),
        key=lambda orientation: (
            _dimensions(item, orientation)[2],
            -_dimensions(item, orientation)[0] * _dimensions(item, orientation)[1],
            orientation,
        ),
    )
    for slot in slot_order:
        if slot.slot_id in used_slots and slot.kind == "item_top":
            continue
        container = containers[slot.container_idx]
        if bool(item.get("is_prioritized", False)) and prioritized_available and not bool(container.get("is_prioritized", False)):
            continue
        for orientation in orientations:
            dimensions = _dimensions(item, orientation)
            if dimensions[0] <= _EPS or dimensions[1] <= _EPS or dimensions[2] <= _EPS:
                continue
            if not slot.accepts_footprint(dimensions[0], dimensions[1]):
                continue
            if dimensions[2] + 0.018 > slot.headroom + _EPS:
                continue
            center = _candidate_center(slot, dimensions, item, container)
            candidate_box = _aabb(center, dimensions)
            if any(
                other.container_idx == slot.container_idx
                and _aabb_overlap(candidate_box, _aabb(other.position, other.dimensions))
                for other in existing
            ):
                continue
            compatible = _protection_compatible(slot, item)
            options.append(
                PlacementIntent(
                    item_index=item_index,
                    pool_ordinal=pool_ordinal,
                    container_idx=slot.container_idx,
                    orientation=orientation,
                    position=center,
                    dimensions=dimensions,
                    slot_id=slot.slot_id,
                    route=route,
                    protection_feasible=compatible,
                    supporter_index=slot.supporter_index,
                )
            )
            # One orientation per slot is enough for the beam seed; later
            # repair expands alternatives if the authorizer rejects it.
            break
    options.sort(
        key=lambda intent: (
            not intent.protection_feasible,
            -intent.position[1],
            intent.position[2],
            intent.container_idx,
            intent.slot_id,
            intent.orientation,
        )
    )
    return options[:8]


def _support_edges(placements: Sequence[PlacementIntent]) -> tuple[SupportEdge, ...]:
    edges: list[SupportEdge] = []
    for intent in placements:
        if intent.supporter_index is None:
            continue
        edges.append(
            SupportEdge(
                before=intent.supporter_index,
                after=intent.item_index,
                slot_id=intent.slot_id,
                support_height=intent.position[2] - intent.dimensions[2] * 0.5,
            )
        )
    return tuple(sorted(edges, key=lambda edge: (str(edge.before), str(edge.after), edge.slot_id)))


def _topological_order(placements: Sequence[PlacementIntent], edges: Sequence[PortalEdge | SupportEdge]) -> tuple[PlacementIntent, ...]:
    by_id = {intent.item_index: intent for intent in placements}
    order = {intent.item_index: index for index, intent in enumerate(placements)}
    incoming: dict[Any, set[Any]] = {intent.item_index: set() for intent in placements}
    outgoing: dict[Any, set[Any]] = {intent.item_index: set() for intent in placements}
    for edge in edges:
        if edge.before in incoming and edge.after in incoming and edge.before != edge.after:
            incoming[edge.after].add(edge.before)
            outgoing[edge.before].add(edge.after)
    ready = sorted((identifier for identifier, dependencies in incoming.items() if not dependencies), key=lambda identifier: order[identifier])
    resolved: list[Any] = []
    while ready:
        current = ready.pop(0)
        resolved.append(current)
        for successor in sorted(outgoing[current], key=lambda identifier: order[identifier]):
            incoming[successor].discard(current)
            if not incoming[successor] and successor not in resolved and successor not in ready:
                ready.append(successor)
        ready.sort(key=lambda identifier: order[identifier])
    # Cycles can arise from mutually intersecting broad sweeps.  Keep the
    # deterministic input order for the unresolved suffix rather than dropping
    # a valid partial child.
    resolved.extend(identifier for identifier in (intent.item_index for intent in placements) if identifier not in resolved)
    return tuple(by_id[identifier] for identifier in resolved)


def _plan_from_state(
    state: _BeamState,
    slots: Sequence[ScaffoldSlot],
    items: Sequence[Mapping[str, Any]],
    containers: Sequence[Mapping[str, Any]],
    *,
    unplaced: Sequence[Any],
    partial: bool,
    deadline_expired: bool,
    reservation_enabled: bool = True,
    route: str = "planned",
) -> Plan:
    del route
    placements = tuple(state.placements)
    portal_edges = tuple(build_portal_edges([intent.as_dict() for intent in placements], containers))
    support_edges = _support_edges(placements)
    ordered = _topological_order(placements, tuple(support_edges) + tuple(portal_edges)) if reservation_enabled else placements
    metadata = {
        "rank": _state_rank(state, {ordinal: item for ordinal, item in enumerate(items)}, containers),
        "portal_edge_count": len(portal_edges),
        "support_edge_count": len(support_edges),
    }
    return Plan(
        placements=ordered,
        slots=tuple(slots),
        support_edges=support_edges,
        portal_edges=portal_edges,
        unplaced_indices=tuple(unplaced),
        partial=bool(partial),
        deadline_expired=bool(deadline_expired),
        metadata=metadata,
    )


def build_plan(
    items: Sequence[Mapping[str, Any]],
    containers: Sequence[Mapping[str, Any]],
    deadline: Any = None,
) -> Plan:
    """Build a deterministic Mode-A scaffold plan with bounded beam repair."""
    items = tuple(item for item in (items or ()) if isinstance(item, Mapping))
    containers = tuple(container for container in (containers or ()) if isinstance(container, Mapping))
    slots = tuple(build_scaffold_slots(items, containers))
    if not items or not containers or not slots:
        return Plan(slots=slots, unplaced_indices=tuple(_item_id(item, ordinal) for ordinal, item in enumerate(items)), partial=False)

    # The historical seed's heavy/rigid tendency is retained while priority
    # cargo is surfaced early enough to reserve eligible capacity.
    item_ordinals = sorted(
        range(len(items)),
        key=lambda ordinal: (
            not bool(items[ordinal].get("is_prioritized", False)),
            bool(items[ordinal].get("is_soft", False)),
            -_item_mass(items[ordinal]),
            -_item_volume(items[ordinal]),
            _item_id(items[ordinal], ordinal) if isinstance(_item_id(items[ordinal], ordinal), int) else str(_item_id(items[ordinal], ordinal)),
            ordinal,
        ),
    )
    initial_area = sum(portal_capacity(container)[0] for container in containers)
    initial_depth = sum(portal_capacity(container)[1] for container in containers)
    states = [_BeamState((), frozenset(), (), 0, initial_area, initial_depth)]
    completed_ordinals: set[int] = set()
    deadline_expired = False

    for position, ordinal in enumerate(item_ordinals):
        # Always expand the first item once.  If the deadline expires during a
        # later expansion, the completed child is retained as a partial plan.
        if position > 0 and _deadline_reached(deadline):
            deadline_expired = True
            break
        item = items[ordinal]
        next_states: list[_BeamState] = []
        for state in states:
            candidates = _candidate_intents(
                item,
                ordinal,
                slots,
                containers,
                state.placements,
                state.used_slots,
            )
            for candidate in candidates[:_BEAM_WIDTH]:
                used_slots = set(state.used_slots)
                if candidate.slot_id.startswith("c") and ":item_top:" in candidate.slot_id:
                    used_slots.add(candidate.slot_id)
                container_placements = tuple(
                    intent for intent in state.placements if intent.container_idx == candidate.container_idx
                ) + (candidate,)
                capacity_area, capacity_depth = portal_capacity(containers[candidate.container_idx], container_placements)
                next_states.append(
                    _BeamState(
                        placements=state.placements + (candidate,),
                        used_slots=frozenset(used_slots),
                        skipped=state.skipped,
                        protection_count=state.protection_count + int(candidate.protection_feasible),
                        portal_area=state.portal_area + capacity_area,
                        portal_depth=state.portal_depth + capacity_depth,
                    )
                )
            # A skip child is retained so a blocked item does not discard a
            # higher-count completed branch later in the stream.
            next_states.append(
                _BeamState(
                    placements=state.placements,
                    used_slots=state.used_slots,
                    skipped=state.skipped + (_item_id(item, ordinal),),
                    protection_count=state.protection_count,
                    portal_area=state.portal_area,
                    portal_depth=state.portal_depth,
                )
            )
        if not next_states:
            deadline_expired = _deadline_reached(deadline)
            break
        by_key: dict[tuple[Any, ...], _BeamState] = {}
        item_by_ordinal = {index: value for index, value in enumerate(items)}
        for state in next_states:
            key = _state_rank(state, item_by_ordinal, containers)
            by_key.setdefault(key, state)
        states = sorted(by_key.values(), key=lambda state: _state_rank(state, item_by_ordinal, containers), reverse=True)[:_BEAM_WIDTH]
        completed_ordinals.add(ordinal)

    item_by_ordinal = {index: value for index, value in enumerate(items)}
    best_state = max(states, key=lambda state: _state_rank(state, item_by_ordinal, containers)) if states else _BeamState((), frozenset(), (), 0, initial_area, initial_depth)
    placed_ordinals = {intent.pool_ordinal for intent in best_state.placements}
    unplaced = [
        _item_id(item, ordinal)
        for ordinal, item in enumerate(items)
        if ordinal not in placed_ordinals
    ]
    partial = bool(unplaced) or deadline_expired
    return _plan_from_state(
        best_state,
        slots,
        items,
        containers,
        unplaced=unplaced,
        partial=partial,
        deadline_expired=deadline_expired,
    )


def _plan_items(plan: Plan | Mapping[str, Any]) -> tuple[PlacementIntent, ...]:
    if isinstance(plan, Plan):
        return plan.placements
    values = plan.get("placements", ()) if isinstance(plan, Mapping) else getattr(plan, "placements", ())
    return tuple(value if isinstance(value, PlacementIntent) else PlacementIntent(
        item_index=value.get("item_index", value.get("item_idx")),
        pool_ordinal=int(value.get("pool_ordinal", value.get("item_idx", 0))),
        container_idx=int(value.get("container_idx", value.get("container_index", 0))),
        orientation=int(value.get("orientation", 0)),
        position=tuple(_float(v) for v in value.get("position", value.get("place_pos", (0.0, 0.0, 0.0)))[:3]),
        dimensions=tuple(_float(v) for v in value.get("dimensions", (0.0, 0.0, 0.0))[:3]),
        slot_id=str(value.get("slot_id", "")),
        route=str(value.get("route", "repair")),
    ) for value in values)


def _repair_alternatives(
    item: Mapping[str, Any],
    intent: PlacementIntent,
    slots: Sequence[ScaffoldSlot],
    containers: Sequence[Mapping[str, Any]],
    existing: Sequence[PlacementIntent],
) -> list[PlacementIntent]:
    used_slots = frozenset(existing_intent.slot_id for existing_intent in existing if ":item_top:" in existing_intent.slot_id)
    alternatives = _candidate_intents(item, intent.pool_ordinal, slots, containers, existing, used_slots, route="repair")
    original = PlacementIntent(
        item_index=intent.item_index,
        pool_ordinal=intent.pool_ordinal,
        container_idx=intent.container_idx,
        orientation=intent.orientation,
        position=intent.position,
        dimensions=intent.dimensions,
        slot_id=intent.slot_id,
        route="repair",
        protection_feasible=intent.protection_feasible,
        supporter_index=intent.supporter_index,
    )
    return [original] + [candidate for candidate in alternatives if candidate.position != original.position or candidate.container_idx != original.container_idx]


def repair_plan(observation: Mapping[str, Any], plan: Plan | Mapping[str, Any], deadline: Any = None) -> Plan:
    """Rebind planned intents to a live observation through the Task 3 authorizer."""
    if not isinstance(observation, Mapping):
        return Plan(partial=True, deadline_expired=_deadline_reached(deadline))
    pool = tuple(item for item in observation.get("pool_list", ()) if isinstance(item, Mapping))
    containers = tuple(container for container in observation.get("container_list", ()) if isinstance(container, Mapping))
    slots = tuple(build_scaffold_slots(pool, containers))
    source_intents = _plan_items(plan)
    retained: list[PlacementIntent] = []
    deadline_expired = False
    from .authorizer import authorize_current, proposal_from_action

    for intent in source_intents:
        if _deadline_reached(deadline):
            deadline_expired = True
            break
        if not 0 <= intent.pool_ordinal < len(pool):
            continue
        item = pool[intent.pool_ordinal]
        for candidate in _repair_alternatives(item, intent, slots, containers, retained):
            if _deadline_reached(deadline):
                deadline_expired = True
                break
            try:
                proposal = proposal_from_action(candidate.as_action(), observation, route="repair", source_key=candidate.slot_id)
                result = authorize_current(proposal, observation, deadline=deadline)
            except Exception:
                continue
            if result.accepted:
                retained.append(candidate)
                break
        if deadline_expired:
            break

    retained_ids = {intent.pool_ordinal for intent in retained}
    unplaced = [
        _item_id(item, ordinal)
        for ordinal, item in enumerate(pool)
        if ordinal not in retained_ids
    ]
    state = _BeamState(
        placements=tuple(retained),
        used_slots=frozenset(intent.slot_id for intent in retained if ":item_top:" in intent.slot_id),
        skipped=tuple(unplaced),
        protection_count=sum(int(intent.protection_feasible) for intent in retained),
        portal_area=sum(portal_capacity(container)[0] for container in containers),
        portal_depth=sum(portal_capacity(container)[1] for container in containers),
    )
    return _plan_from_state(
        state,
        slots,
        pool,
        containers,
        unplaced=unplaced,
        partial=bool(unplaced) or deadline_expired,
        deadline_expired=deadline_expired,
        reservation_enabled=True,
        route="repair",
    )


__all__ = [
    "PlacementIntent",
    "Plan",
    "SupportEdge",
    "build_plan",
    "repair_plan",
]
