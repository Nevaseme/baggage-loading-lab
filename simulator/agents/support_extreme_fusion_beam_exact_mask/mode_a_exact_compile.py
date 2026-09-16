"""Strict virtual compiler for complete Mode-A proxy order skeletons.

Exact roots exist only as local transition authority.  They are freshly
revalidated, applied to a cloned analytical state, then discarded before a
receipt-free ModeAPlan is finalized.
"""

from __future__ import annotations

import math
import time
from typing import Any, Sequence

from .catalog import CatalogWorkQuota, StrictRootScanner
from .geometry import oriented_dimensions
from .mask import ExactMask
from .mode_a_order_beam import ProxyOrderCandidate
from .mode_a_types import (
    ModeAOptimizeTrace,
    ModeAPlan,
    OfflineOccurrence,
    SkeletonIntent,
    SupportKind,
    _validate_occurrence_sequence,
    build_offline_occurrences,
    finalize_mode_a_plan,
)
from .model import AABB, ItemSpec, PackingState, PlacementProposal, _item_signature
from .settings import SearchSettings
from .transition import SimState, apply_root


_EPS = 1.0e-12


class _CompileExpired(RuntimeError):
    """Internal cooperative-abort signal; never escapes ``compile``."""


class StrictSkeletonCompiler:
    """Compile a complete proxy skeleton through current-state exact checks."""

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
        profile = settings.profile_digest()
        if scanner.settings.profile_digest() != profile:
            raise ValueError("scanner settings profile mismatch")
        if scanner.mask.profile_digest != profile or exact_mask.profile_digest != profile:
            raise ValueError("strict exact profile mismatch")
        self.settings = settings
        self.scanner = scanner
        self.exact_mask = exact_mask
        self.clock = clock or time.perf_counter

    def compile(
        self,
        initial_state: PackingState,
        raw_items: Sequence[dict[str, Any]],
        occurrences: tuple[OfflineOccurrence, ...],
        candidate: ProxyOrderCandidate,
        deadline: float,
    ) -> ModeAPlan | None:
        started = self._now()
        try:
            if not isinstance(initial_state, PackingState):
                return None
            if not math.isfinite(float(deadline)) or started is None or started >= deadline:
                return None
            self._require_time(deadline)
            occurrences = _validate_occurrence_sequence(occurrences)
            self._require_time(deadline)
            canonical = build_offline_occurrences(raw_items)
            canonical_keys = []
            occurrence_keys = []
            for value in canonical:
                self._require_time(deadline)
                canonical_keys.append(value.stable_key)
            for value in occurrences:
                self._require_time(deadline)
                occurrence_keys.append(value.stable_key)
            if tuple(canonical_keys) != tuple(occurrence_keys):
                return None
            if not self._candidate_is_complete_current(
                candidate, occurrences, deadline
            ):
                return None
            items_list = []
            for value in raw_items:
                self._require_time(deadline)
                items_list.append(ItemSpec.from_dict(value))
            items = tuple(items_list)
            by_position = {}
            for value in occurrences:
                self._require_time(deadline)
                by_position[value.original_position] = value
            source_intents = {}
            for value in candidate.skeleton:
                self._require_time(deadline)
                source_intents[value.occurrence.original_position] = value
            self._require_time(deadline)
            current_packing = initial_state.clone()
            self._require_time(deadline)
            compiled: list[SkeletonIntent] = []
            compiled_boxes: list[tuple[OfflineOccurrence, int, AABB]] = []
            exact_attempts = 0
            strict_candidates = 0

            for step, occurrence in enumerate(candidate.occurrence_order):
                now = self._now()
                if now is None or now >= deadline:
                    return None
                steps_left = len(candidate.occurrence_order) - step
                step_deadline = min(
                    float(deadline), now + max(0.0, float(deadline) - now) / steps_left
                )
                if step_deadline <= now:
                    return None
                item = items[occurrence.original_position]
                if _item_signature(item) != occurrence.item_signature:
                    return None
                singleton = (item,)
                sim = SimState(
                    current_packing,
                    singleton,
                    (occurrence.original_position,),
                )
                planned = source_intents[occurrence.original_position]
                advisory_deadline = now + (step_deadline - now) * 0.35
                roots = []
                for proposal in self._advisory_proposals(
                    current_packing, item, planned, advisory_deadline
                )[:6]:
                    loop_now = self._now()
                    if loop_now is None or loop_now >= advisory_deadline:
                        break
                    exact_attempts += 1
                    root = self.exact_mask.validate(
                        current_packing,
                        singleton,
                        proposal,
                        deadline=advisory_deadline,
                    )
                    if root is not None:
                        roots.append(root)

                scan_now = self._now()
                if scan_now is None or scan_now >= step_deadline:
                    return None
                catalog = self.scanner.scan_coverage_fixed(
                    current_packing,
                    singleton,
                    deadline=step_deadline,
                    quota=CatalogWorkQuota(
                        per_pool_raw_limit=128,
                        global_exact_attempt_cap=64,
                        include_dense=False,
                        include_deferred=False,
                        include_rescue=False,
                    ),
                    allow_deferred=False,
                    allow_rescue=False,
                )
                exact_attempts += int(catalog.stats.exact_attempts)
                roots.extend(record.root for record in catalog.records[:64])
                roots = self._unique_roots(roots, step_deadline)
                strict_candidates += len(roots)
                if not roots:
                    return None
                ordered_roots = self._rank_roots(
                    roots,
                    planned,
                    candidate.skeleton[step + 1 :],
                    step_deadline,
                )
                selected_root = None
                placement = None
                for root in ordered_roots:
                    if self._expired(step_deadline):
                        return None
                    try:
                        current = apply_root(
                            sim,
                            root,
                            self.settings,
                            exact_revalidator=self.exact_mask,
                            deadline=step_deadline,
                        )
                    except Exception:
                        continue
                    selected_root = root
                    placement = current
                    break
                if selected_root is None or placement is None:
                    return None
                self._require_time(step_deadline)
                compiled_intent = self._compiled_intent(
                    occurrence,
                    selected_root,
                    max(1, len(roots)),
                    current_packing,
                    compiled_boxes,
                    by_position,
                    step_deadline,
                )
                compiled.append(compiled_intent)
                compiled_boxes.append(
                    (
                        occurrence,
                        selected_root.proposal.container_index,
                        selected_root.box,
                    )
                )
                current_packing = placement.child.packing
                # selected_root and placement are local authority only.  The
                # next iteration retains geometry/state, never either receipt.

            ended = self._now()
            if ended is None or ended >= deadline or len(compiled) != len(occurrences):
                return None
            trace = ModeAOptimizeTrace(
                nodes=len(compiled),
                fit_tests=exact_attempts,
                candidates=strict_candidates,
                elapsed_seconds=max(0.0, float(ended - started)),
                complete=True,
                fallback_reason="",
            )
            order_values = []
            for value in candidate.occurrence_order:
                self._require_time(deadline)
                order_values.append(value.original_position)
            order = tuple(order_values)
            returned, plan = finalize_mode_a_plan(
                occurrences,
                order,
                tuple(compiled),
                trace,
            )
            self._require_time(deadline)
            if returned != order:
                return None
            return plan
        except Exception:
            return None

    def _candidate_is_complete_current(
        self,
        candidate: object,
        occurrences: tuple[OfflineOccurrence, ...],
        deadline: float,
    ) -> bool:
        self._require_time(deadline)
        if type(candidate) is not ProxyOrderCandidate:
            return False
        try:
            candidate.__post_init__()
        except Exception:
            return False
        self._require_time(deadline)
        if not candidate.complete or candidate.placed_count != len(occurrences):
            return False
        if len(candidate.skeleton) != len(occurrences):
            return False
        authoritative = {}
        for value in occurrences:
            self._require_time(deadline)
            authoritative[value.original_position] = value
        if len(candidate.occurrence_order) != len(occurrences):
            return False
        for occurrence in candidate.occurrence_order:
            self._require_time(deadline)
            expected = authoritative.get(occurrence.original_position)
            if expected is None or occurrence.stable_key != expected.stable_key:
                return False
        for index, intent in enumerate(candidate.skeleton):
            self._require_time(deadline)
            if (
                intent.occurrence.stable_key
                != candidate.occurrence_order[index].stable_key
            ):
                return False
        return True

    def _advisory_proposals(
        self,
        state: PackingState,
        item: ItemSpec,
        intent: SkeletonIntent,
        deadline: float,
    ) -> tuple[PlacementProposal, ...]:
        self._require_time(deadline)
        if intent.container_ordinal >= len(state.containers):
            return ()
        container = state.containers[intent.container_ordinal]
        dimensions = oriented_dimensions(item.dimensions, intent.orientation)
        x, y, planned_z = intent.local_position
        centers = [planned_z]
        centers.append(container.thickness + container.buffer + 0.008 + dimensions[2] * 0.5)
        for obstacle in container.static_obstacles:
            self._require_time(deadline)
            centers.append(
                float(obstacle.maximum[2]) + 0.022 + dimensions[2] * 0.5
            )
        for placed in container.placed:
            self._require_time(deadline)
            centers.append(float(placed.box.maximum[2]) + dimensions[2] * 0.5)
        result: list[PlacementProposal] = []
        seen: set[tuple] = set()
        for ordinal, z in enumerate(centers):
            self._require_time(deadline)
            if not math.isfinite(z):
                continue
            key = (
                item.index,
                0,
                intent.container_ordinal,
                intent.orientation,
                round(x, 8),
                round(y, 8),
                round(z, 8),
            )
            if key in seen:
                continue
            seen.add(key)
            result.append(
                PlacementProposal(
                    item_index=item.index,
                    pool_index=0,
                    container_index=intent.container_ordinal,
                    orientation=intent.orientation,
                    position=(x, y, float(z)),
                    source=f"mode_a_advisory_{ordinal}",
                )
            )
            if len(result) >= 6:
                break
        self._require_time(deadline)
        return tuple(result)

    def _unique_roots(
        self, roots: Sequence[object], deadline: float
    ) -> list:
        result = []
        seen: set[tuple] = set()
        for root in roots:
            self._require_time(deadline)
            try:
                key = tuple(root.proposal_key)
            except Exception:
                continue
            if key in seen:
                continue
            seen.add(key)
            result.append(root)
        return result

    def _rank_roots(
        self,
        roots: Sequence[object],
        intent: SkeletonIntent,
        suffix: Sequence[SkeletonIntent],
        deadline: float,
    ) -> tuple:
        suffix_min_alternatives = 1
        suffix_support = 1.0
        suffix_clearance = 1.0
        if suffix:
            suffix_min_alternatives = suffix[0].alternative_count
            suffix_support = suffix[0].support_margin
            suffix_clearance = suffix[0].clearance_margin
            for value in suffix:
                self._require_time(deadline)
                suffix_min_alternatives = min(
                    suffix_min_alternatives, value.alternative_count
                )
                suffix_support = min(suffix_support, value.support_margin)
                suffix_clearance = min(
                    suffix_clearance, value.clearance_margin
                )
        ranked = []
        for root in roots:
            self._require_time(deadline)
            distance = 0.0
            for a, b in zip(root.proposal.position, intent.local_position):
                self._require_time(deadline)
                distance += (float(a) - float(b)) ** 2
            ranked.append(
                (
                    (
                        -distance,
                        len(suffix),
                        suffix_min_alternatives,
                        suffix_support,
                        suffix_clearance,
                        float(root.support_ratio),
                        float(root.min_clearance),
                    ),
                    tuple(root.proposal_key),
                    root,
                )
            )
        self._require_time(deadline)
        ranked.sort(key=lambda value: value[1])
        ranked.sort(key=lambda value: value[0], reverse=True)
        self._require_time(deadline)
        return tuple(value[2] for value in ranked)

    def _compiled_intent(
        self,
        occurrence: OfflineOccurrence,
        root: object,
        alternatives: int,
        state: PackingState,
        compiled_boxes: Sequence[tuple[OfflineOccurrence, int, AABB]],
        authoritative: dict[int, OfflineOccurrence],
        deadline: float,
    ) -> SkeletonIntent:
        self._require_time(deadline)
        box = root.box
        container_ordinal = root.proposal.container_index
        supporters_list = []
        for value, lower_container_ordinal, lower in compiled_boxes:
            self._require_time(deadline)
            if (
                lower_container_ordinal == container_ordinal
                and lower.axis_aligned
                and abs(float(lower.maximum[2]) - float(box.minimum[2]))
                <= self.settings.support_height_tolerance
                and lower.footprint.intersection(box.footprint) is not None
            ):
                supporters_list.append(value)
        supporters = tuple(supporters_list)
        if supporters:
            kind = SupportKind.PROXY_TOP
        else:
            container = state.containers[container_ordinal]
            bottom = float(box.minimum[2])
            tolerance = self.settings.support_height_tolerance
            shelf = False
            for obstacle in container.static_obstacles:
                self._require_time(deadline)
                gap = bottom - float(obstacle.maximum[2])
                if (
                    0.0 <= gap <= self.settings.shelf_drop_gap + tolerance
                    and obstacle.footprint.intersection(box.footprint) is not None
                ):
                    shelf = True
                    break
            placed = False
            if not shelf:
                for value in container.placed:
                    self._require_time(deadline)
                    if (
                        value.box.axis_aligned
                        and abs(float(value.box.maximum[2]) - bottom) <= tolerance
                        and value.box.footprint.intersection(box.footprint) is not None
                    ):
                        placed = True
                        break
            kind = (
                SupportKind.SHELF
                if shelf
                else SupportKind.PLACED_TOP
                if placed
                else SupportKind.FLOOR
            )
        canonical_supporters_list = []
        for value in supporters:
            self._require_time(deadline)
            canonical_supporters_list.append(
                authoritative[value.original_position]
            )
        canonical_supporters = tuple(canonical_supporters_list)
        self._require_time(deadline)
        intent = SkeletonIntent(
            occurrence=authoritative[occurrence.original_position],
            container_ordinal=root.proposal.container_index,
            orientation=root.proposal.orientation,
            local_position=tuple(float(value) for value in root.proposal.position),
            support_kind=kind,
            supporter_occurrences=canonical_supporters,
            alternative_count=alternatives,
            support_margin=float(root.support_ratio),
            clearance_margin=float(root.min_clearance),
        )
        self._require_time(deadline)
        return intent

    def _now(self) -> float | None:
        try:
            value = float(self.clock())
        except Exception:
            return None
        return value if math.isfinite(value) else None

    def _expired(self, deadline: float) -> bool:
        now = self._now()
        return now is None or now >= deadline

    def _require_time(self, deadline: float) -> None:
        if self._expired(deadline):
            raise _CompileExpired("compile deadline expired")


__all__ = ["StrictSkeletonCompiler"]
