import pathlib
import random
import sys
import time
import unittest
from unittest.mock import patch


SIMULATOR_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(SIMULATOR_ROOT) not in sys.path:
    sys.path.insert(0, str(SIMULATOR_ROOT))

from agents.highscore.catalog import RootAction  # noqa: E402
from agents.highscore.ems import EMS, ProxyAction, ProxyState, state_key  # noqa: E402
from agents.highscore.mcts import MCTSSearch, RolloutValue, _DeadlineExpired, _Node  # noqa: E402
from agents.highscore.model import AABB, Candidate, ItemSpec, Rect  # noqa: E402
from agents.highscore.settings import SearchSettings  # noqa: E402


class RolloutValueAndSelectionTests(unittest.TestCase):
    def test_rollout_value_is_root_lexicographic(self):
        """Catches final-root selection that trades a packed item for any lower metric."""
        three_items = RolloutValue(3, 0.10, -9, 0.0, 0.0, -9.0, -9.0)
        two_items = RolloutValue(2, 999.0, 0, 999.0, 999.0, 0.0, 0.0)
        more_volume = RolloutValue(3, 0.20, -9, 0.0, 0.0, -9.0, -9.0)
        fewer_violations = RolloutValue(3, 0.20, -1, 0.0, 0.0, -9.0, -9.0)

        self.assertGreater(three_items, two_items)
        self.assertGreater(more_volume, three_items)
        self.assertGreater(fewer_violations, more_volume)

    def test_ucb_prioritizes_unvisited_then_uses_stable_key(self):
        """Catches UCB selection that starves unexplored children or uses object identity ties."""
        search = MCTSSearch(SearchSettings())
        parent = _Node(state=None, remaining=(), action_key=())
        visited_low_key = _Node(state=None, remaining=(), action_key=(1,))
        visited_high_key = _Node(state=None, remaining=(), action_key=(2,))
        unvisited = _Node(state=None, remaining=(), action_key=(3,))
        visited_low_key.visits = visited_high_key.visits = 4
        visited_low_key.total_scalar = visited_high_key.total_scalar = 2.0
        parent.visits = 8

        parent.children = [visited_high_key, unvisited, visited_low_key]
        self.assertIs(search._select_node_child(parent), unvisited)

        parent.children.remove(unvisited)
        self.assertIs(search._select_node_child(parent), visited_low_key)


def _item(index, *, length=0.2, width=0.2, height=0.2, mass=1.0):
    return ItemSpec(index=index, length=length, width=width, height=height, mass=mass)


def _state(*placed_ids):
    return ProxyState(
        spaces=(EMS(Rect(0.0, 1.0, 0.0, 1.0), 0.0, 1.0, 0, (False, False)),),
        boxes=(),
        placed_ids=tuple(placed_ids),
    )


def _action(item, pool_index, marker):
    box = AABB.from_center_half((0.1 + marker / 100.0, 0.1, 0.1), (0.1, 0.1, 0.1))
    return ProxyAction(item, pool_index, 0, 0, box, (0, marker))


def _root(item, pool_index, marker):
    action = _action(item, pool_index, marker)
    candidate = Candidate(
        item=item,
        pool_index=pool_index,
        container_index=0,
        orientation=0,
        position=tuple(float(value) for value in action.box.center),
        box=action.box,
        support_ratio=1.0,
        min_clearance=1.0,
        secondary_score=100.0 - marker,
    )
    return RootAction(candidate, action, _state(marker))


class _StepClock:
    def __init__(self, step=0.001):
        self.value = 0.0
        self.step = step

    def __call__(self):
        now = self.value
        self.value += self.step
        return now


class _SequenceClock:
    """Controlled clock that records every deadline observation."""
    def __init__(self, values):
        self.values = iter(values)
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return next(self.values)


