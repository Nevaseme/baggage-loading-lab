from __future__ import annotations

from dataclasses import replace
import copy
import pathlib
import sys
import time
import unittest
from unittest.mock import patch


SIMULATOR_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(SIMULATOR_ROOT) not in sys.path:
    sys.path.insert(0, str(SIMULATOR_ROOT))

from agents.support_extreme_fusion_beam_exact_mask.catalog import (  # noqa: E402
    AdaptiveDenseRescueConfig,
    StrictRootScanner,
)
from agents.support_extreme_fusion_beam_exact_mask.mask import (  # noqa: E402
    ExactMask,
    RejectReason,
    ValidationTrace,
)
from agents.support_extreme_fusion_beam_exact_mask.model import (  # noqa: E402
    ItemSpec,
    PlacementProposal,
    ValidatedRoot,
)
from agents.support_extreme_fusion_beam_exact_mask.proposals import (  # noqa: E402
    FusedProposal,
    ProposalProvenance,
    ProposalSource,
)
from agents.support_extreme_fusion_beam_exact_mask.settings import SearchSettings  # noqa: E402
from agents.support_extreme_fusion_beam_exact_mask.state import build_packing_state  # noqa: E402
from agents.support_extreme_fusion_beam_exact_mask.transition import (  # noqa: E402
    SimState,
    apply_root,
)
from tests.replay_support import load_observation_snapshot  # noqa: E402


def _container() -> dict:
    return {
        "index": 0,
        "length": 2.0,
        "width": 1.5,
        "height": 1.6,
        "thickness": 0.04,
        "cut_x": 0.4,
        "cut_y": 0.4,
        "center": (0.0, 0.0, 0.8),
        "points": [
            [0.96, 0.0, 0.0],
            [-0.96, 0.0, 0.0],
            [0.0, 0.71, 0.0],
            [0.0, -0.71, 0.0],
            [0.0, 0.0, 1.56],
            [0.0, 0.0, 0.04],
        ],
        "n_vecs": [
            [1.0, 0.0, 0.0],
            [-1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, -1.0, 0.0],
            [0.0, 0.0, 1.0],
            [0.0, 0.0, -1.0],
        ],
        "volume": 4.8,
        "shelf": False,
        "is_prioritized": False,
        "packed_items": [],
    }


def _item(index: int) -> ItemSpec:
    return ItemSpec(index=index, length=0.20, width=0.16, height=0.12, mass=1.0)


