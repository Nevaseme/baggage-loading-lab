import pathlib
import sys
import time
import unittest
from dataclasses import replace
from unittest.mock import patch

import numpy as np


SIMULATOR_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(SIMULATOR_ROOT) not in sys.path:
    sys.path.insert(0, str(SIMULATOR_ROOT))

from agents.highscore.agent import Agent  # noqa: E402
from agents.highscore import agent as agent_module  # noqa: E402
from agents.highscore.candidates import CandidateGenerator  # noqa: E402
from agents.highscore.catalog import RootAction, build_root_catalog  # noqa: E402
from agents.highscore.model import AABB, Candidate, ItemSpec, PlacedItem  # noqa: E402
from agents.highscore.planner import Planner  # noqa: E402
from agents.highscore.scoring import CandidateScorer  # noqa: E402
from agents.highscore.settings import SearchSettings  # noqa: E402
from agents.highscore.state import build_packing_state  # noqa: E402
from simulator.tests.replay_support import load_observation_snapshot  # noqa: E402
from simulator.tests.test_highscore_candidates import container_dict, item_dict  # noqa: E402


class ScoringTests(unittest.TestCase):
    def test_heavy_item_candidate_is_ranked_lower_when_placed_higher(self):
        settings = SearchSettings()
        state = build_packing_state([container_dict()])
        item = ItemSpec.from_dict(item_dict())
        candidates = CandidateGenerator(settings).generate(state, item, pool_index=0)
        low = min(candidates, key=lambda candidate: candidate.position[2])
        high = max(candidates, key=lambda candidate: candidate.position[2])
        scorer = CandidateScorer(settings)

        self.assertGreaterEqual(scorer.score(state, low), scorer.score(state, high))

    def test_mass_weighted_centre_of_gravity_penalizes_a_heavy_high_item(self):
        packed = [
            {
                **item_dict(20, pos=(0.0, 0.0, 0.16), orn=(0.0, 0.0, 0.0, 1.0)),
                "mass": 100.0,
            }
        ]
        state = build_packing_state([container_dict(packed=packed)])
        light = ItemSpec.from_dict({**item_dict(21), "mass": 1.0})
        heavy = ItemSpec.from_dict({**item_dict(22), "mass": 100.0})
        template = CandidateGenerator(SearchSettings()).generate(
            build_packing_state([container_dict()]), light, pool_index=0
        )[0]
        high_box = type(template.box).from_center_half((0.5, 0.4, 1.2), template.box.half)
        light_high = replace(template, item=light, position=(0.5, 0.4, 1.2), box=high_box)
        heavy_high = replace(template, item=heavy, position=(0.5, 0.4, 1.2), box=high_box)
        scorer = CandidateScorer(SearchSettings())

        self.assertGreater(scorer.score(state, light_high), scorer.score(state, heavy_high))


