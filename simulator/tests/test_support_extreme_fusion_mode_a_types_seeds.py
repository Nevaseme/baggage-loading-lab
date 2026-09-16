from __future__ import annotations

import ast
from collections import Counter
import copy
import dataclasses
import math
import pathlib
import sys
import unittest

import numpy as np


SIMULATOR_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(SIMULATOR_ROOT) not in sys.path:
    sys.path.insert(0, str(SIMULATOR_ROOT))

from agents.support_extreme_fusion_beam_exact_mask.mode_a_seeds import (  # noqa: E402
    historical_static_order_seed,
)
from agents.support_extreme_fusion_beam_exact_mask.mode_a_types import (  # noqa: E402
    MODE_A_PLAN_PROFILE_VERSION,
    ModeAOptimizeTrace,
    ModeAPlan,
    OfflineOccurrence,
    SkeletonIntent,
    SupportKind,
    build_offline_occurrences,
    compute_mode_a_plan_digest,
    finalize_mode_a_plan,
)
from agents.support_extreme_fusion_beam_exact_mask.model import (  # noqa: E402
    PlacementProposal,
    ValidatedRoot,
)


def _raw(
    index: int,
    *,
    length: float = 0.2,
    width: float = 0.2,
    height: float = 0.2,
    mass: float = 1.0,
    priority: bool = False,
    soft: bool = False,
    belongs_to: int | None = None,
) -> dict:
    value = {
        "index": index,
        "length": length,
        "width": width,
        "height": height,
        "mass": mass,
        "is_prioritized": priority,
        "is_soft": soft,
    }
    if belongs_to is not None:
        value["belongs_to"] = belongs_to
    return value


def _trace(*, complete: bool = True, fallback_reason: str = ""):
    return ModeAOptimizeTrace(
        nodes=7,
        fit_tests=23,
        candidates=11,
        elapsed_seconds=0.25,
        complete=complete,
        fallback_reason=fallback_reason,
    )


def _skeleton(occurrences):
    return tuple(
        SkeletonIntent(
            occurrence=value,
            container_ordinal=0,
            orientation=index % 6,
            local_position=(float(index), 0.0, 0.1),
            support_kind=SupportKind.FLOOR,
            supporter_occurrences=(),
            alternative_count=1,
            support_margin=0.8,
            clearance_margin=0.02,
        )
        for index, value in enumerate(occurrences)
    )


class OfflineOccurrenceTests(unittest.TestCase):
    def test_build_occurrences_distinguishes_duplicate_ids_and_signatures(self):
        raw = [_raw(7), _raw(7), _raw(7, mass=2.0), _raw(7)]
        occurrences = build_offline_occurrences(raw)

        self.assertEqual(
            tuple(value.original_position for value in occurrences), (0, 1, 2, 3)
        )
        self.assertEqual(tuple(value.item_index for value in occurrences), (7, 7, 7, 7))
        self.assertEqual(tuple(value.duplicate_ordinal for value in occurrences), (0, 1, 0, 2))
        self.assertEqual(occurrences[0].item_signature, occurrences[1].item_signature)
        self.assertNotEqual(occurrences[1].item_signature, occurrences[2].item_signature)

    def test_source_mutation_cannot_change_canonical_occurrence(self):
        raw = _raw(2)
        occurrences = build_offline_occurrences([raw])
        before = occurrences[0]
        raw["mass"] = 99.0

        self.assertEqual(before.item_signature[4], 1.0)
        self.assertIsInstance(before.item_signature, tuple)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            before.duplicate_ordinal = 4

    def test_malformed_exact_ints_bools_and_signature_are_rejected(self):
        signature = build_offline_occurrences([_raw(1)])[0].item_signature
        for field in ("original_position", "item_index", "duplicate_ordinal"):
            values = dict(
                original_position=0,
                item_index=1,
                item_signature=signature,
                duplicate_ordinal=0,
            )
            values[field] = True
            with self.subTest(field=field), self.assertRaises((TypeError, ValueError)):
                OfflineOccurrence(**values)
        with self.assertRaises((TypeError, ValueError)):
            OfflineOccurrence(0, 1, list(signature), 0)
        with self.assertRaises((TypeError, ValueError)):
            OfflineOccurrence(0, 2, signature, 0)


