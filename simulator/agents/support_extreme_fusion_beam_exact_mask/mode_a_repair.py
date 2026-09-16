"""Observation-derived exact repair for a receipt-free Mode-A skeleton.

The component never advances a mutable plan cursor.  It reconstructs the
completed prefix from the settled packing state on every call, freshly applies
catalog roots through the exact mask, and returns one of the original catalog
root objects or ``None``.
"""

from __future__ import annotations

from collections import Counter
import math
import time
from typing import Sequence

from .catalog import RootCatalog, StrictRootScanner
from .geometry import oriented_dimensions
from .layered_proxy import LayeredProxy, ProxyWork, ProxyWorkQuota
from .mask import ExactMask
from .mode_a_types import ModeAPlan, OfflineOccurrence, SkeletonIntent, SupportKind
from .model import AABB, ItemSpec, PackingState, Rect, ValidatedRoot, _item_signature
from .settings import SearchSettings
from .transition import SimPlacement, SimState, apply_root


class ModeAExactSkeletonRepair:
    """Select a current exact root using optional Mode-A skeleton evidence."""

    def __init__(
        self,
        settings: SearchSettings,
        scanner: StrictRootScanner,
        exact_mask: ExactMask,
        *,
        clock=None,
    ) -> None:
        if not isinstance(settings, SearchSettings):
            raise TypeError("settings must be SearchSettings")
        if not isinstance(scanner, StrictRootScanner):
            raise TypeError("scanner must be StrictRootScanner")
        if not isinstance(exact_mask, ExactMask):
            raise TypeError("exact_mask must be ExactMask")
        digest = settings.profile_digest()
        if scanner.settings.profile_digest() != digest:
            raise ValueError("scanner settings profile mismatch")
        if scanner.mask.profile_digest != digest or exact_mask.profile_digest != digest:
            raise ValueError("exact mask profile mismatch")
        self.settings = settings
        self.scanner = scanner
        self.exact_mask = exact_mask
        self.clock = clock or time.perf_counter
        self.proxy = LayeredProxy()

    def choose(
        self,
        state: PackingState,
        current_pool: Sequence[ItemSpec | dict],
        catalog: RootCatalog,
        plan: ModeAPlan | None,
        initial_packed_signatures: Sequence[tuple],
        deadline: float,
    ) -> ValidatedRoot | None:
        """Return an original, freshly applicable current catalog root."""

        if not isinstance(state, PackingState) or not isinstance(catalog, RootCatalog):
            return None
        if self._expired(deadline):
            return None
        try:
            pool = tuple(
                value if isinstance(value, ItemSpec) else ItemSpec.from_dict(value)
                for value in current_pool
            )
            sim = SimState.from_current(state, pool)
        except Exception:
            return None
        if not pool or not catalog.records:
            return None

        evaluated: list[tuple[ValidatedRoot, SimPlacement]] = []
        incumbent: ValidatedRoot | None = None
        for record in catalog.records:
            if self._expired(deadline):
                return incumbent
            root = record.root
            try:
                placement = apply_root(
                    sim,
                    root,
                    self.settings,
                    exact_revalidator=self.exact_mask,
                    deadline=deadline,
                )
            except Exception:
                continue
            if incumbent is None:
                incumbent = root
            evaluated.append((root, placement))
        if not evaluated:
            return None
        if self._expired(deadline):
            return incumbent

        valid_plan = self._valid_plan(plan)
        context = None
        if valid_plan is not None:
            try:
                context = self._derive_context(
                    state, valid_plan, initial_packed_signatures, deadline
                )
            except Exception:
                context = None
        if self._expired(deadline):
            return incumbent
        if context is None or context[0] is None:
            return self._fallback(evaluated, deadline)

        intent, suffix, completed_boxes = context
        matching_pool_indices = tuple(
            index
            for index, item in enumerate(pool)
            if _item_signature(item) == intent.occurrence.item_signature
        )
        # The live observation has no offline occurrence token.  Bind the
        # next duplicate occurrence to the first matching live pool position
        # deterministically; never let two equal signatures alias one cursor.
        matching_pool_indices = matching_pool_indices[:1]
        targeted = tuple(
            value
            for value in evaluated
            if value[0].proposal.pool_index in matching_pool_indices
        )
        if not targeted:
            return self._fallback(evaluated, deadline)
        try:
            target_position = self.rebase_intent_position(
                intent, completed_boxes, valid_plan, deadline
            )
            if self._expired(deadline):
                return incumbent
            immediate = sorted(
                targeted,
                key=lambda value: self._stable_key(value[0]),
            )
            hint_scores = {}
            for root, _placement in immediate:
                if self._expired(deadline):
                    return incumbent
                hint_scores[id(root)] = self._hint_rank(
                    state,
                    root,
                    intent,
                    target_position,
                    completed_boxes,
                    deadline,
                )
            immediate.sort(
                key=lambda value: hint_scores[id(value[0])],
                reverse=True,
            )
        except Exception:
            return incumbent
        top = immediate[:12]
        ranked: list[tuple[tuple, tuple, ValidatedRoot]] = []
        for root, placement in top:
            if self._expired(deadline):
                return incumbent
            try:
                suffix_score = self._suffix_proxy_score(
                    placement, suffix[:8], deadline
                )
            except Exception:
                suffix_score = (0, 0.0)
            if self._expired(deadline):
                return incumbent
            rank = (
                suffix_score[0],
                suffix_score[1],
                *hint_scores[id(root)],
                float(root.support_ratio),
                float(root.min_clearance),
            )
            ranked.append((rank, self._stable_key(root), root))
        if not ranked:
            return incumbent
        ranked.sort(key=lambda value: value[1])
        ranked.sort(key=lambda value: value[0], reverse=True)
        return ranked[0][2]

    def derive_next_intent(
        self,
        state: PackingState,
        plan: ModeAPlan | None,
        initial_packed_signatures: Sequence[tuple],
    ) -> SkeletonIntent | None:
        valid = self._valid_plan(plan)
        if valid is None:
            return None
        try:
            now = float(self.clock())
            context = self._derive_context(
                state,
                valid,
                initial_packed_signatures,
                now + 1.0e9,
            )
        except Exception:
            return None
        return context[0]

    def rebase_intent_position(
        self,
        intent: SkeletonIntent,
        completed_boxes: dict[tuple, tuple],
        plan: ModeAPlan,
        deadline: float | None = None,
    ) -> tuple[float, float, float]:
        target = [float(value) for value in intent.local_position]
        if not intent.supporter_occurrences:
            return tuple(target)
        plan_intents = {
            value.occurrence.stable_key: value for value in plan.skeleton
        }
        shifts = []
        tops = []
        for supporter in intent.supporter_occurrences:
            if deadline is not None and self._expired(deadline):
                raise TimeoutError("repair deadline expired during rebase")
            actual = completed_boxes.get(supporter.stable_key)
            planned = plan_intents.get(supporter.stable_key)
            if actual is None or planned is None:
                continue
            self._validate_settled_support(actual)
            if actual[2] != intent.container_ordinal:
                continue
            center, top = actual[0], actual[1]
            shifts.append(
                (
                    float(center[0]) - planned.local_position[0],
                    float(center[1]) - planned.local_position[1],
                )
            )
            tops.append(float(top))
        if not shifts:
            return tuple(target)
        target[0] += sum(value[0] for value in shifts) / len(shifts)
        target[1] += sum(value[1] for value in shifts) / len(shifts)
        dimensions = oriented_dimensions(
            intent.occurrence.item_signature[1:4], intent.orientation
        )
        target[2] = max(tops) + dimensions[2] * 0.5
        return tuple(target)

    def _derive_context(
        self,
        state: PackingState,
        plan: ModeAPlan,
        initial_packed_signatures: Sequence[tuple],
        deadline: float,
    ) -> tuple[
        SkeletonIntent | None,
        tuple[SkeletonIntent, ...],
        dict[tuple, tuple],
    ]:
        initial = Counter(tuple(value) for value in initial_packed_signatures)
        placed = []
        for container in state.containers:
            if self._expired(deadline):
                raise TimeoutError
            for value in container.placed:
                if self._expired(deadline):
                    raise TimeoutError
                placed.append((
                    _item_signature(value.item),
                    container.ordinal,
                    value.box,
                ))
        remaining_placed = list(placed)
        for signature, count in initial.items():
            for _ in range(count):
                match = None
                for index, value in enumerate(remaining_placed):
                    if self._expired(deadline):
                        raise TimeoutError
                    if value[0] == signature:
                        match = index
                        break
                if match is not None:
                    remaining_placed.pop(match)
        executed = Counter(value[0] for value in remaining_placed)
        occurrences = {
            value.original_position: value for value in plan.occurrences
        }
        intents = {
            value.occurrence.original_position: value for value in plan.skeleton
        }
        completed: list[OfflineOccurrence] = []
        next_intent = None
        suffix = []
        for order_index, position in enumerate(plan.returned_order):
            if self._expired(deadline):
                raise TimeoutError
            occurrence = occurrences[position]
            if executed[occurrence.item_signature] > 0:
                executed[occurrence.item_signature] -= 1
                completed.append(occurrence)
                continue
            next_intent = intents[position]
            suffix = [intents[value] for value in plan.returned_order[order_index + 1 :]]
            break
        completed_boxes = {}
        available = list(remaining_placed)
        for occurrence in completed:
            if self._expired(deadline):
                raise TimeoutError
            match = None
            for index, value in enumerate(available):
                if self._expired(deadline):
                    raise TimeoutError
                if value[0] == occurrence.item_signature:
                    match = index
                    break
            if match is None:
                continue
            _signature, _container, box = available.pop(match)
            completed_boxes[occurrence.stable_key] = (
                tuple(float(value) for value in box.center),
                float(box.maximum[2]),
                int(_container),
                box.footprint,
            )
        return next_intent, tuple(suffix), completed_boxes

    def _suffix_proxy_score(
        self,
        placement: SimPlacement,
        suffix: Sequence[SkeletonIntent],
        deadline: float,
    ) -> tuple[int, float]:
        if not suffix or self._expired(deadline):
            return (0, 0.0)
        proxy_state = self.proxy.from_sim_state(placement.child)
        work = ProxyWork()
        quota = ProxyWorkQuota(
            max_nodes=1,
            max_fit_tests=256,
            max_candidates=64,
            max_rectangles_per_patch=32,
        )
        unused = list(proxy_state.remaining)
        fit_count = 0
        fit_volume = 0.0
        for intent in suffix:
            if self._expired(deadline) or work.quota_exhausted(quota):
                break
            match = next(
                (
                    index
                    for index, occurrence in enumerate(unused)
                    if _item_signature(occurrence.item)
                    == intent.occurrence.item_signature
                ),
                None,
            )
            if match is None:
                continue
            occurrence = unused.pop(match)
            try:
                batch = self.proxy.enumerate_candidates(
                    proxy_state, occurrence.key, work, quota
                )
            except Exception:
                break
            work = batch.work
            if batch.candidates:
                fit_count += 1
                fit_volume += float(
                    intent.occurrence.item_signature[1]
                    * intent.occurrence.item_signature[2]
                    * intent.occurrence.item_signature[3]
                )
        return fit_count, fit_volume

    def _hint_rank(
        self,
        state: PackingState,
        root: ValidatedRoot,
        intent: SkeletonIntent,
        target_position: tuple[float, float, float],
        completed_boxes: dict[tuple, tuple],
        deadline: float,
    ) -> tuple:
        if self._expired(deadline):
            raise TimeoutError
        support_kind = self._root_support_kind(state, root, deadline)
        support_match = support_kind is intent.support_kind
        if intent.support_kind is SupportKind.PROXY_TOP:
            bottom = float(root.box.minimum[2])
            tolerance = self.settings.support_height_tolerance
            support_match = any(
                (
                    (actual := completed_boxes.get(supporter.stable_key))
                    is not None
                    and len(actual) >= 4
                    and actual[2] == root.proposal.container_index
                    and abs(float(actual[1]) - bottom) <= tolerance
                    and actual[3].intersection(root.box.footprint) is not None
                )
                for supporter in intent.supporter_occurrences
            )
        dx = float(root.proposal.position[0]) - target_position[0]
        dy = float(root.proposal.position[1]) - target_position[1]
        dz = float(root.proposal.position[2]) - target_position[2]
        return (
            int(root.proposal.container_index == intent.container_ordinal),
            int(support_match),
            int(root.proposal.orientation == intent.orientation),
            -(dx * dx + dy * dy + dz * dz),
        )

    def _root_support_kind(
        self, state: PackingState, root: ValidatedRoot, deadline: float
    ) -> SupportKind:
        container = state.containers[root.proposal.container_index]
        box = root.box
        bottom = float(box.minimum[2])
        tolerance = self.settings.support_height_tolerance
        for obstacle in container.static_obstacles:
            if self._expired(deadline):
                raise TimeoutError
            gap = bottom - float(obstacle.maximum[2])
            if (
                0.0 <= gap <= self.settings.shelf_drop_gap + tolerance
                and obstacle.footprint.intersection(box.footprint) is not None
            ):
                return SupportKind.SHELF
        for placed in container.placed:
            if self._expired(deadline):
                raise TimeoutError
            if (
                placed.box.axis_aligned
                and abs(float(placed.box.maximum[2]) - bottom) <= tolerance
                and placed.box.footprint.intersection(box.footprint) is not None
            ):
                return SupportKind.PLACED_TOP
        return SupportKind.FLOOR

    def _fallback(
        self,
        evaluated: Sequence[tuple[ValidatedRoot, SimPlacement]],
        deadline: float,
    ) -> ValidatedRoot:
        if self._expired(deadline):
            return evaluated[0][0]
        values = list(evaluated)
        values.sort(key=lambda value: ModeAExactSkeletonRepair._stable_key(value[0]))
        if self._expired(deadline):
            return evaluated[0][0]
        values.sort(
            key=lambda value: (
                float(value[0].support_ratio),
                float(value[0].min_clearance),
                -float(value[0].box.maximum[2]),
            ),
            reverse=True,
        )
        if self._expired(deadline):
            return evaluated[0][0]
        return values[0][0]

    @staticmethod
    def _validate_settled_support(value: object) -> None:
        if type(value) is not tuple or len(value) != 4:
            raise TypeError("settled support must be an exact 4-tuple")
        center, top, container_ordinal, footprint = value
        if type(center) is not tuple or len(center) != 3:
            raise TypeError("settled support center must be an exact float tuple")
        if any(type(component) is not float or not math.isfinite(component) for component in center):
            raise TypeError("settled support center must contain exact finite floats")
        if type(top) is not float or not math.isfinite(top):
            raise TypeError("settled support top must be an exact finite float")
        if type(container_ordinal) is not int or container_ordinal < 0:
            raise TypeError("settled support container must be an exact non-negative int")
        if type(footprint) is not Rect:
            raise TypeError("settled support footprint must be an exact Rect")

    @staticmethod
    def _stable_key(root: ValidatedRoot) -> tuple:
        return tuple(root.proposal_key) + (root.source,)

    @staticmethod
    def _valid_plan(plan: object) -> ModeAPlan | None:
        if type(plan) is not ModeAPlan:
            return None
        try:
            plan.__post_init__()
        except Exception:
            return None
        return plan

    def _expired(self, deadline: float) -> bool:
        try:
            now = float(self.clock())
            target = float(deadline)
        except Exception:
            return True
        return not (math.isfinite(now) and math.isfinite(target)) or now >= target


__all__ = ["ModeAExactSkeletonRepair"]
