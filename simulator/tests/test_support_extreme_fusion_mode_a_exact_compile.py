from __future__ import annotations

import dataclasses
import pathlib
import sys
import time
from types import SimpleNamespace
import unittest

import numpy as np


SIMULATOR_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(SIMULATOR_ROOT) not in sys.path:
    sys.path.insert(0, str(SIMULATOR_ROOT))

from agents.support_extreme_fusion_beam_exact_mask.catalog import (  # noqa: E402
    CatalogWorkQuota,
    RootCatalog,
    StrictRootScanner,
)
from agents.support_extreme_fusion_beam_exact_mask.mask import ExactMask  # noqa: E402
from agents.support_extreme_fusion_beam_exact_mask.mode_a_exact_compile import (  # noqa: E402
    StrictSkeletonCompiler,
)
from agents.support_extreme_fusion_beam_exact_mask.mode_a_order_beam import (  # noqa: E402
    LayeredProxyOrderBeam,
    ProxyOrderCandidate,
)
from agents.support_extreme_fusion_beam_exact_mask.mode_a_types import (  # noqa: E402
    ModeAPlan,
    SkeletonIntent,
    SupportKind,
    build_offline_occurrences,
    compute_mode_a_plan_digest,
)
from agents.support_extreme_fusion_beam_exact_mask.model import (  # noqa: E402
    AABB,
    ItemSpec,
    PlacedItem,
    PlacementProposal,
)
from agents.support_extreme_fusion_beam_exact_mask.settings import SearchSettings  # noqa: E402
from agents.support_extreme_fusion_beam_exact_mask.state import build_packing_state  # noqa: E402
from tests.test_support_extreme_fusion_layered_proxy import (  # noqa: E402
    _container,
    _raw_item,
)


def _candidate_case(raw):
    packing = build_packing_state([_container(shelf=True)])
    occurrences = build_offline_occurrences(raw)
    candidate = LayeredProxyOrderBeam(clock=lambda: 0.0).search(
        packing, occurrences, raw, 100.0
    )[0]
    if not candidate.complete:
        raise AssertionError("fixture failed to create a complete proxy candidate")
    return packing, occurrences, candidate


def _compiler(*, mask=None, scanner=None, clock=None):
    settings = SearchSettings()
    mask = mask or ExactMask(settings)
    scanner = scanner or StrictRootScanner(settings, mask=mask, clock=clock)
    return StrictSkeletonCompiler(
        settings,
        scanner,
        mask,
        clock=clock or time.perf_counter,
    )


def _assert_receipt_free(test, value):
    seen = set()

    def visit(current):
        if id(current) in seen:
            return
        seen.add(id(current))
        test.assertNotIn(type(current).__name__, {"ValidatedRoot", "PlacementProposal"})
        test.assertFalse(isinstance(current, dict))
        if dataclasses.is_dataclass(current):
            for field in dataclasses.fields(current):
                visit(getattr(current, field.name))
        elif isinstance(current, tuple):
            for item in current:
                visit(item)

    visit(value)


