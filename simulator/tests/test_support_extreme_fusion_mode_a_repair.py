from __future__ import annotations

import dataclasses
import pathlib
import sys
import time
import unittest

import numpy as np


SIMULATOR_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(SIMULATOR_ROOT) not in sys.path:
    sys.path.insert(0, str(SIMULATOR_ROOT))

from agents.support_extreme_fusion_beam_exact_mask.catalog import (  # noqa: E402
    RootCatalog,
    StrictRootScanner,
)
from agents.support_extreme_fusion_beam_exact_mask.mask import ExactMask  # noqa: E402
from agents.support_extreme_fusion_beam_exact_mask.geometry import oriented_dimensions  # noqa: E402
from agents.support_extreme_fusion_beam_exact_mask.mode_a_repair import (  # noqa: E402
    ModeAExactSkeletonRepair,
)
from agents.support_extreme_fusion_beam_exact_mask.mode_a_types import (  # noqa: E402
    SupportKind,
    finalize_mode_a_plan,
)
from agents.support_extreme_fusion_beam_exact_mask.model import (  # noqa: E402
    AABB,
    ItemSpec,
    PlacedItem,
    PlacementProposal,
    Rect,
)
from agents.support_extreme_fusion_beam_exact_mask.settings import SearchSettings  # noqa: E402
from agents.support_extreme_fusion_beam_exact_mask.state import build_packing_state  # noqa: E402
from tests.test_support_extreme_fusion_layered_proxy import (  # noqa: E402
    _container,
    _raw_item,
)
from tests.test_support_extreme_fusion_mode_a_exact_compile import (  # noqa: E402
    _candidate_case,
    _compiler,
)


def _catalog(scanner, state, pool, *, advisory=()):
    return scanner.scan(
        state,
        pool,
        deadline=time.perf_counter() + 15.0,
        allow_deferred=False,
        allow_rescue=False,
        advisory_proposals=advisory,
    )


def _plan_case(raw):
    state, occurrences, candidate = _candidate_case(raw)
    plan = _compiler().compile(
        state, raw, occurrences, candidate, time.perf_counter() + 30.0
    )
    if plan is None:
        raise AssertionError("fixture strict plan did not compile")
    settings = SearchSettings()
    mask = ExactMask(settings)
    scanner = StrictRootScanner(settings, mask=mask)
    return state, occurrences, plan, settings, mask, scanner


def _catalog_signature(catalog):
    return (
        tuple(
            (
                record.root.proposal_key,
                record.root.proposal,
                tuple(float(value) for value in record.root.box.minimum),
                tuple(float(value) for value in record.root.box.maximum),
                record.root.box.axis_aligned,
                record.root.state_fingerprint,
                record.root.support_ratio,
                record.root.min_clearance,
                record.root.rule_violations,
                record.root.source,
                record.root.profile_digest,
                record.root.item_signature,
                record.root.strict,
                record.provenance,
                record.pass_name,
                record.raw_ordinal,
            )
            for record in catalog.records
        ),
        catalog.stats,
    )