class SkeletonIntentTests(unittest.TestCase):
    def test_exact_tuple_float_orientation_and_finiteness_contract(self):
        occurrence = build_offline_occurrences([_raw(1)])[0]
        base = dict(
            occurrence=occurrence,
            container_ordinal=0,
            orientation=0,
            local_position=(0.0, 0.0, 0.1),
            support_kind=SupportKind.FLOOR,
            supporter_occurrences=(),
            alternative_count=1,
            support_margin=0.8,
            clearance_margin=0.02,
        )
        invalid = (
            {"container_ordinal": True},
            {"orientation": 6},
            {"orientation": True},
            {"local_position": [0.0, 0.0, 0.1]},
            {"local_position": np.asarray((0.0, 0.0, 0.1), dtype=np.float64)},
            {"local_position": (0, 0.0, 0.1)},
            {"local_position": (0.0, math.inf, 0.1)},
            {"support_kind": "floor"},
            {"supporter_occurrences": []},
            {"alternative_count": 0},
            {"support_margin": 1},
            {"clearance_margin": math.nan},
        )
        for change in invalid:
            with self.subTest(change=change), self.assertRaises((TypeError, ValueError)):
                SkeletonIntent(**{**base, **change})

    def test_supporters_and_stable_key_are_immutable_and_canonical(self):
        occurrences = build_offline_occurrences([_raw(1), _raw(2)])
        value = SkeletonIntent(
            occurrence=occurrences[1],
            container_ordinal=1,
            orientation=2,
            local_position=(0.1, 0.2, 0.3),
            support_kind=SupportKind.PLACED_TOP,
            supporter_occurrences=(occurrences[0],),
            alternative_count=3,
            support_margin=0.75,
            clearance_margin=0.018,
        )

        self.assertIsInstance(value.stable_key, tuple)
        self.assertEqual(value.stable_key, copy.deepcopy(value).stable_key)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            value.orientation = 1


