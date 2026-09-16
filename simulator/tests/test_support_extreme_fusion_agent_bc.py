from __future__ import annotations

import ast
from dataclasses import replace
import inspect
import pathlib
import sys
import time
import unittest
from unittest.mock import patch

import numpy as np


SIMULATOR_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(SIMULATOR_ROOT) not in sys.path:
    sys.path.insert(0, str(SIMULATOR_ROOT))

from agents.support_extreme_fusion_beam_exact_mask.agent import (  # noqa: E402
    Agent,
    CandidateZeroError,
    NotReadyError,
    PlanningError,
)
from agents.support_extreme_fusion_beam_exact_mask.catalog import (  # noqa: E402
    CatalogStats,
    RootCatalog,
    RootRecord,
    StrictRootScanner,
)
from agents.support_extreme_fusion_beam_exact_mask.mask import ExactMask  # noqa: E402
from agents.support_extreme_fusion_beam_exact_mask.model import AABB  # noqa: E402
from agents.support_extreme_fusion_beam_exact_mask.settings import SearchSettings  # noqa: E402
from agents.support_extreme_fusion_beam_exact_mask.state import build_packing_state  # noqa: E402
from tests.replay_support import load_observation_snapshot  # noqa: E402


def _container() -> dict:
    length, width, height, thickness = 3.0, 1.8, 1.8, 0.04
    return {
        "index": 41,
        "length": length,
        "width": width,
        "height": height,
        "thickness": thickness,
        "cut_x": 0.40,
        "cut_y": 0.40,
        "center": (0.0, 0.0, height / 2.0),
        "points": [
            [length / 2.0 - thickness, 0.0, 0.0],
            [-length / 2.0 + thickness, 0.0, 0.0],
            [0.0, width / 2.0 - thickness, 0.0],
            [0.0, -width / 2.0 + thickness, 0.0],
            [0.0, 0.0, height - thickness],
            [0.0, 0.0, thickness],
        ],
        "n_vecs": [
            [1.0, 0.0, 0.0],
            [-1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, -1.0, 0.0],
            [0.0, 0.0, 1.0],
            [0.0, 0.0, -1.0],
        ],
        "volume": length * width * height,
        "shelf": False,
        "is_prioritized": False,
        "packed_items": [],
    }


def _item(index: int, *, side: float = 0.20) -> dict:
    return {
        "index": index,
        "length": side,
        "width": side,
        "height": side,
        "mass": 3.0,
        "is_prioritized": False,
        "is_soft": False,
    }


def _strict_catalog(settings: SearchSettings, containers: list[dict], pool: list[dict]):
    state = build_packing_state(containers)
    mask = ExactMask(settings)
    scanner = StrictRootScanner(
        settings,
        mask=mask,
        per_pool_cap=2,
        global_cap=4,
        first_pass_raw_cap=16,
    )
    catalog = scanner.scan(state, pool, deadline=time.perf_counter() + 5.0)
    if not catalog:
        raise AssertionError("test fixture must expose a strict root")
    return state, catalog


class _RecordingScanner:
    def __init__(self, catalog: RootCatalog, *, error: Exception | None = None) -> None:
        self.catalog = catalog
        self.error = error
        self.calls: list[dict] = []

    def scan(self, state, pool, **kwargs):
        self.calls.append({"state": state, "pool": tuple(pool), **kwargs})
        if self.error is not None:
            raise self.error
        return self.catalog


class _RecordingBeam:
    def __init__(self, root, *, error: Exception | None = None) -> None:
        self.root = root
        self.error = error
        self.b_calls: list[dict] = []
        self.c_calls: list[dict] = []

    def choose_b(self, state, pool, catalog, deadline):
        self.b_calls.append(
            {"state": state, "pool": tuple(pool), "catalog": catalog, "deadline": deadline}
        )
        if self.error is not None:
            raise self.error
        return self.root

    def choose_c(self, state, pool, catalog, deadline):
        self.c_calls.append(
            {"state": state, "pool": tuple(pool), "catalog": catalog, "deadline": deadline}
        )
        if self.error is not None:
            raise self.error
        return self.root


class _MutableClock:
    def __init__(self, now: float) -> None:
        self.now = float(now)

    def __call__(self) -> float:
        return self.now


class AgentBCIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.containers = [_container()]
        self.pool = [_item(7)]

    def _wired_agent(self, *, lookahead: int, pool: list[dict] | None = None):
        pool = self.pool if pool is None else pool
        agent = Agent("support_extreme_fusion_beam_exact_mask")
        agent.get_init_states(
            {"optimize": False, "lookahead_k": lookahead, "container_list": self.containers}
        )
        state, catalog = _strict_catalog(agent.settings, self.containers, pool)
        scanner = _RecordingScanner(catalog)
        beam = _RecordingBeam(catalog.roots[0])
        agent.scanner = scanner
        agent.beam = beam
        return agent, state, catalog, scanner, beam

    def test_init_owns_strict_components_installs_revalidator_and_fixes_mode(self) -> None:
        agent = Agent("support_extreme_fusion_beam_exact_mask")
        self.assertIsInstance(agent.exact_mask, ExactMask)
        self.assertIsInstance(agent.scanner, StrictRootScanner)
        self.assertIs(agent.scanner.mask, agent.exact_mask)
        self.assertIs(agent.beam.mask, agent.exact_mask)
        self.assertIsNotNone(agent._exact_revalidator)

        agent.get_init_states(
            {"optimize": False, "lookahead_k": 10, "container_list": self.containers}
        )
        self.assertEqual(agent.mode, "B")
        self.assertEqual(agent.mode, "B")
        agent.get_init_states(
            {"optimize": False, "lookahead_k": 1, "container_list": self.containers}
        )
        self.assertEqual(agent.mode, "C")
        agent.get_init_states(
            {"optimize": True, "lookahead_k": 40, "container_list": self.containers}
        )
        self.assertEqual(agent.mode, "A")

    def test_real_c_and_b_tail_return_exact_public_action(self) -> None:
        for lookahead, expected_mode in ((1, "C"), (10, "B")):
            with self.subTest(mode=expected_mode):
                agent = Agent("support_extreme_fusion_beam_exact_mask")
                agent.get_init_states(
                    {
                        "optimize": False,
                        "lookahead_k": lookahead,
                        "container_list": self.containers,
                    }
                )
                action = agent.policy(
                    {"container_list": self.containers, "pool_list": list(self.pool)}
                )
                self.assertEqual(agent.mode, expected_mode)
                self.assertEqual(set(action), {"item_idx", "container_idx", "place_pos", "orientation"})
                self.assertEqual(action["item_idx"], 0)
                self.assertIs(type(action["container_idx"]), int)
                self.assertIs(type(action["orientation"]), int)
                self.assertEqual(action["place_pos"].shape, (3,))
                self.assertEqual(action["place_pos"].dtype, np.float32)

    def test_b_tail_invokes_b_and_c_invokes_c_without_cross_mode_fallback(self) -> None:
        for lookahead, b_count, c_count in ((10, 1, 0), (1, 0, 1)):
            with self.subTest(lookahead=lookahead):
                agent, _, _, _, beam = self._wired_agent(lookahead=lookahead)
                action = agent.policy(
                    {"container_list": self.containers, "pool_list": list(self.pool)}
                )
                self.assertEqual(action["item_idx"], 0)
                self.assertEqual(len(beam.b_calls), b_count)
                self.assertEqual(len(beam.c_calls), c_count)

    def test_deadline_contract_uses_absolute_budgets_and_output_reserve(self) -> None:
        agent, _, _, scanner, beam = self._wired_agent(lookahead=10)
        agent._clock = lambda: 100.0
        action = agent.policy(
            {"container_list": self.containers, "pool_list": list(self.pool)}
        )
        self.assertEqual(action["item_idx"], 0)
        self.assertAlmostEqual(scanner.calls[0]["deadline"], 105.45)
        self.assertAlmostEqual(beam.b_calls[0]["deadline"], 105.30)
        self.assertAlmostEqual(agent.settings.normal_catalog_limit_seconds, 1.80)
        self.assertAlmostEqual(agent.settings.bc_planning_limit_seconds, 5.45)
        self.assertAlmostEqual(agent.settings.bc_policy_hard_limit_seconds, 5.75)
        self.assertAlmostEqual(
            agent.settings.bc_policy_hard_limit_seconds
            - agent.settings.bc_planning_limit_seconds,
            agent.settings.bc_output_reserve_seconds,
        )

    def test_late_strict_catalog_uses_depth_zero_incumbent_without_calling_beam(self) -> None:
        agent, _, catalog, _, beam = self._wired_agent(lookahead=10)
        clock = _MutableClock(100.0)

        class LateScanner(_RecordingScanner):
            def scan(scanner_self, state, pool, **kwargs):
                result = super().scan(state, pool, **kwargs)
                clock.now = 105.45
                return result

        agent._clock = clock
        agent.scanner = LateScanner(catalog)
        with patch.object(
            agent, "format_validated_action", wraps=agent.format_validated_action
        ) as formatter:
            action = agent.policy(
                {"container_list": self.containers, "pool_list": list(self.pool)}
            )

        self.assertEqual(action["item_idx"], 0)
        self.assertEqual(len(beam.b_calls), 0)
        selected_root = formatter.call_args.args[0]
        self.assertTrue(any(selected_root is root for root in catalog.roots))

    def test_deadline_incumbent_rank_prefers_safety_height_then_stable_key(self) -> None:
        agent, _, catalog, _, _ = self._wired_agent(lookahead=10)
        base = catalog.records[0]

        def record(
            support: float,
            clearance: float,
            minimum_z: float,
            maximum_z: float,
            position_x: float,
        ) -> RootRecord:
            proposal = replace(
                base.proposal,
                position=(position_x, base.proposal.position[1], base.proposal.position[2]),
            )
            box = AABB(
                (base.root.box.minimum[0], base.root.box.minimum[1], minimum_z),
                (base.root.box.maximum[0], base.root.box.maximum[1], maximum_z),
            )
            root = replace(
                base.root,
                proposal=proposal,
                box=box,
                proposal_key=("rank-fixture", position_x),
                support_ratio=support,
                min_clearance=clearance,
            )
            return replace(base, root=root)

        records = (
            record(0.80, 0.90, 0.10, 0.30, -0.30),
            record(0.90, 0.20, 0.10, 0.30, -0.20),
            record(0.90, 0.30, 0.20, 0.50, -0.10),
            record(0.90, 0.30, 0.10, 0.50, 0.10),
            record(0.90, 0.30, 0.10, 0.50, -0.10),
        )
        ranked_catalog = RootCatalog(records, CatalogStats(accepted_roots=len(records)))

        selected = agent._deadline_incumbent(ranked_catalog)

        self.assertIs(selected, records[-1].root)

    def test_beam_none_after_deadline_uses_catalog_incumbent(self) -> None:
        agent, _, catalog, scanner, _ = self._wired_agent(lookahead=10)
        clock = _MutableClock(100.0)

        class DeadlineNoneBeam(_RecordingBeam):
            def choose_b(beam_self, state, pool, current_catalog, deadline):
                beam_self.b_calls.append(
                    {
                        "state": state,
                        "pool": tuple(pool),
                        "catalog": current_catalog,
                        "deadline": deadline,
                    }
                )
                clock.now = 105.30
                return None

        beam = DeadlineNoneBeam(None)
        agent._clock = clock
        agent.scanner = scanner
        agent.beam = beam
        with patch.object(
            agent, "format_validated_action", wraps=agent.format_validated_action
        ) as formatter:
            action = agent.policy(
                {"container_list": self.containers, "pool_list": list(self.pool)}
            )

        self.assertEqual(action["item_idx"], 0)
        self.assertEqual(len(beam.b_calls), 1)
        selected_root = formatter.call_args.args[0]
        self.assertTrue(any(selected_root is root for root in catalog.roots))

    def test_fresh_receipt_finishing_at_hard_deadline_emits_no_action(self) -> None:
        agent, _, catalog, _, beam = self._wired_agent(lookahead=10)
        clock = _MutableClock(100.0)

        class LateScanner(_RecordingScanner):
            def scan(scanner_self, state, pool, **kwargs):
                result = super().scan(state, pool, **kwargs)
                clock.now = 105.45
                return result

        agent._clock = clock
        agent.scanner = LateScanner(catalog)
        original_revalidate = agent.exact_mask.revalidate
        revalidations: list[object] = []

        def record_revalidation(*args):
            revalidations.append(args[2])
            result = original_revalidate(*args)
            clock.now = 105.75
            return result

        agent.install_exact_revalidator(record_revalidation)
        with self.assertRaisesRegex(PlanningError, "hard deadline"):
            agent.policy({"container_list": self.containers, "pool_list": list(self.pool)})
        self.assertEqual(len(revalidations), 1)
        self.assertEqual(len(beam.b_calls), 0)
        self.assertIsNone(agent._active_output_deadline)

    def test_empty_or_root_zero_raises_without_formatter(self) -> None:
        agent = Agent("support_extreme_fusion_beam_exact_mask")
        agent.get_init_states(
            {"optimize": False, "lookahead_k": 1, "container_list": self.containers}
        )
        with self.assertRaisesRegex(CandidateZeroError, "empty.*pool"):
            agent.policy({"container_list": self.containers, "pool_list": []})
        agent.scanner = _RecordingScanner(RootCatalog.empty(1))
        with patch.object(
            agent, "format_validated_action", wraps=agent.format_validated_action
        ) as formatter:
            with self.assertRaisesRegex(CandidateZeroError, "strict root"):
                agent.policy({"container_list": self.containers, "pool_list": list(self.pool)})
            formatter.assert_not_called()

    def test_state_scanner_beam_and_formatter_fail_closed(self) -> None:
        malformed = dict(_container())
        malformed["points"] = [[0.0, 0.0]]
        agent = Agent("support_extreme_fusion_beam_exact_mask")
        agent.get_init_states(
            {"optimize": False, "lookahead_k": 1, "container_list": [malformed]}
        )
        with self.assertRaisesRegex(PlanningError, "state"):
            agent.policy({"container_list": [malformed], "pool_list": list(self.pool)})

        for stage in ("scanner", "beam"):
            with self.subTest(stage=stage):
                agent, _, catalog, scanner, beam = self._wired_agent(lookahead=1)
                if stage == "scanner":
                    agent.scanner = _RecordingScanner(catalog, error=RuntimeError("scan boom"))
                else:
                    agent.beam = _RecordingBeam(catalog.roots[0], error=RuntimeError("beam boom"))
                with self.assertRaisesRegex(PlanningError, stage):
                    agent.policy(
                        {"container_list": self.containers, "pool_list": list(self.pool)}
                    )

        agent, _, _, _, _ = self._wired_agent(lookahead=1)
        agent.install_exact_revalidator(lambda *_args: (_ for _ in ()).throw(RuntimeError("format boom")))
        with self.assertRaisesRegex(PlanningError, "format"):
            agent.policy({"container_list": self.containers, "pool_list": list(self.pool)})

    def test_pool_order_and_duplicate_occurrences_remain_receipt_bound(self) -> None:
        original = [_item(81, side=0.18), _item(82, side=0.22)]
        agent, _, catalog, _, _ = self._wired_agent(lookahead=1, pool=original)
        agent.scanner = _RecordingScanner(catalog)
        agent.beam = _RecordingBeam(catalog.roots[0])
        with self.assertRaisesRegex(PlanningError, "format"):
            agent.policy(
                {"container_list": self.containers, "pool_list": list(reversed(original))}
            )

        duplicates = [_item(90, side=0.18), _item(90, side=0.18)]
        duplicate_agent = Agent("support_extreme_fusion_beam_exact_mask")
        duplicate_agent.get_init_states(
            {"optimize": False, "lookahead_k": 1, "container_list": self.containers}
        )
        action = duplicate_agent.policy(
            {"container_list": self.containers, "pool_list": duplicates}
        )
        self.assertIn(action["item_idx"], (0, 1))

    def test_planner_root_must_be_identical_depth_zero_catalog_member(self) -> None:
        agent, _, catalog, _, beam = self._wired_agent(lookahead=1)
        beam.root = None
        with self.assertRaisesRegex(PlanningError, "no root"):
            agent.policy({"container_list": self.containers, "pool_list": list(self.pool)})

        agent, _, catalog, _, beam = self._wired_agent(lookahead=1)
        beam.root = type(catalog)(catalog.records, catalog.stats).roots[0]
        self.assertIs(beam.root, catalog.roots[0])
        # A separately scanned receipt is equivalent geometrically but is not
        # the caller catalog's depth-zero object.
        _, foreign_catalog = _strict_catalog(agent.settings, self.containers, self.pool)
        beam.root = foreign_catalog.roots[0]
        self.assertIsNot(beam.root, catalog.roots[0])
        with self.assertRaisesRegex(PlanningError, "catalog"):
            agent.policy({"container_list": self.containers, "pool_list": list(self.pool)})

    def test_step14_rejected_historical_actions_are_never_emitted(self) -> None:
        artifact = pathlib.Path(__file__).parent / "artifacts" / "task001_step14_control_failure.npz"
        observation, _metadata = load_observation_snapshot(artifact)
        agent = Agent("support_extreme_fusion_beam_exact_mask")
        agent.get_init_states(
            {
                "optimize": False,
                "lookahead_k": 1,
                "container_list": observation["container_list"],
            }
        )
        forbidden = {
            (4, 0, 0, (0.0, 0.492, 0.178)),
            (3, 0, 0, (-0.172, -0.2195, 0.193)),
        }
        try:
            action = agent.policy(observation)
        except (CandidateZeroError, PlanningError):
            return
        key = (
            action["item_idx"],
            action["container_idx"],
            action["orientation"],
            tuple(round(float(value), 4) for value in action["place_pos"]),
        )
        self.assertNotIn(key, forbidden)

    def test_step9_snapshot_has_strict_depth_zero_root_and_fresh_action(self) -> None:
        artifact = (
            pathlib.Path(__file__).parents[1]
            / "results"
            / "support_extreme_fusion"
            / "task001-b-seed42-e1-failure.npz"
        )
        observation, _metadata = load_observation_snapshot(artifact)
        agent = Agent("support_extreme_fusion_beam_exact_mask")
        agent.get_init_states(
            {
                "optimize": False,
                "lookahead_k": 10,
                "container_list": observation["container_list"],
            }
        )
        state = build_packing_state(
            observation["container_list"], observation.get("depth_map")
        )
        started = time.perf_counter()
        catalog = agent.scanner.scan(
            state,
            observation["pool_list"],
            deadline=started + 5.45,
        )
        elapsed = time.perf_counter() - started

        self.assertGreaterEqual(len(catalog), 1)
        self.assertLess(elapsed, 5.45)
        root = catalog.records[0].root
        self.assertIs(root, catalog.roots[0])
        action = agent.format_validated_action(
            root, state, observation["pool_list"]
        )
        self.assertEqual(action["item_idx"], root.proposal.pool_index)
        self.assertEqual(action["container_idx"], root.proposal.container_index)

    def test_uninitialized_stays_not_ready_while_mode_a_is_exact_or_fail_closed(self) -> None:
        agent = Agent("support_extreme_fusion_beam_exact_mask")
        with self.assertRaises(NotReadyError):
            agent.policy({"container_list": self.containers, "pool_list": list(self.pool)})
        agent.get_init_states(
            {"optimize": True, "lookahead_k": 1, "container_list": self.containers}
        )
        optimized = agent.optimize(list(self.pool))
        self.assertEqual(sorted(optimized), sorted(item["index"] for item in self.pool))
        try:
            action = agent.policy(
                {"container_list": self.containers, "pool_list": list(self.pool)}
            )
        except (CandidateZeroError, PlanningError):
            pass
        else:
            self.assertEqual(
                set(action), {"item_idx", "container_idx", "place_pos", "orientation"}
            )
            self.assertEqual(action["place_pos"].dtype, np.float32)
            self.assertEqual(action["place_pos"].shape, (3,))

    def test_policy_ast_has_no_unchecked_action_or_historical_fallback(self) -> None:
        source = inspect.getsource(sys.modules[Agent.__module__])
        tree = ast.parse(source)
        policy = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "policy"
        )
        self.assertFalse(any(isinstance(node, ast.Dict) for node in ast.walk(policy)))
        returns = [node for node in ast.walk(policy) if isinstance(node, ast.Return)]
        self.assertEqual(len(returns), 1)
        self.assertIsInstance(returns[0].value, ast.Call)
        self.assertEqual(returns[0].value.func.attr, "format_validated_action")
        lowered = source.lower()
        self.assertNotIn("highscore", lowered)
        self.assertNotIn("random", lowered)


if __name__ == "__main__":
    unittest.main()