class CatalogModeAAdvisoryTests(unittest.TestCase):
    def test_default_empty_advisory_is_bit_identical(self):
        raw = (_raw_item(0), _raw_item(1))
        state, _occurrences, _candidate = _candidate_case(raw)
        settings = SearchSettings()
        mask = ExactMask(settings)
        scanner = StrictRootScanner(settings, mask=mask)

        omitted = scanner.scan(
            state,
            raw,
            deadline=time.perf_counter() + 15.0,
            allow_deferred=False,
            allow_rescue=False,
        )
        explicit = _catalog(scanner, state, raw, advisory=())
        self.assertEqual(_catalog_signature(omitted), _catalog_signature(explicit))

    def test_valid_advisory_is_first_class_current_root(self):
        raw = (_raw_item(0),)
        state, _occurrences, _candidate = _candidate_case(raw)
        settings = SearchSettings()
        mask = ExactMask(settings)
        scanner = StrictRootScanner(settings, mask=mask)
        baseline = _catalog(scanner, state, raw)
        proposal = baseline.records[0].proposal

        advised = _catalog(scanner, state, raw, advisory=(proposal,))
        advisory_records = tuple(
            record for record in advised.records if record.pass_name == "advisory"
        )
        self.assertEqual(len(advisory_records), 1)
        self.assertEqual(advisory_records[0].root.proposal_key, baseline.records[0].root.proposal_key)
        self.assertIsNot(advisory_records[0].root, baseline.records[0].root)

    def test_advisory_reject_deduplicate_and_cap_six(self):
        raw = (_raw_item(0),)
        state, _occurrences, _candidate = _candidate_case(raw)

        class RecordingMask(ExactMask):
            def __init__(self, settings):
                super().__init__(settings)
                self.advisory_diagnoses = 0

            def diagnose(self, state, pool, proposal, **kwargs):
                if proposal.source.startswith("mode_a_test"):
                    self.advisory_diagnoses += 1
                return super().diagnose(state, pool, proposal, **kwargs)

        settings = SearchSettings()
        mask = RecordingMask(settings)
        scanner = StrictRootScanner(settings, mask=mask)
        invalid = tuple(
            PlacementProposal(0, 0, 0, 0, (90.0 + value, 90.0, 90.0), f"mode_a_test_{value}")
            for value in range(7)
        )
        advised = _catalog(
            scanner,
            state,
            raw,
            advisory=(invalid[0], invalid[0]) + invalid[1:],
        )
        self.assertLessEqual(mask.advisory_diagnoses, 6)
        self.assertFalse(any(record.pass_name == "advisory" for record in advised))
        self.assertTrue(advised.records)

    def test_advisory_requires_matching_diagnose_and_fresh_receipts(self):
        raw = (_raw_item(0),)
        state, _occurrences, _candidate = _candidate_case(raw)
        settings = SearchSettings()
        baseline_mask = ExactMask(settings)
        baseline_scanner = StrictRootScanner(settings, mask=baseline_mask)
        proposal = _catalog(baseline_scanner, state, raw).records[0].proposal

        class AlteringDiagnoseMask(ExactMask):
            def __init__(self, settings):
                super().__init__(settings)
                self.calls = 0

            def diagnose(self, state, pool, proposal, **kwargs):
                self.calls += 1
                trace = super().diagnose(state, pool, proposal, **kwargs)
                if self.calls == 1 and trace.accepted and trace.root is not None:
                    object.__setattr__(
                        trace.root,
                        "support_ratio",
                        trace.root.support_ratio + 0.01,
                    )
                return trace

        mask = AlteringDiagnoseMask(settings)
        advised = _catalog(
            StrictRootScanner(settings, mask=mask),
            state,
            raw,
            advisory=(proposal,),
        )
        self.assertFalse(any(record.pass_name == "advisory" for record in advised))
        self.assertGreaterEqual(
            advised.stats.rejection_count("invalid_exact_evidence"), 1
        )