class ModeAPlanTests(unittest.TestCase):
    def test_complete_plan_digest_recomputes_and_is_deterministic(self):
        occurrences = build_offline_occurrences([_raw(2), _raw(1), _raw(1)])
        order = (2, 0, 1)
        skeleton = _skeleton(occurrences)
        trace = _trace()
        digest = compute_mode_a_plan_digest(
            occurrences, order, skeleton, trace, MODE_A_PLAN_PROFILE_VERSION
        )
        plan = ModeAPlan(
            occurrences, order, skeleton, digest, trace,
            MODE_A_PLAN_PROFILE_VERSION,
        )

        self.assertEqual(plan.plan_digest, digest)
        self.assertEqual(
            digest,
            compute_mode_a_plan_digest(
                occurrences, order, skeleton, trace, MODE_A_PLAN_PROFILE_VERSION
            ),
        )
        self.assertEqual(
            len(
                {
                    compute_mode_a_plan_digest(
                        occurrences, order, skeleton, trace,
                        MODE_A_PLAN_PROFILE_VERSION,
                    )
                    for _ in range(20)
                }
            ),
            1,
        )

    def test_semantic_plan_digest_ignores_wall_clock_elapsed(self):
        occurrences = build_offline_occurrences([_raw(2), _raw(1)])
        skeleton = _skeleton(occurrences)
        first = _trace()
        second = dataclasses.replace(first, elapsed_seconds=9.75)

        self.assertEqual(
            compute_mode_a_plan_digest(
                occurrences, (1, 0), skeleton, first,
                MODE_A_PLAN_PROFILE_VERSION,
            ),
            compute_mode_a_plan_digest(
                occurrences, (1, 0), skeleton, second,
                MODE_A_PLAN_PROFILE_VERSION,
            ),
        )

    def test_authoritative_occurrences_require_dense_ordered_positions_and_ordinals(self):
        canonical = build_offline_occurrences([_raw(4), _raw(4), _raw(5)])
        invalid_sets = (
            (canonical[1], canonical[0], canonical[2]),
            (dataclasses.replace(canonical[0], original_position=2), canonical[1], canonical[2]),
            (canonical[0], dataclasses.replace(canonical[1], duplicate_ordinal=0), canonical[2]),
            (canonical[0], dataclasses.replace(canonical[1], duplicate_ordinal=3), canonical[2]),
        )
        for occurrences in invalid_sets:
            with self.subTest(keys=tuple(value.stable_key for value in occurrences)):
                with self.assertRaises(ValueError):
                    compute_mode_a_plan_digest(
                        occurrences,
                        tuple(value.original_position for value in occurrences),
                        _skeleton(occurrences),
                        _trace(),
                        MODE_A_PLAN_PROFILE_VERSION,
                    )

    def test_intents_and_supporters_require_full_authoritative_identity(self):
        occurrences = build_offline_occurrences([_raw(4), _raw(5)])
        base = _skeleton(occurrences)
        changed_mass = OfflineOccurrence(
            0,
            4,
            (4, 0.2, 0.2, 0.2, 9.0, False, False, None),
            0,
        )
        changed_index = OfflineOccurrence(
            0,
            8,
            (8, 0.2, 0.2, 0.2, 1.0, False, False, None),
            0,
        )
        changed_ordinal = dataclasses.replace(occurrences[0], duplicate_ordinal=2)
        for forged in (changed_mass, changed_index, changed_ordinal):
            forged_intent = dataclasses.replace(base[0], occurrence=forged)
            with self.subTest(kind="intent", forged=forged.stable_key), self.assertRaises(ValueError):
                compute_mode_a_plan_digest(
                    occurrences,
                    (0, 1),
                    (forged_intent, base[1]),
                    _trace(),
                    MODE_A_PLAN_PROFILE_VERSION,
                )
            forged_supporter = dataclasses.replace(
                base[1],
                support_kind=SupportKind.PLACED_TOP,
                supporter_occurrences=(forged,),
            )
            with self.subTest(kind="supporter", forged=forged.stable_key), self.assertRaises(ValueError):
                compute_mode_a_plan_digest(
                    occurrences,
                    (0, 1),
                    (base[0], forged_supporter),
                    _trace(),
                    MODE_A_PLAN_PROFILE_VERSION,
                )

    def test_completeness_rejects_40_of_41_and_duplicate_omission(self):
        occurrences = build_offline_occurrences([_raw(index) for index in range(41)])
        with self.assertRaises(ValueError):
            ModeAPlan(
                occurrences,
                tuple(range(40)),
                _skeleton(occurrences),
                "bad",
                _trace(),
                MODE_A_PLAN_PROFILE_VERSION,
            )
        duplicate_order = tuple(range(40)) + (39,)
        with self.assertRaises(ValueError):
            ModeAPlan(
                occurrences,
                duplicate_order,
                _skeleton(occurrences),
                "bad",
                _trace(),
                MODE_A_PLAN_PROFILE_VERSION,
            )

    def test_plan_rejects_partial_skeleton_fallback_and_nested_unsafe_values(self):
        occurrences = build_offline_occurrences([_raw(0), _raw(1)])
        with self.assertRaises(ValueError):
            ModeAPlan(
                occurrences,
                (0, 1),
                _skeleton(occurrences)[:1],
                "bad",
                _trace(),
                MODE_A_PLAN_PROFILE_VERSION,
            )
        with self.assertRaises(ValueError):
            ModeAPlan(
                occurrences,
                (0, 1),
                _skeleton(occurrences),
                "bad",
                _trace(complete=False, fallback_reason="incomplete"),
                MODE_A_PLAN_PROFILE_VERSION,
            )
        unsafe_signature = (0, 0.2, 0.2, 0.2, 1.0, False, False, {"item_idx": 0})
        proposal = PlacementProposal(0, 0, 0, 0, (0.0, 0.0, 0.1), "unsafe")
        receipt = object.__new__(ValidatedRoot)
        for nested in (unsafe_signature[-1], proposal, receipt, np.asarray((1.0,))):
            with self.subTest(nested=type(nested).__name__), self.assertRaises((TypeError, ValueError)):
                OfflineOccurrence(
                    0,
                    0,
                    (0, 0.2, 0.2, 0.2, 1.0, False, False, nested),
                    0,
                )

    def test_finalize_fails_closed_to_original_order_and_none(self):
        occurrences = build_offline_occurrences([_raw(8), _raw(2), _raw(3)])
        original = (0, 1, 2)
        for order, skeleton, trace in (
            ((2, 1), _skeleton(occurrences), _trace()),
            ((2, 1, 0), _skeleton(occurrences)[:2], _trace()),
            ((2, 1, 0), _skeleton(occurrences), _trace(complete=False, fallback_reason="quota")),
        ):
            with self.subTest(order=order, skeleton=len(skeleton)):
                returned, plan = finalize_mode_a_plan(
                    occurrences, order, skeleton, trace
                )
                self.assertEqual(returned, original)
                self.assertIsNone(plan)

        returned, plan = finalize_mode_a_plan(
            occurrences, (2, 1, 0), _skeleton(occurrences), _trace()
        )
        self.assertEqual(returned, (2, 1, 0))
        self.assertIsInstance(plan, ModeAPlan)

    def test_trace_has_exact_bounded_types(self):
        for change in (
            {"nodes": True},
            {"fit_tests": -1},
            {"elapsed_seconds": 1},
            {"elapsed_seconds": math.inf},
            {"complete": 1},
            {"fallback_reason": None},
        ):
            values = dataclasses.asdict(_trace())
            values.update(change)
            with self.subTest(change=change), self.assertRaises((TypeError, ValueError)):
                ModeAOptimizeTrace(**values)