class AnytimeMCTSTests(unittest.TestCase):
    def setUp(self):
        self.settings = SearchSettings(
            mcts_progressive_k=1.0,
            mcts_progressive_alpha=0.5,
            mcts_rollout_limit=8,
        )
        self.pool = (_item(100), _item(101), _item(102))
        self.roots = (_root(self.pool[0], 0, 10), _root(self.pool[1], 1, 20))

    def _propose(self, state, item, pool_index, *, limit, deadline):
        marker = state.placed_ids[-1]
        if marker == 10 and item.index == 101:
            return [_action(item, pool_index, 11)]
        if marker == 20:
            if item.index == 100:
                return [_action(item, pool_index, 21)]
            if item.index == 102:
                return [_action(item, pool_index, 22)]
        if marker == 21 and item.index == 102:
            return [_action(item, pool_index, 22)]
        return []

    def _apply(self, state, action, clearance):
        marker = action.support_key[1]
        if marker == 11:
            return _state(10, 11)
        if marker == 21:
            return _state(20, 21)
        if marker == 22:
            return _state(*(state.placed_ids + (22,)))
        return None

    def _choose(self, seed):
        clock = _StepClock()
        with (
            patch("agents.highscore.mcts.propose_actions", side_effect=self._propose),
            patch("agents.highscore.mcts.apply_action", side_effect=self._apply),
            patch("agents.highscore.mcts.time.perf_counter", side_effect=clock),
        ):
            search = MCTSSearch(self.settings)
            chosen = search.choose(self.roots, self.pool, deadline=0.20, seed=seed)
        return chosen, search

    def test_choose_prefers_root_with_three_visible_items_and_is_deterministic(self):
        """Catches root ranking based on immediate height or scalar mean instead of rollouts."""
        first, first_search = self._choose(seed=7)
        second, second_search = self._choose(seed=7)

        self.assertIs(first, self.roots[1].candidate)
        self.assertIs(second, self.roots[1].candidate)
        self.assertEqual(first_search._last_root_values, second_search._last_root_values)
        self.assertTrue(
            all(
                len(node.children)
                <= int(self.settings.mcts_progressive_k * node.visits ** self.settings.mcts_progressive_alpha)
                for node in first_search._last_nodes
                if node.visits
            )
        )

    def test_deadline_and_node_exception_preserve_an_exact_incumbent(self):
        """Catches timeout/error fallbacks that return a proxy action or erase an exact root."""
        def broken_propose(state, item, pool_index, *, limit, deadline):
            if state.placed_ids[-1] == 20:
                raise RuntimeError("synthetic rollout failure")
            return self._propose(state, item, pool_index, limit=limit, deadline=deadline)

        clock = _StepClock(step=0.05)
        with (
            patch("agents.highscore.mcts.propose_actions", side_effect=broken_propose),
            patch("agents.highscore.mcts.apply_action", side_effect=self._apply),
            patch("agents.highscore.mcts.time.perf_counter", side_effect=clock),
        ):
            chosen = MCTSSearch(self.settings).choose(self.roots, self.pool, deadline=0.16, seed=3)

        self.assertIn(chosen, [root.candidate for root in self.roots])
        self.assertNotIsInstance(chosen, ProxyAction)

    def test_empty_or_expired_search_returns_none(self):
        self.assertIsNone(MCTSSearch(self.settings).choose((), self.pool, deadline=time.perf_counter() + 1.0, seed=0))
        self.assertIsNone(MCTSSearch(self.settings).choose(self.roots, self.pool, deadline=0.0, seed=0))

    def test_configured_policy_limit_caps_a_later_caller_deadline(self):
        """Catches a caller deadline bypassing the MCTS 5.40-second hard policy cap."""
        clock = _StepClock(step=0.5)
        settings = SearchSettings(mcts_policy_limit_seconds=0.0)
        with patch("agents.highscore.mcts.time.perf_counter", side_effect=clock):
            chosen = MCTSSearch(settings).choose(self.roots, self.pool, deadline=10.0, seed=0)
        self.assertIsNone(chosen)

    def test_transposition_cache_never_replays_a_removed_duplicate_pool_position(self):
        """Catches cache reuse that counts a duplicate ItemSpec from a no-longer-visible position."""
        duplicate_pool = (_item(500), _item(500), _item(501))
        current = _state(99)
        stale = _action(duplicate_pool[1], 1, 31)
        valid = _action(duplicate_pool[0], 0, 32)
        left = ((0, duplicate_pool[0]), (2, duplicate_pool[2]))
        search = MCTSSearch(self.settings)
        search._cache[state_key(current, (500, 501), self.settings.mcts_transposition_quantum)] = (stale,)

        with (
            patch("agents.highscore.mcts.propose_actions", return_value=[valid]),
            patch("agents.highscore.mcts.apply_action", return_value=_state(99, 32)),
        ):
            actions, _, _ = search._rollout(
                current, left, random.Random(0), time.perf_counter() + 1.0
            )

        self.assertEqual(actions[0].pool_index, 0)

    def test_terminal_and_actionless_roots_converge_before_policy_budget(self):
        """Catches a no-action tree repeatedly consuming the entire policy deadline."""
        clock = _StepClock(step=0.1)
        actionless_pool = (self.pool[0], self.pool[1])
        actionless_root = _root(actionless_pool[0], 0, 10)
        with (
            patch("agents.highscore.mcts.propose_actions", return_value=[]),
            patch("agents.highscore.mcts.time.perf_counter", side_effect=clock),
        ):
            chosen = MCTSSearch(self.settings).choose(
                (actionless_root,), actionless_pool, deadline=100.0, seed=1
            )
        self.assertIs(chosen, actionless_root.candidate)
        # The feature baseline performs several bounded clock reads; one search
        # pass remains far below the 5.40-second policy cap.
        self.assertLess(clock.value, 2.5)

    def test_cached_rollout_continues_through_successor_cache_entries(self):
        """Catches replay that stops after cache S -> A instead of continuing S1 -> B."""
        first, second = _item(600), _item(601)
        state, successor, terminal = _state(60), _state(61), _state(62)
        action_a, action_b = _action(first, 0, 61), _action(second, 1, 62)
        search = MCTSSearch(self.settings)
        search._cache[state_key(state, (600, 601), self.settings.mcts_transposition_quantum)] = (action_a,)
        search._cache[state_key(successor, (601,), self.settings.mcts_transposition_quantum)] = (action_b,)

        def apply(current, action, clearance):
            return successor if action is action_a else terminal

        with patch("agents.highscore.mcts.apply_action", side_effect=apply):
            actions, leaf, left = search._rollout(
                state, ((0, first), (1, second)), random.Random(0), time.perf_counter() + 1.0
            )
        self.assertEqual(actions, (action_a, action_b))
        self.assertIs(leaf, terminal)
        self.assertEqual(left, ())

    def test_equal_rollout_values_prefer_higher_finite_secondary_score(self):
        """Catches final-root ties that discard the existing exact candidate secondary score."""
        lower_key = _root(self.pool[0], 0, 10)
        higher_score = _root(self.pool[0], 0, 20)
        lower_key.candidate.secondary_score = 1.0
        higher_score.candidate.secondary_score = 9.0
        with patch("agents.highscore.mcts.time.perf_counter", side_effect=_StepClock(step=0.1)):
            chosen = MCTSSearch(self.settings).choose(
                (lower_key, higher_score), (self.pool[0],), deadline=10.0, seed=0
            )
        self.assertIs(chosen, higher_score.candidate)

    def test_bad_root_baseline_is_skipped_without_losing_prior_exact_incumbent(self):
        """Catches a feature exception from one root aborting an already exact incumbent."""
        good, bad = _root(self.pool[0], 0, 10), _root(self.pool[0], 0, 20)
        original = MCTSSearch._value

        def value_or_error(search, root, *args, **kwargs):
            if root is bad:
                raise RuntimeError("bad root feature")
            return original(search, root, *args, **kwargs)

        with (
            patch.object(MCTSSearch, "_value", new=value_or_error),
            patch("agents.highscore.mcts.time.perf_counter", side_effect=_StepClock(step=0.1)),
        ):
            chosen = MCTSSearch(self.settings).choose((good, bad), (self.pool[0],), deadline=10.0, seed=0)
        self.assertIs(chosen, good.candidate)

    def test_deadline_preflight_prevents_partial_backup_statistics(self):
        """Catches backup loops that partially mutate tree statistics after expiry."""
        nodes = [_Node(_state(), (), (index,)) for index in range(4)]
        value = RolloutValue(1, 1.0, 0, 0.0, 0.0, 0.0, 0.0)
        clock = _StepClock(step=0.1)
        with patch("agents.highscore.mcts.time.perf_counter", side_effect=clock):
            backed_up = MCTSSearch(self.settings)._backup(nodes, value, deadline=0.25)
        self.assertFalse(backed_up)
        self.assertTrue(all(node.visits == 0 and node.total_scalar == 0.0 for node in nodes))

    def test_value_deadline_checks_each_remaining_item_space_scan(self):
        """Catches a remaining-item best-fit generator scanning EMSs past deadline."""
        root = _root(self.pool[0], 0, 10)
        one_space = _state(10)
        two_spaces = ProxyState(one_space.spaces * 2, (), (10,))
        # Calls 1-7 cover value entry, mass, feature entry, two outer spaces,
        # item, and first inner comparison. Call 8 is the second inner EMS.
        clock = _SequenceClock((0.0,) * 7 + (1.0,))
        with patch("agents.highscore.mcts.time.perf_counter", side_effect=clock):
            with self.assertRaises(_DeadlineExpired):
                MCTSSearch(self.settings)._value(
                    root, (), two_spaces, ((1, self.pool[1]),), deadline=0.5
                )
        self.assertEqual(clock.calls, 8)

    def test_value_deadline_checks_each_item_volume_accumulation(self):
        """Catches an unchecked packed-volume sum after all earlier feature checks passed."""
        root = _root(self.pool[0], 0, 10)
        # With no spaces/actions, the final 1.0 can only be observed in a volume loop.
        no_spaces = ProxyState(spaces=(), boxes=(), placed_ids=(10,))
        clock = iter((0.0, 0.0, 0.0, 1.0))
        with patch("agents.highscore.mcts.time.perf_counter", side_effect=clock):
            with self.assertRaises(_DeadlineExpired):
                MCTSSearch(self.settings)._value(root, (), no_spaces, (), deadline=0.5)

    def test_inner_space_scan_expiry_keeps_minimal_exact_root_incumbent(self):
        """Catches a baseline feature expiry returning None instead of its exact root."""
        root = _root(self.pool[0], 0, 10)
        clock = iter((0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0))
        with patch("agents.highscore.mcts.time.perf_counter", side_effect=clock):
            chosen = MCTSSearch(self.settings).choose(
                (root,), (self.pool[0], self.pool[1]), deadline=0.5, seed=0
            )
        self.assertIs(chosen, root.candidate)

    def test_volume_accumulation_expiry_keeps_minimal_exact_root_incumbent(self):
        """Catches a volume-feature expiry returning None instead of its exact root."""
        root = _root(self.pool[0], 0, 10)
        root = RootAction(root.candidate, root.proxy_action, ProxyState((), (), (10,)))
        # Calls 1-4: choose start, value entry, mass, feature entry. Call 5
        # is the single volume-item check; call 6 exits the outer loop.
        clock = _SequenceClock((0.0,) * 4 + (1.0, 1.0))
        search = MCTSSearch(self.settings)
        with patch("agents.highscore.mcts.time.perf_counter", side_effect=clock):
            chosen = search.choose(
                (root,), (self.pool[0],), deadline=0.5, seed=0
            )
        self.assertIs(chosen, root.candidate)
        self.assertEqual(search._last_root_values, (search._minimal_value(root),))
        self.assertEqual(clock.calls, 6)


if __name__ == "__main__":
    unittest.main()