class ModeAExactSkeletonRepairTests(unittest.TestCase):
    def test_returns_original_catalog_identity_and_is_idempotent(self):
        raw = (_raw_item(0), _raw_item(1))
        state, _occurrences, plan, settings, mask, scanner = _plan_case(raw)
        catalog = _catalog(scanner, state, raw)
        repair = ModeAExactSkeletonRepair(settings, scanner, mask)

        first = repair.choose(
            state, raw, catalog, plan, (), time.perf_counter() + 15.0
        )
        second = repair.choose(
            state, raw, catalog, plan, (), time.perf_counter() + 15.0
        )

        self.assertIsNotNone(first)
        self.assertTrue(any(first is record.root for record in catalog.records))
        self.assertIs(second, first)

    def test_invalid_planned_hint_repairs_with_normal_exact_root(self):
        raw = (_raw_item(0),)
        state, occurrences, plan, settings, mask, scanner = _plan_case(raw)
        intent = dataclasses.replace(
            plan.skeleton[0], local_position=(99.0, 99.0, 99.0)
        )
        _order, repaired_hint_plan = finalize_mode_a_plan(
            occurrences,
            plan.returned_order,
            (intent,),
            plan.trace,
        )
        catalog = _catalog(scanner, state, raw)
        selected = ModeAExactSkeletonRepair(settings, scanner, mask).choose(
            state,
            raw,
            catalog,
            repaired_hint_plan,
            (),
            time.perf_counter() + 15.0,
        )
        self.assertIsNotNone(selected)
        self.assertTrue(any(selected is record.root for record in catalog.records))
        self.assertNotEqual(selected.proposal.position, intent.local_position)

    def test_stale_plan_disables_hints_but_keeps_safe_catalog_fallback(self):
        raw = (_raw_item(0),)
        state, _occurrences, plan, settings, mask, scanner = _plan_case(raw)
        catalog = _catalog(scanner, state, raw)
        object.__setattr__(plan, "plan_digest", "0" * 64)
        selected = ModeAExactSkeletonRepair(settings, scanner, mask).choose(
            state, raw, catalog, plan, (), time.perf_counter() + 15.0
        )
        self.assertIsNotNone(selected)
        self.assertTrue(any(selected is record.root for record in catalog.records))

    def test_duplicate_signature_and_preloaded_subtraction_are_observation_derived(self):
        raw = (_raw_item(4), _raw_item(4))
        state, _occurrences, plan, settings, mask, scanner = _plan_case(raw)
        catalog = _catalog(scanner, state, raw)
        repair = ModeAExactSkeletonRepair(settings, scanner, mask)
        signature = plan.occurrences[0].item_signature

        packed = PlacedItem(
            ItemSpec.from_dict(raw[0]),
            AABB(
                np.asarray((-0.1, -0.1, 0.048), dtype=np.float64),
                np.asarray((0.1, 0.1, 0.168), dtype=np.float64),
            ),
        )
        state.containers[0].placed.append(packed)
        without_preload = repair.derive_next_intent(state, plan, ())
        with_preload = repair.derive_next_intent(state, plan, (signature,))
        self.assertEqual(without_preload.occurrence.original_position, 1)
        self.assertEqual(with_preload.occurrence.original_position, 0)
        state.containers[0].placed.pop()
        selected = repair.choose(
            state, raw, catalog, plan, (signature,), time.perf_counter() + 15.0
        )
        self.assertIsNotNone(selected)
        self.assertEqual(selected.proposal.pool_index, 0)

    def test_every_catalog_root_is_freshly_applied_before_ranking(self):
        raw = (_raw_item(0),)
        state, _occurrences, plan, settings, _mask, scanner = _plan_case(raw)
        catalog = _catalog(scanner, state, raw)

        class RecordingMask(ExactMask):
            def __init__(self, settings):
                super().__init__(settings)
                self.keys = []

            def validate(self, state, pool, proposal, **kwargs):
                result = super().validate(state, pool, proposal, **kwargs)
                self.keys.append((proposal.item_index, proposal.pool_index,
                                  proposal.container_index, proposal.orientation,
                                  tuple(round(value, 7) for value in proposal.position)))
                return result

        mask = RecordingMask(settings)
        repair = ModeAExactSkeletonRepair(
            settings, StrictRootScanner(settings, mask=mask), mask
        )
        selected = repair.choose(
            state, raw, catalog, plan, (), time.perf_counter() + 15.0
        )
        self.assertIsNotNone(selected)
        self.assertEqual(
            set(mask.keys),
            {tuple(record.root.proposal_key) for record in catalog.records},
        )

    def test_root_exception_isolated_and_deadline_keeps_first_exact_incumbent(self):
        raw = (_raw_item(0),)
        state, _occurrences, plan, settings, _mask, scanner = _plan_case(raw)
        catalog = _catalog(scanner, state, raw)
        self.assertGreater(len(catalog.records), 1)
        rejected_key = tuple(catalog.records[0].root.proposal_key)

        class OneRaisingMask(ExactMask):
            def validate(self, state, pool, proposal, **kwargs):
                key = (
                    proposal.item_index,
                    proposal.pool_index,
                    proposal.container_index,
                    proposal.orientation,
                    tuple(round(value, 7) for value in proposal.position),
                )
                if key == rejected_key:
                    raise RuntimeError("isolated root failure")
                return super().validate(state, pool, proposal, **kwargs)

        raising = OneRaisingMask(settings)
        selected = ModeAExactSkeletonRepair(
            settings, StrictRootScanner(settings, mask=raising), raising
        ).choose(state, raw, catalog, plan, (), time.perf_counter() + 15.0)
        self.assertIsNotNone(selected)
        self.assertIsNot(selected, catalog.records[0].root)

        base = time.perf_counter()
        hard_deadline = base + 30.0
        clock_value = [base]

        class ExpiringMask(ExactMask):
            def validate(self, state, pool, proposal, **kwargs):
                result = super().validate(state, pool, proposal, **kwargs)
                if result is not None:
                    clock_value[0] = hard_deadline
                return result

        expiring = ExpiringMask(settings)
        deadline_repair = ModeAExactSkeletonRepair(
            settings,
            StrictRootScanner(settings, mask=expiring),
            expiring,
            clock=lambda: clock_value[0],
        )
        incumbent = deadline_repair.choose(
            state, raw, catalog, plan, (), hard_deadline
        )
        self.assertIs(incumbent, catalog.records[0].root)

    def test_suffix_survival_dominates_container_orientation_and_support_hints(self):
        raw = (_raw_item(0),)
        _state, _occurrences, plan, settings, mask, _scanner = _plan_case(raw)
        state = build_packing_state([_container(shelf=True), _container(shelf=True)])
        scanner = StrictRootScanner(settings, mask=mask)
        ordinary = _catalog(scanner, state, raw)
        container_one = dataclasses.replace(
            ordinary.records[0].proposal,
            container_index=1,
            source="mode_a_container_one",
        )
        catalog = _catalog(scanner, state, raw, advisory=(container_one,))
        by_container = {
            record.container_index for record in catalog.records
        }
        self.assertEqual(by_container, {0, 1})

        class SurvivalRepair(ModeAExactSkeletonRepair):
            def _suffix_proxy_score(self, placement, suffix, deadline):
                del suffix, deadline
                return (
                    2 if placement.root.proposal.container_index == 1 else 1,
                    1.0,
                )

        selected = SurvivalRepair(settings, scanner, mask).choose(
            state, raw, catalog, plan, (), time.perf_counter() + 15.0
        )
        self.assertIsNotNone(selected)
        self.assertEqual(selected.proposal.container_index, 1)
        self.assertTrue(any(selected is record.root for record in catalog.records))

    def test_supporter_translation_and_z_rebase(self):
        raw = (_raw_item(0), _raw_item(1))
        state, occurrences, plan, settings, mask, scanner = _plan_case(raw)
        intent = dataclasses.replace(
            plan.skeleton[1],
            support_kind=SupportKind.PROXY_TOP,
            supporter_occurrences=(occurrences[0],),
        )
        actual_center = (0.25, -0.15, 0.40)
        actual_top = 0.46
        actual_footprint = Rect(0.10, 0.40, -0.30, 0.0)
        target = ModeAExactSkeletonRepair(settings, scanner, mask).rebase_intent_position(
            intent,
            {
                occurrences[0].stable_key: (
                    actual_center,
                    actual_top,
                    intent.container_ordinal,
                    actual_footprint,
                )
            },
            plan,
        )
        planned_support = plan.skeleton[0].local_position
        self.assertAlmostEqual(
            target[0], intent.local_position[0] + actual_center[0] - planned_support[0]
        )
        self.assertAlmostEqual(
            target[1], intent.local_position[1] + actual_center[1] - planned_support[1]
        )
        expected_half_height = oriented_dimensions(
            intent.occurrence.item_signature[1:4], intent.orientation
        )[2] / 2.0
        self.assertGreaterEqual(target[2], actual_top + expected_half_height - 1e-9)

        foreign = ModeAExactSkeletonRepair(
            settings, scanner, mask
        ).rebase_intent_position(
            intent,
            {
                occurrences[0].stable_key: (
                    actual_center,
                    actual_top,
                    intent.container_ordinal + 1,
                    actual_footprint,
                )
            },
            plan,
        )
        self.assertEqual(foreign, intent.local_position)
        with self.assertRaises((TypeError, ValueError)):
            ModeAExactSkeletonRepair(
                settings, scanner, mask
            ).rebase_intent_position(
                intent,
                {occurrences[0].stable_key: [actual_center, actual_top]},
                plan,
            )

    def test_expired_deadline_returns_none_and_empty_catalog_is_safe(self):
        raw = (_raw_item(0),)
        state, _occurrences, plan, settings, mask, scanner = _plan_case(raw)
        repair = ModeAExactSkeletonRepair(settings, scanner, mask)
        now = time.perf_counter()
        self.assertIsNone(repair.choose(state, raw, _catalog(scanner, state, raw), plan, (), now))

    def test_context_expiry_returns_first_fresh_incumbent_without_fallback_sort(self):
        raw = (_raw_item(0),)
        state, _occurrences, plan, settings, mask, scanner = _plan_case(raw)
        catalog = _catalog(scanner, state, raw)
        baseline = ModeAExactSkeletonRepair(settings, scanner, mask)
        fallback = baseline.choose(
            state, raw, catalog, None, (), time.perf_counter() + 15.0
        )
        nonfallback = next(
            record for record in catalog.records if record.root is not fallback
        )
        reordered = RootCatalog(
            (nonfallback,) + tuple(
                record for record in catalog.records if record is not nonfallback
            ),
            catalog.stats,
        )
        base = time.perf_counter()
        hard_deadline = base + 30.0
        clock_value = [base]

        class ExpiringContextRepair(ModeAExactSkeletonRepair):
            rebase_calls = 0

            def _derive_context(self, *args, **kwargs):
                result = super()._derive_context(*args, **kwargs)
                clock_value[0] = hard_deadline
                return result

            def rebase_intent_position(self, *args, **kwargs):
                self.rebase_calls += 1
                return super().rebase_intent_position(*args, **kwargs)

        repair = ExpiringContextRepair(
            settings, scanner, mask, clock=lambda: clock_value[0]
        )
        selected = repair.choose(state, raw, reordered, plan, (), hard_deadline)
        self.assertIs(selected, nonfallback.root)
        self.assertIsNot(selected, fallback)
        self.assertEqual(repair.rebase_calls, 0)


if __name__ == "__main__":
    unittest.main()