class HistoricalSeedTests(unittest.TestCase):
    def test_golden_historical_rigid_heavy_footprint_volume_order(self):
        raw = [
            _raw(10, mass=3.0, length=0.2, width=0.2, height=0.2),
            _raw(11, mass=5.0, length=0.1, width=0.3, height=0.2),
            _raw(12, mass=5.0, length=0.2, width=0.2, height=0.2),
            _raw(13, mass=5.0, length=0.2, width=0.2, height=0.3),
            _raw(14, mass=99.0, priority=True),
            _raw(15, mass=100.0, soft=True),
        ]
        occurrences = build_offline_occurrences(raw)

        # Historical tuple: group, -mass, -max pair footprint, -volume,
        # -largest dimension, item index; occurrence position is the safe tie.
        self.assertEqual(
            historical_static_order_seed(raw, occurrences),
            (3, 1, 2, 0, 4, 5),
        )

    def test_seed_is_occurrence_stable_and_duplicate_safe_for_twenty_runs(self):
        raw = [_raw(4), _raw(4), _raw(4), _raw(2)]
        occurrences = build_offline_occurrences(raw)
        outputs = {
            historical_static_order_seed(raw, occurrences) for _ in range(20)
        }

        self.assertEqual(len(outputs), 1)
        result = outputs.pop()
        self.assertEqual(Counter(result), Counter(range(4)))
        self.assertEqual(result, (3, 0, 1, 2))

    def test_seed_rejects_forged_duplicate_ordinal(self):
        raw = [_raw(4), _raw(4)]
        occurrences = build_offline_occurrences(raw)
        forged = (occurrences[0], dataclasses.replace(occurrences[1], duplicate_ordinal=7))

        with self.assertRaises(ValueError):
            historical_static_order_seed(raw, forged)

    def test_new_modules_do_not_import_historical_or_search_implementations(self):
        package = (
            SIMULATOR_ROOT
            / "agents"
            / "support_extreme_fusion_beam_exact_mask"
        )
        forbidden = ("highscore", "high_score", "submit", "ems", "mcts", "beam", "fixed_quota")
        for name in ("mode_a_types.py", "mode_a_seeds.py"):
            tree = ast.parse((package / name).read_text(encoding="utf-8"))
            imports = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports.extend(alias.name.lower() for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    imports.append((node.module or "").lower())
            self.assertFalse(
                any(word in value for value in imports for word in forbidden),
                (name, imports),
            )


if __name__ == "__main__":
    unittest.main()