def _fused(item: ItemSpec, pool_index: int, serial: int, *, valid: bool) -> FusedProposal:
    if valid:
        position = (-0.70 + 0.02 * (serial % 4), 0.45, 0.108)
    else:
        position = (
            -0.90 + 0.01 * (serial % 20),
            0.60 - 0.01 * (serial // 20),
            2.0,
        )
    proposal = PlacementProposal(
        item_index=item.index,
        pool_index=pool_index,
        container_index=0,
        orientation=0,
        position=position,
        source=ProposalSource.DENSE_SUPPORT_LATTICE.value,
    )
    return FusedProposal(
        proposal,
        ProposalProvenance(
            sources=(ProposalSource.DENSE_SUPPORT_LATTICE.value,),
            support_sources=("floor",),
            support_levels=(0.04,),
        ),
    )


class _DeadlineIgnoringMask(ExactMask):
    def diagnose(self, state, pool, proposal, *, deadline=None):
        return super().diagnose(state, pool, proposal, deadline=None)


class _RecordingMask(_DeadlineIgnoringMask):
    def __init__(self, settings, calls, clock_update=None):
        super().__init__(settings)
        self.calls = calls
        self.validate_calls: list[int] = []
        self.clock_update = clock_update

    def diagnose(self, state, pool, proposal, *, deadline=None):
        self.calls.append(proposal.pool_index)
        trace = super().diagnose(state, pool, proposal, deadline=None)
        if self.clock_update is not None:
            self.clock_update()
        return trace

    def validate(self, state, pool, proposal, *, deadline=None):
        self.validate_calls.append(proposal.pool_index)
        return ExactMask.diagnose(
            self, state, pool, proposal, deadline=None
        ).root


class GlobalZeroAdaptiveDenseRescueTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = SearchSettings(
            raw_proposal_limit=256,
            proposal_quantum=1,
            normal_catalog_limit_seconds=10.0,
            zero_root_rescue_limit_seconds=10.0,
        )
        self.state = build_packing_state([_container()])
        self.config = AdaptiveDenseRescueConfig()

    def _scanner(self, *, clock=lambda: 0.0, mask=None, global_cap=64):
        return StrictRootScanner(
            self.settings,
            mask=mask or _DeadlineIgnoringMask(self.settings),
            adaptive_dense_rescue=self.config,
            clock=clock,
            global_cap=global_cap,
        )

    def test_default_legacy_and_adaptive_nonzero_path_are_exactly_equivalent(self):
        pool = [_item(1).to_dict()]
        calls: list[tuple[ProposalSource, ...]] = []

        def records(_state, item, pool_index, **kwargs):
            families = tuple(kwargs.get("family_subset") or ())
            calls.append(families)
            if families == (ProposalSource.FREE_RECTANGLE_BOUNDARY,):
                yield _fused(_item(1), pool_index, 0, valid=True)

        with patch(
            "agents.support_extreme_fusion_beam_exact_mask.catalog.iter_fused_records",
            side_effect=records,
        ):
            legacy = StrictRootScanner(
                self.settings,
                mask=_DeadlineIgnoringMask(self.settings),
                clock=lambda: 0.0,
            ).scan(self.state, pool)
            calls_after_legacy = len(calls)
            adaptive = self._scanner().scan(self.state, pool)

        self.assertEqual(
            tuple((record.stable_key, record.root.proposal_key) for record in legacy),
            tuple((record.stable_key, record.root.proposal_key) for record in adaptive),
        )
        self.assertEqual(legacy.stats, adaptive.stats)
        self.assertFalse(adaptive.stats.adaptive_dense_activated)
        self.assertNotIn(
            (ProposalSource.DENSE_SUPPORT_LATTICE,), calls[calls_after_legacy:]
        )

    def test_global_zero_calls_dense_4096_once_and_recovers_late_root(self):
        item = _item(2)
        pool = [item.to_dict()]
        dense_calls: list[dict] = []

        def records(_state, _item_value, pool_index, **kwargs):
            families = tuple(kwargs.get("family_subset") or ())
            if families != (ProposalSource.DENSE_SUPPORT_LATTICE,):
                return
            dense_calls.append(dict(kwargs))
            for serial in range(300):
                yield _fused(item, pool_index, serial, valid=False)
            yield _fused(item, pool_index, 0, valid=True)

        with patch(
            "agents.support_extreme_fusion_beam_exact_mask.catalog.iter_fused_records",
            side_effect=records,
        ):
            catalog = self._scanner().scan(self.state, pool, deadline=10.0)

        self.assertEqual(len(dense_calls), 1)
        self.assertEqual(dense_calls[0]["raw_work_limit"], 4096)
        self.assertEqual(len(catalog), 1)
        self.assertEqual(catalog.records[0].pool_index, 0)
        self.assertTrue(catalog.stats.adaptive_dense_activated)
        self.assertEqual(catalog.stats.adaptive_dense_covered_occurrences, 1)
        self.assertGreater(catalog.stats.adaptive_dense_exact_attempts, 256)

    def test_exact_round_robin_does_not_starve_later_pool_and_stops_first_root(self):
        items = [_item(10), _item(11), _item(12)]
        pool = [item.to_dict() for item in items]
        exact_order: list[int] = []
        mask = _RecordingMask(self.settings, exact_order)

        def records(_state, _item_value, pool_index, **kwargs):
            if tuple(kwargs.get("family_subset") or ()) != (
                ProposalSource.DENSE_SUPPORT_LATTICE,
            ):
                return
            if pool_index == 0:
                for serial in range(5):
                    yield _fused(items[0], 0, serial, valid=False)
            elif pool_index == 1:
                yield _fused(items[1], 1, 0, valid=True)
                yield _fused(items[1], 1, 1, valid=True)
            else:
                yield _fused(items[2], 2, 0, valid=False)
                yield _fused(items[2], 2, 1, valid=True)

        with patch(
            "agents.support_extreme_fusion_beam_exact_mask.catalog.iter_fused_records",
            side_effect=records,
        ):
            catalog = self._scanner(mask=mask).scan(self.state, pool, deadline=10.0)

        self.assertEqual(exact_order[:3], [0, 1, 2])
        self.assertEqual(exact_order.count(1), 1)
        self.assertEqual(catalog.stats.per_pool_roots, (0, 1, 1))
        self.assertEqual(catalog.stats.adaptive_dense_covered_occurrences, 2)

    def test_global_target_is_eight_distinct_occurrences_even_with_duplicate_ids(self):
        items = [_item(77) for _ in range(10)]
        pool = [item.to_dict() for item in items]

        def records(_state, _item_value, pool_index, **kwargs):
            if tuple(kwargs.get("family_subset") or ()) == (
                ProposalSource.DENSE_SUPPORT_LATTICE,
            ):
                yield _fused(items[pool_index], pool_index, 0, valid=True)
                yield _fused(items[pool_index], pool_index, 1, valid=True)

        with patch(
            "agents.support_extreme_fusion_beam_exact_mask.catalog.iter_fused_records",
            side_effect=records,
        ):
            catalog = self._scanner().scan(self.state, pool, deadline=10.0)

        self.assertEqual([record.pool_index for record in catalog], list(range(8)))
        self.assertEqual(catalog.stats.adaptive_dense_covered_occurrences, 8)
        self.assertEqual(catalog.stats.adaptive_dense_exact_attempts, 8)
        self.assertTrue(catalog.stats.adaptive_dense_early_stop)

    def test_reserve_deadline_retains_only_predeadline_partial_root(self):
        items = [_item(31), _item(32)]
        pool = [item.to_dict() for item in items]
        now = [8.5]
        calls: list[int] = []

        def advance():
            now[0] += 0.5

        mask = _RecordingMask(self.settings, calls, advance)

        def records(_state, _item_value, pool_index, **kwargs):
            if tuple(kwargs.get("family_subset") or ()) == (
                ProposalSource.DENSE_SUPPORT_LATTICE,
            ):
                yield _fused(items[pool_index], pool_index, 0, valid=True)

        with patch(
            "agents.support_extreme_fusion_beam_exact_mask.catalog.iter_fused_records",
            side_effect=records,
        ):
            catalog = self._scanner(clock=lambda: now[0], mask=mask).scan(
                self.state, pool, deadline=10.0
            )

        self.assertEqual([record.pool_index for record in catalog], [0])
        self.assertEqual(calls, [0, 1])
        self.assertTrue(catalog.stats.adaptive_dense_deadline_reached)
        self.assertFalse(catalog.stats.deadline_reached)

    def test_foreign_or_nonstrict_diagnostic_receipt_is_not_catalogued(self):
        item = _item(45)
        pool = [item.to_dict()]
        proposal = _fused(item, 0, 0, valid=True).proposal
        root = ExactMask(self.settings).diagnose(self.state, pool, proposal).root
        self.assertIsInstance(root, ValidatedRoot)
        nonstrict = copy.deepcopy(root)
        object.__setattr__(nonstrict, "strict", False)
        invalid_roots = (replace(root, state_fingerprint="foreign"), nonstrict)

        class InvalidEvidenceMask(_DeadlineIgnoringMask):
            invalid_root = invalid_roots[0]

            def diagnose(self, *_args, **_kwargs):
                return ValidationTrace(True, self.invalid_root, None)

        def records(_state, _item_value, pool_index, **kwargs):
            if tuple(kwargs.get("family_subset") or ()) == (
                ProposalSource.DENSE_SUPPORT_LATTICE,
            ):
                yield _fused(item, pool_index, 0, valid=True)

        for invalid_root in invalid_roots:
            with self.subTest(strict=invalid_root.strict, fingerprint=invalid_root.state_fingerprint):
                mask = InvalidEvidenceMask(self.settings)
                mask.invalid_root = invalid_root
                with patch(
                    "agents.support_extreme_fusion_beam_exact_mask.catalog.iter_fused_records",
                    side_effect=records,
                ):
                    catalog = self._scanner(mask=mask).scan(
                        self.state, pool, deadline=10.0
                    )
                self.assertFalse(catalog)
                self.assertEqual(
                    dict(catalog.stats.rejection_counts).get(
                        "invalid_exact_evidence"
                    ),
                    1,
                )

    def test_adaptive_accept_requires_one_fresh_matching_validate_receipt(self):
        item = _item(46)
        pool = [item.to_dict()]
        fused = _fused(item, 0, 0, valid=True)
        authoritative = ExactMask(self.settings)
        diagnosed = authoritative.validate(self.state, pool, fused.proposal)
        fresh = authoritative.validate(self.state, pool, fused.proposal)
        self.assertIsInstance(diagnosed, ValidatedRoot)
        self.assertIsInstance(fresh, ValidatedRoot)
        self.assertIsNot(diagnosed, fresh)

        class TwoPhaseMask:
            profile_digest = authoritative.profile_digest

            def __init__(self, trace, validated):
                self.trace = trace
                self.validated = validated
                self.diagnose_calls = 0
                self.validate_calls = 0

            def diagnose(self, *_args, **_kwargs):
                self.diagnose_calls += 1
                return self.trace

            def validate(self, *_args, **_kwargs):
                self.validate_calls += 1
                return self.validated

        cases = (
            (
                "diagnose_reject",
                ValidationTrace(False, None, RejectReason.SUPPORT_RATIO),
                fresh,
                0,
                False,
            ),
            (
                "validate_none",
                ValidationTrace(True, diagnosed, None),
                None,
                1,
                False,
            ),
            (
                "diagnose_and_validate_disagree",
                ValidationTrace(True, replace(diagnosed, source="altered"), None),
                fresh,
                1,
                False,
            ),
            (
                "matching_fresh_receipt",
                ValidationTrace(True, diagnosed, None),
                fresh,
                1,
                True,
            ),
        )

        def records(_state, _item_value, pool_index, **kwargs):
            if tuple(kwargs.get("family_subset") or ()) == (
                ProposalSource.DENSE_SUPPORT_LATTICE,
            ):
                yield fused

        for name, trace, validated, expected_validate_calls, expected_root in cases:
            with self.subTest(name=name):
                mask = TwoPhaseMask(trace, validated)
                with patch(
                    "agents.support_extreme_fusion_beam_exact_mask.catalog.iter_fused_records",
                    side_effect=records,
                ):
                    catalog = self._scanner(mask=mask).scan(
                        self.state, pool, deadline=10.0
                    )
                self.assertEqual(mask.diagnose_calls, 1)
                self.assertEqual(mask.validate_calls, expected_validate_calls)
                self.assertEqual(bool(catalog), expected_root)
                if expected_root:
                    self.assertIs(catalog.records[0].root, fresh)

    def test_allow_rescue_false_never_invokes_adaptive_dense_generator(self):
        pool = [_item(47).to_dict()]
        dense_calls = 0

        def records(_state, _item_value, _pool_index, **kwargs):
            nonlocal dense_calls
            if tuple(kwargs.get("family_subset") or ()) == (
                ProposalSource.DENSE_SUPPORT_LATTICE,
            ):
                dense_calls += 1
            return iter(())

        with patch(
            "agents.support_extreme_fusion_beam_exact_mask.catalog.iter_fused_records",
            side_effect=records,
        ):
            catalog = self._scanner().scan(
                self.state, pool, deadline=10.0, allow_rescue=False
            )

        self.assertFalse(catalog)
        self.assertEqual(dense_calls, 0)
        self.assertFalse(catalog.stats.adaptive_dense_activated)

    def test_twenty_synthetic_repeats_have_identical_roots_and_stats(self):
        items = [_item(50), _item(50)]
        pool = [item.to_dict() for item in items]

        def records(_state, _item_value, pool_index, **kwargs):
            if tuple(kwargs.get("family_subset") or ()) == (
                ProposalSource.DENSE_SUPPORT_LATTICE,
            ):
                yield _fused(items[pool_index], pool_index, 0, valid=True)

        outputs = []
        with patch(
            "agents.support_extreme_fusion_beam_exact_mask.catalog.iter_fused_records",
            side_effect=records,
        ):
            for _ in range(20):
                catalog = self._scanner().scan(self.state, pool, deadline=10.0)
                outputs.append(
                    (
                        tuple(record.stable_key for record in catalog),
                        catalog.stats,
                    )
                )
        self.assertTrue(all(value == outputs[0] for value in outputs[1:]))

    def test_task18d_step15_exposes_fresh_current_bound_roots(self):
        snapshot = SIMULATOR_ROOT / (
            "results/support_extreme_fusion/"
            "task001-b-maxrects-regret-seed42-failure.npz"
        )
        observation, _ = load_observation_snapshot(snapshot)
        state = build_packing_state(
            observation["container_list"], observation.get("depth_map")
        )
        pool = observation["pool_list"]
        scanner = StrictRootScanner(adaptive_dense_rescue=self.config)
        started = time.perf_counter()
        catalog = scanner.scan(state, pool, deadline=started + 5.45)

        self.assertTrue(catalog)
        self.assertTrue(catalog.stats.adaptive_dense_activated)
        sim = SimState.from_current(state, pool)
        for record in catalog:
            placement = apply_root(
                sim,
                record.root,
                scanner.settings,
                exact_revalidator=scanner.mask,
                deadline=time.perf_counter() + 2.0,
            )
            self.assertEqual(
                placement.selected_pool_index, record.proposal.pool_index
            )


if __name__ == "__main__":
    unittest.main()