class StrictSkeletonCompilerTests(unittest.TestCase):
    def test_small_real_integration_compiles_all_and_digest_recomputes(self):
        raw = (
            _raw_item(0, length=0.18, width=0.16, height=0.12),
            _raw_item(1, length=0.20, width=0.14, height=0.10),
            _raw_item(2, length=0.12, width=0.12, height=0.12, soft=True),
        )
        packing, occurrences, candidate = _candidate_case(raw)
        plan = _compiler().compile(
            packing, raw, occurrences, candidate, time.perf_counter() + 30.0
        )

        self.assertIsInstance(plan, ModeAPlan)
        self.assertEqual(len(plan.skeleton), 3)
        self.assertEqual(plan.returned_order, tuple(
            value.original_position for value in candidate.occurrence_order
        ))
        self.assertEqual(
            plan.plan_digest,
            compute_mode_a_plan_digest(
                plan.occurrences,
                plan.returned_order,
                plan.skeleton,
                plan.trace,
                plan.profile_version,
            ),
        )
        _assert_receipt_free(self, plan)

    def test_duplicate_occurrences_are_compiled_as_singletons_in_order(self):
        raw = (_raw_item(4), _raw_item(4))
        packing, occurrences, candidate = _candidate_case(raw)

        class RecordingScanner(StrictRootScanner):
            def __init__(self, settings, mask):
                super().__init__(settings, mask=mask)
                self.pools = []

            def scan_coverage_fixed(self, state, pool, **kwargs):
                self.pools.append(tuple(pool))
                return super().scan_coverage_fixed(state, pool, **kwargs)

        settings = SearchSettings()
        mask = ExactMask(settings)
        scanner = RecordingScanner(settings, mask)
        plan = StrictSkeletonCompiler(settings, scanner, mask).compile(
            packing, raw, occurrences, candidate, time.perf_counter() + 30.0
        )

        self.assertIsNotNone(plan)
        self.assertEqual(len(scanner.pools), 2)
        self.assertTrue(all(len(pool) == 1 for pool in scanner.pools))
        self.assertEqual(
            tuple(pool[0].index for pool in scanner.pools),
            tuple(value.item_index for value in candidate.occurrence_order),
        )

    def test_each_later_scan_observes_the_freshly_applied_child_state(self):
        raw = (_raw_item(0), _raw_item(1))
        packing, occurrences, candidate = _candidate_case(raw)

        class RecordingScanner(StrictRootScanner):
            def __init__(self, settings, mask):
                super().__init__(settings, mask=mask)
                self.placed_counts = []

            def scan_coverage_fixed(self, state, pool, **kwargs):
                self.placed_counts.append(sum(
                    len(container.placed) for container in state.containers
                ))
                return super().scan_coverage_fixed(state, pool, **kwargs)

        settings = SearchSettings()
        mask = ExactMask(settings)
        scanner = RecordingScanner(settings, mask)
        plan = StrictSkeletonCompiler(settings, scanner, mask).compile(
            packing, raw, occurrences, candidate, time.perf_counter() + 30.0
        )

        self.assertIsNotNone(plan)
        self.assertEqual(scanner.placed_counts, [0, 1])

    def test_rejected_advisory_is_repaired_by_normal_scanner(self):
        raw = (_raw_item(0),)
        packing, occurrences, candidate = _candidate_case(raw)
        intent = dataclasses.replace(
            candidate.skeleton[0], local_position=(99.0, 99.0, 99.0)
        )
        forged_advisory = dataclasses.replace(candidate, skeleton=(intent,))
        plan = _compiler().compile(
            packing,
            raw,
            occurrences,
            forged_advisory,
            time.perf_counter() + 30.0,
        )

        self.assertIsNotNone(plan)
        self.assertNotEqual(plan.skeleton[0].local_position, intent.local_position)

    def test_planned_support_z_is_rebased_before_strict_validation(self):
        raw = (_raw_item(0),)
        packing, occurrences, candidate = _candidate_case(raw)
        original = candidate.skeleton[0]
        wrong = dataclasses.replace(
            original,
            local_position=(
                original.local_position[0],
                original.local_position[1],
                original.local_position[2] + 0.25,
            ),
        )
        plan = _compiler().compile(
            packing,
            raw,
            occurrences,
            dataclasses.replace(candidate, skeleton=(wrong,)),
            time.perf_counter() + 30.0,
        )

        self.assertIsNotNone(plan)
        self.assertLess(plan.skeleton[0].local_position[2], wrong.local_position[2])

    def test_scanner_uses_singleton_fixed_cap_64_and_advisory_cap_6(self):
        raw = (_raw_item(0),)
        packing, occurrences, candidate = _candidate_case(raw)

        class RecordingMask(ExactMask):
            def __init__(self, settings):
                super().__init__(settings)
                self.advisory = 0

            def validate(self, state, pool, proposal, **kwargs):
                if proposal.source.startswith("mode_a_advisory"):
                    self.advisory += 1
                return super().validate(state, pool, proposal, **kwargs)

        class RecordingScanner(StrictRootScanner):
            def __init__(self, settings, mask):
                super().__init__(settings, mask=mask)
                self.quotas = []
                self.flags = []
                self.exact_attempts = []

            def scan_coverage_fixed(self, state, pool, *, quota, **kwargs):
                self.quotas.append((len(pool), quota))
                self.flags.append(
                    (kwargs.get("allow_deferred"), kwargs.get("allow_rescue"))
                )
                catalog = super().scan_coverage_fixed(
                    state, pool, quota=quota, **kwargs
                )
                self.exact_attempts.append(catalog.stats.exact_attempts)
                return catalog

        settings = SearchSettings()
        mask = RecordingMask(settings)
        scanner = RecordingScanner(settings, mask)
        plan = StrictSkeletonCompiler(settings, scanner, mask).compile(
            packing, raw, occurrences, candidate, time.perf_counter() + 30.0
        )

        self.assertIsNotNone(plan)
        self.assertLessEqual(mask.advisory, 6)
        self.assertEqual(scanner.quotas[0][0], 1)
        self.assertIsInstance(scanner.quotas[0][1], CatalogWorkQuota)
        self.assertEqual(scanner.quotas[0][1].global_exact_attempt_cap, 64)
        self.assertFalse(scanner.quotas[0][1].include_dense)
        self.assertFalse(scanner.quotas[0][1].include_rescue)
        self.assertEqual(scanner.flags, [(False, False)])
        self.assertLessEqual(scanner.exact_attempts[0], 64)

    def test_selected_root_is_freshly_revalidated_and_parent_is_unchanged(self):
        raw = (_raw_item(0),)
        packing, occurrences, candidate = _candidate_case(raw)
        original_placed = tuple(len(container.placed) for container in packing.containers)

        class RecordingMask(ExactMask):
            def __init__(self, settings):
                super().__init__(settings)
                self.validated_keys = []

            def validate(self, state, pool, proposal, **kwargs):
                root = super().validate(state, pool, proposal, **kwargs)
                if root is not None:
                    self.validated_keys.append(tuple(root.proposal_key))
                return root

        settings = SearchSettings()
        mask = RecordingMask(settings)
        scanner = StrictRootScanner(settings, mask=mask)
        plan = StrictSkeletonCompiler(settings, scanner, mask).compile(
            packing, raw, occurrences, candidate, time.perf_counter() + 30.0
        )

        self.assertIsNotNone(plan)
        self.assertTrue(any(
            mask.validated_keys.count(key) >= 2 for key in mask.validated_keys
        ))
        self.assertEqual(
            tuple(len(container.placed) for container in packing.containers),
            original_placed,
        )

    def test_deadline_reached_after_scanner_discards_complete_catalog(self):
        raw = (_raw_item(0),)
        packing, occurrences, candidate = _candidate_case(raw)
        base = time.perf_counter()
        hard_deadline = base + 30.0
        clock_value = [base]

        class ExpiringScanner(StrictRootScanner):
            def scan_coverage_fixed(self, *args, **kwargs):
                result = super().scan_coverage_fixed(*args, **kwargs)
                clock_value[0] = hard_deadline
                return result

        settings = SearchSettings()
        mask = ExactMask(settings)
        scanner = ExpiringScanner(settings, mask=mask)
        compiler = StrictSkeletonCompiler(
            settings, scanner, mask, clock=lambda: clock_value[0]
        )

        self.assertIsNone(
            compiler.compile(
                packing, raw, occurrences, candidate, hard_deadline
            )
        )

    def test_partial_forged_or_identity_mismatched_candidate_fails_closed(self):
        raw = (_raw_item(0), _raw_item(1), _raw_item(2))
        packing, occurrences, candidate = _candidate_case(raw)
        partial = ProxyOrderCandidate(
            occurrence_order=candidate.occurrence_order,
            skeleton=candidate.skeleton[:2],
            placed_count=2,
            placed_volume=sum(value.item_signature[1] * value.item_signature[2] * value.item_signature[3] for value in candidate.occurrence_order[:2]),
            min_alternatives=candidate.min_alternatives,
            support_margin=candidate.support_margin,
            clearance_margin=candidate.clearance_margin,
            metrics=candidate.metrics,
            seed_discrepancies=candidate.seed_discrepancies,
            complete=False,
            seed_lane=candidate.seed_lane,
        )
        self.assertIsNone(
            _compiler().compile(
                packing, raw, occurrences, partial, time.perf_counter() + 30.0
            )
        )
        object.__setattr__(candidate, "complete", False)
        self.assertIsNone(
            _compiler().compile(
                packing, raw, occurrences, candidate, time.perf_counter() + 30.0
            )
        )

        first = occurrences[0]
        forged_signature = list(first.item_signature)
        forged_signature[4] += 1.0
        forged_occurrence = dataclasses.replace(
            first, item_signature=tuple(forged_signature)
        )
        forged_order = (forged_occurrence,) + occurrences[1:]
        forged_skeleton = (
            dataclasses.replace(
                candidate.skeleton[0], occurrence=forged_occurrence
            ),
        ) + candidate.skeleton[1:]
        forged_identity = dataclasses.replace(
            candidate,
            occurrence_order=forged_order,
            skeleton=forged_skeleton,
            complete=True,
        )
        self.assertIsNone(
            _compiler().compile(
                packing,
                raw,
                occurrences,
                forged_identity,
                time.perf_counter() + 30.0,
            )
        )

    def test_timeout_and_scanner_exception_publish_nothing(self):
        raw = (_raw_item(0),)
        packing, occurrences, candidate = _candidate_case(raw)
        now = time.perf_counter()
        self.assertIsNone(
            _compiler(clock=lambda: now + 1.0).compile(
                packing, raw, occurrences, candidate, now
            )
        )

        class RaisingScanner(StrictRootScanner):
            def scan_coverage_fixed(self, *args, **kwargs):
                raise RuntimeError("synthetic scanner failure")

        settings = SearchSettings()
        mask = ExactMask(settings)
        compiler = StrictSkeletonCompiler(
            settings, RaisingScanner(settings, mask=mask), mask
        )
        self.assertIsNone(
            compiler.compile(
                packing, raw, occurrences, candidate,
                time.perf_counter() + 30.0,
            )
        )

    def test_twenty_runs_are_deterministic_and_receipt_free(self):
        raw = (_raw_item(0),)
        packing, occurrences, candidate = _candidate_case(raw)
        values = []
        for _ in range(20):
            plan = _compiler(clock=lambda: 0.0).compile(
                packing, raw, occurrences, candidate, 100.0
            )
            values.append(plan)
        self.assertTrue(all(value == values[0] for value in values[1:]))
        _assert_receipt_free(self, values[0])

    def test_supporters_are_authoritative_when_compiled_stack_is_selected(self):
        raw = (
            _raw_item(0, length=0.8, width=0.7, height=0.12),
            _raw_item(1, length=0.2, width=0.2, height=0.10),
        )
        packing = build_packing_state([_container(shelf=False)])
        occurrences = build_offline_occurrences(raw)
        candidate = LayeredProxyOrderBeam(clock=lambda: 0.0).search(
            packing, occurrences, raw, 100.0
        )[0]
        floor_intent = dataclasses.replace(
            candidate.skeleton[0],
            orientation=0,
            local_position=(0.0, -0.2, 0.108),
            support_kind=SupportKind.FLOOR,
            supporter_occurrences=(),
        )
        stack_intent = dataclasses.replace(
            candidate.skeleton[1],
            orientation=0,
            local_position=(0.0, -0.2, 0.218),
            support_kind=SupportKind.PROXY_TOP,
            supporter_occurrences=(occurrences[0],),
        )
        candidate = dataclasses.replace(
            candidate, skeleton=(floor_intent, stack_intent)
        )
        plan = _compiler().compile(
            packing, raw, occurrences, candidate, time.perf_counter() + 30.0
        )
        self.assertIsNotNone(plan)
        authoritative = {value.original_position: value for value in occurrences}
        stacked = plan.skeleton[1]
        self.assertEqual(stacked.support_kind, SupportKind.PROXY_TOP)
        self.assertEqual(stacked.supporter_occurrences, (occurrences[0],))
        supporter = stacked.supporter_occurrences[0]
        self.assertEqual(
            supporter.stable_key,
            authoritative[supporter.original_position].stable_key,
        )

    def test_supporters_require_the_same_container_ordinal(self):
        raw = (_raw_item(0), _raw_item(1), _raw_item(2))
        occurrences = build_offline_occurrences(raw)
        state = build_packing_state([_container(), _container()])
        lower = AABB(
            np.asarray((-0.20, -0.20, 0.04), dtype=np.float64),
            np.asarray((0.20, 0.20, 0.20), dtype=np.float64),
        )
        upper = AABB(
            np.asarray((-0.10, -0.10, 0.20), dtype=np.float64),
            np.asarray((0.10, 0.10, 0.30), dtype=np.float64),
        )
        root = SimpleNamespace(
            proposal=PlacementProposal(2, 0, 0, 0, (0.0, 0.0, 0.25), "test"),
            box=upper,
            support_ratio=1.0,
            min_clearance=0.02,
        )
        compiler = _compiler()

        intent = compiler._compiled_intent(
            occurrences[2],
            root,
            1,
            state,
            (
                (occurrences[0], 1, lower),
                (occurrences[1], 0, lower),
            ),
            {value.original_position: value for value in occurrences},
            time.perf_counter() + 5.0,
        )

        self.assertEqual(intent.support_kind, SupportKind.PROXY_TOP)
        self.assertEqual(intent.supporter_occurrences, (occurrences[1],))

    def test_compiled_supporter_uses_mask_tolerance_and_requires_alignment(self):
        raw = (_raw_item(0), _raw_item(1), _raw_item(2))
        occurrences = build_offline_occurrences(raw)
        state = build_packing_state([_container()])
        settled_lower = AABB(
            np.asarray((-0.20, -0.20, 0.04), dtype=np.float64),
            np.asarray((0.20, 0.20, 0.20), dtype=np.float64),
            axis_aligned=True,
        )
        tilted_lower = AABB(
            np.asarray((-0.20, -0.20, 0.04), dtype=np.float64),
            np.asarray((0.20, 0.20, 0.21), dtype=np.float64),
            axis_aligned=False,
        )
        upper = AABB(
            np.asarray((-0.10, -0.10, 0.21), dtype=np.float64),
            np.asarray((0.10, 0.10, 0.31), dtype=np.float64),
        )
        root = SimpleNamespace(
            proposal=PlacementProposal(2, 0, 0, 0, (0.0, 0.0, 0.26), "test"),
            box=upper,
            support_ratio=1.0,
            min_clearance=0.02,
        )
        compiler = _compiler()
        intent = compiler._compiled_intent(
            occurrences[2],
            root,
            1,
            state,
            (
                (occurrences[0], 0, settled_lower),
                (occurrences[1], 0, tilted_lower),
            ),
            {value.original_position: value for value in occurrences},
            time.perf_counter() + 5.0,
        )
        self.assertEqual(intent.support_kind, SupportKind.PROXY_TOP)
        self.assertEqual(intent.supporter_occurrences, (occurrences[0],))

    def test_shelf_kind_requires_xy_overlap_and_otherwise_uses_placed_top(self):
        raw = (_raw_item(0),)
        occurrence = build_offline_occurrences(raw)[0]
        state = build_packing_state([_container(shelf=True)])
        container = state.containers[0]
        shelf_top = float(container.static_obstacles[0].maximum[2])
        bottom = shelf_top + 0.022
        root_box = AABB(
            np.asarray((0.60, -0.60, bottom), dtype=np.float64),
            np.asarray((0.80, -0.40, bottom + 0.10), dtype=np.float64),
        )
        supporting_box = AABB(
            np.asarray((0.55, -0.65, bottom - 0.10), dtype=np.float64),
            np.asarray((0.85, -0.35, bottom), dtype=np.float64),
        )
        container.placed.append(
            PlacedItem(ItemSpec.from_dict(_raw_item(99)), supporting_box)
        )
        root = SimpleNamespace(
            proposal=PlacementProposal(0, 0, 0, 0, (0.70, -0.50, bottom + 0.05), "test"),
            box=root_box,
            support_ratio=1.0,
            min_clearance=0.02,
        )
        compiler = _compiler()
        intent = compiler._compiled_intent(
            occurrence,
            root,
            1,
            state,
            (),
            {0: occurrence},
            time.perf_counter() + 5.0,
        )
        self.assertEqual(intent.support_kind, SupportKind.PLACED_TOP)

        overlapping = AABB(
            np.asarray((-0.90, -0.10, bottom), dtype=np.float64),
            np.asarray((-0.70, 0.10, bottom + 0.10), dtype=np.float64),
        )
        shelf_root = SimpleNamespace(
            proposal=PlacementProposal(0, 0, 0, 0, (-0.80, 0.0, bottom + 0.05), "test"),
            box=overlapping,
            support_ratio=1.0,
            min_clearance=0.02,
        )
        shelf_intent = compiler._compiled_intent(
            occurrence,
            shelf_root,
            1,
            state,
            (),
            {0: occurrence},
            time.perf_counter() + 5.0,
        )
        self.assertEqual(shelf_intent.support_kind, SupportKind.SHELF)

    def test_shelf_gap_is_nonnegative_and_tilted_initial_top_is_not_support(self):
        raw = (_raw_item(0),)
        occurrence = build_offline_occurrences(raw)[0]
        state = build_packing_state([_container(shelf=True)])
        container = state.containers[0]
        shelf_top = float(container.static_obstacles[0].maximum[2])
        overlap_min = np.asarray((-0.90, -0.10), dtype=np.float64)
        overlap_max = np.asarray((-0.70, 0.10), dtype=np.float64)

        below = shelf_top - 0.001
        support_item = ItemSpec.from_dict(_raw_item(98))
        container.placed.append(PlacedItem(
            support_item,
            AABB(
                np.asarray((overlap_min[0], overlap_min[1], below - 0.10), dtype=np.float64),
                np.asarray((overlap_max[0], overlap_max[1], below), dtype=np.float64),
                axis_aligned=True,
            ),
        ))
        compiler = _compiler()

        def classify(bottom, *, placed_axis_aligned=True):
            container.placed[-1] = PlacedItem(
                support_item,
                AABB(
                    np.asarray((overlap_min[0], overlap_min[1], bottom - 0.10), dtype=np.float64),
                    np.asarray((overlap_max[0], overlap_max[1], bottom), dtype=np.float64),
                    axis_aligned=placed_axis_aligned,
                ),
            )
            box = AABB(
                np.asarray((overlap_min[0], overlap_min[1], bottom), dtype=np.float64),
                np.asarray((overlap_max[0], overlap_max[1], bottom + 0.10), dtype=np.float64),
            )
            root = SimpleNamespace(
                proposal=PlacementProposal(0, 0, 0, 0, (-0.80, 0.0, bottom + 0.05), "test"),
                box=box,
                support_ratio=1.0,
                min_clearance=0.02,
            )
            return compiler._compiled_intent(
                occurrence,
                root,
                1,
                state,
                (),
                {0: occurrence},
                time.perf_counter() + 5.0,
            ).support_kind

        self.assertEqual(classify(below), SupportKind.PLACED_TOP)
        self.assertEqual(classify(shelf_top + 0.001), SupportKind.SHELF)
        self.assertEqual(
            classify(below, placed_axis_aligned=False), SupportKind.FLOOR
        )

    def test_advisory_obstacle_walk_stops_cooperatively_at_deadline(self):
        raw = (_raw_item(0),)
        packing, occurrences, candidate = _candidate_case(raw)
        container = packing.containers[0]
        obstacles = tuple(container.static_obstacles) * 40
        visited = []

        class SpyList(list):
            def __iter__(self):
                for value in super().__iter__():
                    visited.append(value)
                    yield value

        container.static_obstacles = SpyList(obstacles)
        ticks = iter((0.0, 0.1, 0.2, 1.0, 1.0))
        compiler = _compiler(clock=lambda: next(ticks, 1.0))
        with self.assertRaisesRegex(Exception, "compile deadline expired"):
            compiler._advisory_proposals(
                packing,
                ItemSpec.from_dict(raw[0]),
                candidate.skeleton[0],
                0.5,
            )
        self.assertLess(len(visited), len(obstacles))

    def test_expiry_after_fresh_apply_does_not_build_or_publish_intent(self):
        raw = (_raw_item(0),)
        packing, occurrences, candidate = _candidate_case(raw)
        base = time.perf_counter()
        hard_deadline = base + 30.0
        clock_value = [base]

        class ExpiringAfterFreshMask(ExactMask):
            def __init__(self, settings):
                super().__init__(settings)
                self.accepted = set()

            def validate(self, state, pool, proposal, **kwargs):
                root = super().validate(state, pool, proposal, **kwargs)
                if root is not None:
                    key = tuple(root.proposal_key)
                    if key in self.accepted:
                        clock_value[0] = hard_deadline
                    self.accepted.add(key)
                return root

        settings = SearchSettings()
        mask = ExpiringAfterFreshMask(settings)
        scanner = StrictRootScanner(settings, mask=mask)
        class RecordingCompiler(StrictSkeletonCompiler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.intent_calls = 0

            def _compiled_intent(self, *args, **kwargs):
                self.intent_calls += 1
                return super()._compiled_intent(*args, **kwargs)

        compiler = RecordingCompiler(
            settings, scanner, mask, clock=lambda: clock_value[0]
        )
        self.assertIsNone(
            compiler.compile(
                packing, raw, occurrences, candidate, hard_deadline
            )
        )
        self.assertEqual(compiler.intent_calls, 0)


if __name__ == "__main__":
    unittest.main()