class PlannerTests(unittest.TestCase):
    def test_online_planner_returns_a_valid_designated_priority_action(self):
        settings = SearchSettings()
        state = build_packing_state(
            [container_dict(index=0), container_dict(index=1, offset_x=2.0, prioritized=True)]
        )
        pool = [ItemSpec.from_dict(item_dict(1)), ItemSpec.from_dict(item_dict(2, prioritized=True))]
        planner = Planner(settings)
        candidate = planner.choose_online(state, pool, deadline=time.perf_counter() + 2.0)

        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.pool_index, 1)
        self.assertEqual(candidate.container_index, 1)
        self.assertGreater(candidate.future_feasible, 0.0)

    def test_offline_order_is_a_complete_permutation_and_starts_with_constrained_items(self):
        settings = SearchSettings(optimize_limit_seconds=0.5)
        state = build_packing_state([container_dict()])
        items = [
            ItemSpec.from_dict(item_dict(10)),
            ItemSpec.from_dict(item_dict(11, soft=True)),
            ItemSpec.from_dict(item_dict(12, prioritized=True)),
        ]
        order, skeleton = Planner(settings).optimize_order(
            state, items, deadline=time.perf_counter() + 0.5
        )

        self.assertEqual(set(order), {10, 11, 12})
        self.assertEqual(len(order), 3)
        self.assertIn(order[0], {11, 12})
        self.assertLessEqual(len(skeleton), 3)

    def test_choose_mpc_scores_exact_catalog_roots_and_uses_shared_deadlines(self):
        state = build_packing_state([container_dict()])
        pool = [ItemSpec.from_dict(item_dict(1)), ItemSpec.from_dict(item_dict(2))]
        planner = Planner(SearchSettings(mcts_policy_limit_seconds=5.40, ems_root_budget_seconds=1.35))
        first = AgentContractTests._candidate(pool[0], 0)
        second = AgentContractTests._candidate(pool[1], 1)
        roots = [
            RootAction(first, object(), object()),
            RootAction(second, object(), object()),
        ]
        catalog_deadlines = []
        mcts_deadlines = []
        scored = []
        test_case = self

        class Clock:
            now = 100.0

            def __call__(self):
                return self.now

        class Scorer:
            def score(self, scored_state, candidate):
                test_case.assertIs(scored_state, state)
                scored.append(candidate)
                return candidate.secondary_score

        clock = Clock()
        planner.scorer = Scorer()

        def fake_catalog(*args, deadline, **kwargs):
            catalog_deadlines.append(deadline)
            clock.now = 101.0
            return roots

        class FakeMCTS:
            def __init__(self, settings):
                test_case.assertIs(settings, planner.settings)

            def choose(self, received_roots, received_pool, *, deadline, seed):
                mcts_deadlines.append(deadline)
                test_case.assertEqual(received_roots, roots)
                test_case.assertEqual(list(received_pool), pool)
                test_case.assertIsInstance(seed, int)
                return second

        with patch("agents.highscore.planner.time.perf_counter", clock), patch(
            "agents.highscore.planner.build_root_catalog", fake_catalog
        ), patch("agents.highscore.planner.MCTSSearch", FakeMCTS):
            chosen = planner.choose_mpc(state, pool, deadline=110.0, seed=73)

        self.assertIs(chosen, second)
        self.assertEqual(scored, [first, second])
        self.assertEqual(catalog_deadlines, [101.35])
        self.assertEqual(mcts_deadlines, [105.4])

    def test_choose_mpc_returns_none_when_catalog_raises(self):
        state = build_packing_state([container_dict()])
        planner = Planner(SearchSettings())
        with patch(
            "agents.highscore.planner.build_root_catalog",
            side_effect=RuntimeError("catalog failed"),
        ):
            self.assertIsNone(
                planner.choose_mpc(
                    state,
                    [ItemSpec.from_dict(item_dict(1))],
                    deadline=time.perf_counter() + 1.0,
                    seed=1,
                )
            )

    def test_choose_mpc_filters_bad_scored_roots_and_keeps_exact_incumbent_when_mcts_fails(self):
        state = build_packing_state([container_dict()])
        pool = [ItemSpec.from_dict(item_dict(1)), ItemSpec.from_dict(item_dict(2))]
        planner = Planner(SearchSettings())
        first = self._root(pool[0], 0, score=4.0)
        bad = self._root(pool[1], 1, score=99.0)
        received = []

        class Scorer:
            def score(self, scored_state, candidate):
                if candidate is bad.candidate:
                    raise RuntimeError("bad score")
                return candidate.secondary_score

        class FailingMCTS:
            def __init__(self, settings):
                pass

            def choose(self, roots, pool, *, deadline, seed):
                received.extend(roots)
                raise RuntimeError("mcts failed")

        planner.scorer = Scorer()
        with patch("agents.highscore.planner.build_root_catalog", return_value=[first, bad]), patch(
            "agents.highscore.planner.MCTSSearch", FailingMCTS
        ):
            chosen = planner.choose_mpc(
                state, pool, deadline=time.perf_counter() + 1.0, seed=7
            )

        self.assertIs(chosen, first.candidate)
        self.assertEqual(received, [first])

    def test_choose_mpc_returns_best_scored_exact_incumbent_when_scoring_reaches_deadline(self):
        state = build_packing_state([container_dict()])
        pool = [ItemSpec.from_dict(item_dict(1)), ItemSpec.from_dict(item_dict(2))]
        planner = Planner(SearchSettings(mcts_policy_limit_seconds=5.40))
        lower = self._root(pool[0], 0, score=1.0)
        better = self._root(pool[1], 1, score=2.0)

        class Clock:
            now = 10.0

            def __call__(self):
                return self.now

        clock = Clock()

        class Scorer:
            def score(self, scored_state, candidate):
                clock.now = 15.4
                return candidate.secondary_score

        planner.scorer = Scorer()
        with patch("agents.highscore.planner.time.perf_counter", clock), patch(
            "agents.highscore.planner.build_root_catalog", return_value=[lower, better]
        ), patch("agents.highscore.planner.MCTSSearch") as mcts:
            chosen = planner.choose_mpc(state, pool, deadline=20.0, seed=9)

        self.assertIs(chosen, lower.candidate)
        mcts.assert_not_called()

    @staticmethod
    def _root(item, pool_index, *, score=0.0):
        candidate = AgentContractTests._candidate(item, pool_index, score=score)
        return RootAction(candidate, object(), object())

    def test_stable_mpc_seed_changes_for_visible_item_and_packed_aabb(self):
        state = build_packing_state([container_dict()])
        pool = [ItemSpec.from_dict(item_dict(1))]
        initial = Planner.stable_mpc_seed(state, pool)
        self.assertEqual(initial, Planner.stable_mpc_seed(state, pool))

        changed_item = [ItemSpec.from_dict(item_dict(2))]
        self.assertNotEqual(initial, Planner.stable_mpc_seed(state, changed_item))

        changed_state = state.clone()
        changed_state.containers[0].placed.append(
            PlacedItem(
                pool[0],
                AABB.from_center_half((0.2, 0.1, 0.2), (0.1, 0.1, 0.1)),
            )
        )
        self.assertNotEqual(initial, Planner.stable_mpc_seed(changed_state, pool))

    def test_stable_mpc_seed_is_deterministic_for_a_64_by_64_depth_observation(self):
        state = build_packing_state([container_dict()], np.ones((1, 64, 64), dtype=np.float32))
        pool = [ItemSpec.from_dict(item_dict(1))]
        started = time.perf_counter()
        first = Planner.stable_mpc_seed(state, pool)
        second = Planner.stable_mpc_seed(state, pool)
        self.assertEqual(first, second)
        self.assertLess(time.perf_counter() - started, 1.0)

    def test_choose_mpc_snapshot_action_is_a_fresh_exact_root_not_last_resort(self):
        artifact = SIMULATOR_ROOT / "tests" / "artifacts" / "task001_step23_failure.npz"
        observation, _ = load_observation_snapshot(artifact)
        state = build_packing_state(observation["container_list"], observation["depth_map"])
        pool = [ItemSpec.from_dict(raw) for raw in observation["pool_list"]]
        settings = SearchSettings(mcts_policy_limit_seconds=0.50, ems_root_budget_seconds=0.30)
        planner = Planner(settings)
        chosen = planner.choose_mpc(
            state,
            pool,
            deadline=time.perf_counter() + 0.50,
            seed=Planner.stable_mpc_seed(state, pool),
        )

        self.assertIsNotNone(chosen)
        fresh_roots = build_root_catalog(
            state, pool, planner.generator, settings, deadline=time.perf_counter() + 0.30
        )
        self.assertTrue(any(root.candidate is chosen or (
            root.candidate.pool_index == chosen.pool_index
            and root.candidate.container_index == chosen.container_index
            and root.candidate.orientation == chosen.orientation
            and np.allclose(root.candidate.position, chosen.position)
        ) for root in fresh_roots))
        agent = Agent(str(SIMULATOR_ROOT / "agents" / "highscore"))
        agent.settings = replace(agent.settings, use_mpc_mcts_ems=True, mcts_policy_limit_seconds=0.50, ems_root_budget_seconds=0.30)
        agent.planner = Planner(agent.settings)
        action = agent.policy(observation)
        self.assertTrue(any(
            root.candidate.pool_index == action["item_idx"]
            and root.candidate.container_index == action["container_idx"]
            and root.candidate.orientation == action["orientation"]
            and np.allclose(root.candidate.position, action["place_pos"])
            for root in fresh_roots
        ))
        fallback = agent._deterministic_last_resort(observation, pool)
        self.assertFalse(
            action["item_idx"] == fallback["item_idx"]
            and action["container_idx"] == fallback["container_idx"]
            and action["orientation"] == fallback["orientation"]
            and np.allclose(action["place_pos"], fallback["place_pos"])
        )

    def test_agent_mpc_one_item_uses_real_terminal_mcts_exact_root_promptly(self):
        observation = {"container_list": [container_dict()], "pool_list": [item_dict(7)]}
        state = build_packing_state(observation["container_list"])
        pool = [ItemSpec.from_dict(observation["pool_list"][0])]
        settings = SearchSettings(use_mpc_mcts_ems=True, mcts_policy_limit_seconds=1.0)
        source_planner = Planner(settings)
        roots = build_root_catalog(
            state, pool, source_planner.generator, settings, deadline=time.perf_counter() + 0.5
        )
        self.assertTrue(roots)
        agent = Agent(str(SIMULATOR_ROOT / "agents" / "highscore"))
        agent.settings = settings
        agent.planner = Planner(settings)
        started = time.perf_counter()
        with patch("agents.highscore.planner.build_root_catalog", return_value=roots), patch.object(
            agent.planner, "choose_online", side_effect=AssertionError("legacy route is forbidden")
        ):
            action = agent.policy(observation)

        self.assertLess(time.perf_counter() - started, 0.5)
        self.assertTrue(any(
            root.candidate.pool_index == action["item_idx"]
            and root.candidate.container_index == action["container_idx"]
            and root.candidate.orientation == action["orientation"]
            and np.allclose(root.candidate.position, action["place_pos"])
            for root in roots
        ))


class AgentContractTests(unittest.TestCase):
    @staticmethod
    def _candidate(item, pool_index, *, score=0.0, violations=0, support=1.0, clearance=1.0):
        box = AABB.from_center_half((0.25, 0.1, 0.2), (0.1, 0.1, 0.1))
        return Candidate(
            item=item,
            pool_index=pool_index,
            container_index=0,
            orientation=0,
            position=tuple(float(value) for value in box.center),
            box=box,
            support_ratio=support,
            min_clearance=clearance,
            rule_violations=violations,
            secondary_score=score,
        )

    def test_policy_rebuilds_a_no_depth_state_only_after_primary_returns_none(self):
        agent = Agent(str(SIMULATOR_ROOT / "agents" / "highscore"))
        agent.settings = replace(agent.settings, use_geometry_rescue=True)
        containers = [container_dict()]
        item = ItemSpec.from_dict(item_dict(3))
        rescue_candidate = self._candidate(item, 0)

        class DepthSensitiveGenerator:
            def generate(self, state, candidate_item, pool_index, **kwargs):
                if state.containers[0].depth_map is not None:
                    return []
                return [rescue_candidate]

        class Scorer:
            def score(self, state, candidate):
                return candidate.secondary_score

        class EmptyPrimaryPlanner:
            generator = DepthSensitiveGenerator()
            scorer = Scorer()

            def choose_online(self, state, pool, *, deadline):
                self.primary_had_depth = state.containers[0].depth_map is not None
                return None

        planner = EmptyPrimaryPlanner()
        agent.planner = planner
        observation = {
            "container_list": containers,
            "pool_list": [item_dict(3)],
            "depth_map": np.ones((1, 64, 64), dtype=np.float32),
        }

        action = agent.policy(observation)

        self.assertTrue(planner.primary_had_depth)
        np.testing.assert_allclose(action["place_pos"], rescue_candidate.position)

    def test_policy_does_not_run_geometry_rescue_when_primary_returns_a_candidate(self):
        agent = Agent(str(SIMULATOR_ROOT / "agents" / "highscore"))
        containers = [container_dict()]
        item = ItemSpec.from_dict(item_dict(3))
        primary_candidate = self._candidate(item, 0)

        class UnusedGenerator:
            def generate(self, *args, **kwargs):
                raise AssertionError("geometry rescue must not run")

        class PrimaryPlanner:
            generator = UnusedGenerator()
            scorer = object()

            def choose_online(self, state, pool, *, deadline):
                return primary_candidate

        agent.planner = PrimaryPlanner()
        observation = {
            "container_list": containers,
            "pool_list": [item_dict(3)],
            "depth_map": np.ones((1, 64, 64), dtype=np.float32),
        }

        action = agent.policy(observation)

        np.testing.assert_allclose(action["place_pos"], primary_candidate.position)

    def test_policy_routes_mpc_flag_only_to_choose_mpc_and_preserves_container_identifier(self):
        agent = Agent(str(SIMULATOR_ROOT / "agents" / "highscore"))
        containers = [container_dict(index=0), container_dict(index=1, offset_x=2.0)]
        item = ItemSpec.from_dict(item_dict(3))
        mpc_candidate = replace(self._candidate(item, 0), container_index=1)
        seen = []

        class MPCPlanner:
            def choose_mpc(self, state, pool, *, deadline, seed):
                seen.append((deadline, seed))
                return mpc_candidate

            def choose_online(self, *args, **kwargs):
                raise AssertionError("legacy planner must not run when MPC is enabled")

        agent.settings = replace(agent.settings, use_mpc_mcts_ems=True)
        agent.planner = MPCPlanner()
        action = agent.policy({"container_list": containers, "pool_list": [item_dict(3)]})

        self.assertEqual(len(seen), 1)
        self.assertEqual(action["container_idx"], 1)
        self.assertEqual(action["item_idx"], 0)

    def test_policy_mpc_failure_uses_existing_depth_emergency_hard_deadline(self):
        agent = Agent(str(SIMULATOR_ROOT / "agents" / "highscore"))
        containers = [container_dict()]
        item = ItemSpec.from_dict(item_dict(3))
        emergency = self._candidate(item, 0, support=1.0)
        seen = []

        class Generator:
            def generate(self, state, candidate_item, pool_index, *, deadline, **kwargs):
                seen.append(deadline)
                return [emergency]

        class Scorer:
            def score(self, state, candidate):
                return candidate.secondary_score

        class FailingMPCPlanner:
            generator = Generator()
            scorer = Scorer()

            def choose_mpc(self, state, pool, *, deadline, seed):
                raise RuntimeError("search failed")

            def choose_online(self, *args, **kwargs):
                raise AssertionError("legacy planner must not run when MPC is enabled")

        class Clock:
            def __call__(self):
                return 10.0

        agent.settings = replace(agent.settings, use_mpc_mcts_ems=True, use_geometry_rescue=False)
        agent.planner = FailingMPCPlanner()
        with patch.object(agent_module.time, "perf_counter", Clock()):
            action = agent.policy({"container_list": containers, "pool_list": [item_dict(3)]})

        self.assertEqual(seen, [15.75])
        np.testing.assert_allclose(action["place_pos"], emergency.position)

    def test_policy_uses_the_legacy_depth_aware_emergency_when_rescue_is_disabled(self):
        agent = Agent(str(SIMULATOR_ROOT / "agents" / "highscore"))
        containers = [container_dict()]
        item = ItemSpec.from_dict(item_dict(3))
        higher_score = self._candidate(item, 0, score=10.0, support=0.8)
        emergency_candidate = replace(
            self._candidate(item, 0, score=-10.0, support=1.0),
            orientation=1,
            position=(0.35, 0.1, 0.2),
        )
        generated_depth_states = []

        class Generator:
            def generate(self, state, item, pool_index, **kwargs):
                generated_depth_states.append(state.containers[0].depth_map is not None)
                return [higher_score, emergency_candidate]

        class Scorer:
            def score(self, state, candidate):
                return candidate.secondary_score

        class EmptyPrimaryPlanner:
            generator = Generator()
            scorer = Scorer()

            def choose_online(self, state, pool, *, deadline):
                return None

        agent.settings = replace(agent.settings, use_geometry_rescue=False)
        agent.planner = EmptyPrimaryPlanner()
        observation = {
            "container_list": containers,
            "pool_list": [item_dict(3), item_dict(4)],
            "depth_map": np.ones((1, 64, 64), dtype=np.float32),
        }

        action = agent.policy(observation)

        self.assertEqual(generated_depth_states, [True])
        self.assertEqual(action["orientation"], 1)
        np.testing.assert_allclose(action["place_pos"], emergency_candidate.position)

    def test_geometry_rescue_collects_all_items_and_uses_the_documented_rank(self):
        agent = Agent(str(SIMULATOR_ROOT / "agents" / "highscore"))
        containers = [container_dict()]
        pool = [ItemSpec.from_dict(item_dict(1)), ItemSpec.from_dict(item_dict(2))]

        class Generator:
            def generate(self, state, item, pool_index, **kwargs):
                return [AgentContractTests._candidate(item, pool_index, score=float(item.index))]

        class Scorer:
            def score(self, state, candidate):
                return candidate.secondary_score

        class RescuePlanner:
            generator = Generator()
            scorer = Scorer()

        agent.planner = RescuePlanner()

        candidate = agent._geometry_rescue(
            {"container_list": containers},
            pool,
            time.perf_counter() + 1.0,
        )

        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.pool_index, 1)

    def test_geometry_rescue_fairly_slices_the_remaining_hard_deadline(self):
        agent = Agent(str(SIMULATOR_ROOT / "agents" / "highscore"))
        containers = [container_dict()]
        pool = [ItemSpec.from_dict(item_dict(index)) for index in range(3)]
        seen_deadlines = []

        class Generator:
            def generate(self, state, item, pool_index, *, deadline, **kwargs):
                seen_deadlines.append(deadline)
                return []

        class RescuePlanner:
            generator = Generator()
            scorer = object()

        agent.planner = RescuePlanner()
        hard_deadline = time.perf_counter() + 3.0

        candidate = agent._geometry_rescue(
            {"container_list": containers},
            pool,
            hard_deadline,
        )

        self.assertIsNone(candidate)
        self.assertEqual(len(seen_deadlines), 3)
        self.assertLess(seen_deadlines[0], hard_deadline - 1.5)
        self.assertLess(seen_deadlines[1], hard_deadline - 0.5)
        self.assertLessEqual(seen_deadlines[2], hard_deadline)

    def test_geometry_rescue_stops_scoring_at_the_hard_deadline(self):
        agent = Agent(str(SIMULATOR_ROOT / "agents" / "highscore"))
        containers = [container_dict()]
        pool = [ItemSpec.from_dict(item_dict(1)), ItemSpec.from_dict(item_dict(2))]
        first = self._candidate(pool[0], 0, score=1.0)
        second = self._candidate(pool[0], 0, score=2.0)
        generated_items = []
        scored = []

        class Clock:
            now = 0.0

            def __call__(self):
                return self.now

        clock = Clock()

        class Generator:
            def generate(self, state, item, pool_index, **kwargs):
                generated_items.append(item.index)
                return [first, second]

        class SlowScorer:
            def score(self, state, candidate):
                scored.append(candidate)
                clock.now = 10.0
                return candidate.secondary_score

        class RescuePlanner:
            generator = Generator()
            scorer = SlowScorer()

        agent.planner = RescuePlanner()
        with patch.object(agent_module.time, "perf_counter", clock):
            candidate = agent._geometry_rescue(
                {"container_list": containers},
                pool,
                hard_deadline=10.0,
            )

        self.assertIs(candidate, first)
        self.assertEqual(scored, [first])
        self.assertEqual(generated_items, [1])

    def test_geometry_rescue_keeps_best_when_later_generation_raises(self):
        agent = Agent(str(SIMULATOR_ROOT / "agents" / "highscore"))
        containers = [container_dict()]
        pool = [ItemSpec.from_dict(item_dict(1)), ItemSpec.from_dict(item_dict(2))]
        first = self._candidate(pool[0], 0, score=1.0)

        class Generator:
            def generate(self, state, item, pool_index, **kwargs):
                if item.index == 1:
                    return [first]
                raise RuntimeError("candidate generation failed")

        class Scorer:
            def score(self, state, candidate):
                return candidate.secondary_score

        class RescuePlanner:
            generator = Generator()
            scorer = Scorer()

        agent.planner = RescuePlanner()

        candidate = agent._geometry_rescue(
            {"container_list": containers},
            pool,
            time.perf_counter() + 1.0,
        )

        self.assertIs(candidate, first)

    def test_geometry_rescue_keeps_best_when_later_scoring_raises(self):
        agent = Agent(str(SIMULATOR_ROOT / "agents" / "highscore"))
        containers = [container_dict()]
        pool = [ItemSpec.from_dict(item_dict(1)), ItemSpec.from_dict(item_dict(2))]
        first = self._candidate(pool[0], 0, score=1.0)
        second = self._candidate(pool[1], 1, score=2.0)

        class Generator:
            def generate(self, state, item, pool_index, **kwargs):
                return [first if item.index == 1 else second]

        class Scorer:
            def score(self, state, candidate):
                if candidate is second:
                    raise RuntimeError("candidate scoring failed")
                return candidate.secondary_score

        class RescuePlanner:
            generator = Generator()
            scorer = Scorer()

        agent.planner = RescuePlanner()

        candidate = agent._geometry_rescue(
            {"container_list": containers},
            pool,
            time.perf_counter() + 1.0,
        )

        self.assertIs(candidate, first)

    def test_policy_returns_exact_action_contract_for_short_final_pool(self):
        agent = Agent(str(SIMULATOR_ROOT / "agents" / "highscore"))
        containers = [container_dict()]
        agent.get_init_states(
            {"optimize": False, "lookahead_k": 10, "container_list": containers}
        )
        observation = {
            "optimize": False,
            "lookahead_k": 10,
            "container_list": containers,
            "pool_list": [item_dict(3)],
            "depth_map": np.full((1, 64, 64), 1.5, dtype=np.float32),
        }
        action = agent.policy(observation)

        self.assertEqual(set(action), {"item_idx", "container_idx", "place_pos", "orientation"})
        self.assertEqual(action["item_idx"], 0)
        self.assertIsInstance(action["item_idx"], int)
        self.assertIsInstance(action["container_idx"], int)
        self.assertIsInstance(action["orientation"], int)
        self.assertEqual(action["place_pos"].shape, (3,))
        self.assertEqual(action["place_pos"].dtype, np.float32)

    def test_optimize_guards_the_complete_index_permutation(self):
        agent = Agent(str(SIMULATOR_ROOT / "agents" / "highscore"))
        containers = [container_dict()]
        agent.get_init_states(
            {"optimize": True, "lookahead_k": 1, "container_list": containers}
        )
        raw_items = [item_dict(5), item_dict(8, soft=True), item_dict(13, prioritized=True)]
        order = agent.optimize(raw_items)
        self.assertEqual(set(order), {5, 8, 13})
        self.assertEqual(len(order), 3)

    def test_optimize_rejects_complete_order_when_skeleton_is_incomplete(self):
        agent = Agent(str(SIMULATOR_ROOT / "agents" / "highscore"))
        agent.get_init_states(
            {"optimize": True, "lookahead_k": 1, "container_list": [container_dict()]}
        )
        incomplete_skeleton = [object(), object()]

        class IncompletePlanner:
            def optimize_order(self, state, items, *, deadline):
                return [13, 5, 8], incomplete_skeleton

        agent.planner = IncompletePlanner()
        agent.offline_skeleton = [object()]

        order = agent.optimize([item_dict(5), item_dict(8, soft=True), item_dict(13, prioritized=True)])

        self.assertEqual(order, [5, 8, 13])
        self.assertEqual(agent.offline_skeleton, [])

    def test_optimize_accepts_complete_order_with_full_skeleton(self):
        agent = Agent(str(SIMULATOR_ROOT / "agents" / "highscore"))
        agent.get_init_states(
            {"optimize": True, "lookahead_k": 1, "container_list": [container_dict()]}
        )
        full_skeleton = [object(), object(), object()]

        class CompletePlanner:
            def optimize_order(self, state, items, *, deadline):
                return [13, 5, 8], full_skeleton

        agent.planner = CompletePlanner()

        order = agent.optimize([item_dict(5), item_dict(8, soft=True), item_dict(13, prioritized=True)])

        self.assertEqual(order, [13, 5, 8])
        self.assertIs(agent.offline_skeleton, full_skeleton)


if __name__ == "__main__":
    unittest.main()
