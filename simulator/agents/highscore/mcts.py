"""Deterministic anytime MPC-MCTS over the compressed EMS proxy state."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import random
import time
from typing import Any, Sequence

import numpy as np

from .catalog import RootAction
from .ems import ProxyAction, ProxyState, apply_action, propose_actions, state_key
from .model import Candidate, ItemSpec
from .settings import SearchSettings


class _DeadlineExpired(RuntimeError):
    """Internal signal used to abandon incomplete proxy work atomically."""


@dataclass(frozen=True, order=True)
class RolloutValue:
    """A root-aware lexicographic value; larger tuples are always preferred."""

    packed_count: int
    packed_volume: float
    neg_violations: int
    largest_space_volume: float
    minimum_ingress_slack: float
    neg_roughness: float
    neg_cog: float


@dataclass
class _Node:
    """Tree statistics for a proxy state; no exact action exists below the root."""

    state: Any
    remaining: tuple[tuple[int, Any], ...]
    action_key: tuple
    action: ProxyAction | None = None
    visits: int = 0
    total_scalar: float = 0.0
    best_value: RolloutValue | None = None
    children: list["_Node"] = field(default_factory=list)
    pending: list[ProxyAction] = field(default_factory=list)
    generated: bool = False
    terminal: bool = False


class MCTSSearch:
    def __init__(self, settings: SearchSettings):
        self.settings = settings
        self._cache: dict[tuple, tuple[ProxyAction, ...]] = {}
        self._last_nodes: list[_Node] = []
        self._last_root_values: tuple[RolloutValue | None, ...] = ()

    def _select_node_child(self, parent: _Node) -> _Node | None:
        """Select UCB child, making all ties independent of construction order."""
        children = [child for child in parent.children if not self._converged(child)]
        if not children:
            return None
        unvisited = [child for child in children if child.visits == 0]
        if unvisited:
            return min(unvisited, key=lambda child: child.action_key)
        log_parent = math.log(max(1, parent.visits))
        return min(
            children,
            key=lambda child: (
                -(
                    child.total_scalar / child.visits
                    + self.settings.mcts_exploration
                    * math.sqrt(log_parent / child.visits)
                ),
                child.action_key,
            ),
        )

    @staticmethod
    def _action_key(action: ProxyAction) -> tuple:
        return (
            action.pool_index,
            action.item.index,
            action.container_index,
            action.orientation,
            *(int(round(float(value) / 0.001)) for value in action.box.minimum),
            *(int(round(float(value) / 0.001)) for value in action.box.maximum),
        )

    @classmethod
    def _root_key(cls, root: RootAction) -> tuple:
        return cls._action_key(root.proxy_action)

    @staticmethod
    def _remaining_after(
        remaining: tuple[tuple[int, ItemSpec], ...], pool_index: int
    ) -> tuple[tuple[int, ItemSpec], ...]:
        """Remove one visible-pool position, preserving duplicate ItemSpecs."""
        return tuple(entry for entry in remaining if entry[0] != pool_index)

    def _scalar(self, value: RolloutValue) -> float:
        """A bounded backup score; final decisions never use it by itself."""
        volume = value.packed_volume / (1.0 + max(0.0, value.packed_volume))
        largest = value.largest_space_volume / (1.0 + max(0.0, value.largest_space_volume))
        ingress = value.minimum_ingress_slack / (1.0 + max(0.0, value.minimum_ingress_slack))
        return float(
            value.packed_count
            + volume
            + 0.10 * value.neg_violations
            + 0.05 * largest
            + 0.05 * ingress
            + 0.01 * value.neg_roughness
            + 0.01 * value.neg_cog
        )

    @staticmethod
    def _check_deadline(deadline: float) -> None:
        if time.perf_counter() >= deadline:
            raise _DeadlineExpired

    @staticmethod
    def _secondary(root: RootAction) -> float:
        score = float(root.candidate.secondary_score)
        return score if math.isfinite(score) else -math.inf

    def _better_root(
        self,
        value: RolloutValue,
        root: RootAction,
        incumbent: tuple[RolloutValue, RootAction] | None,
    ) -> bool:
        if incumbent is None:
            return True
        prior_value, prior_root = incumbent
        if value != prior_value:
            return value > prior_value
        if self._secondary(root) != self._secondary(prior_root):
            return self._secondary(root) > self._secondary(prior_root)
        return self._root_key(root) < self._root_key(prior_root)

    @staticmethod
    def _minimal_value(root: RootAction) -> RolloutValue:
        """Cheap exact-root fallback if lower-order proxy features time out."""
        mass = max(0.0, float(root.candidate.item.mass))
        cog = float(root.candidate.box.center[2]) if mass else 0.0
        return RolloutValue(
            packed_count=1,
            packed_volume=float(root.candidate.item.volume),
            neg_violations=-int(root.candidate.rule_violations),
            largest_space_volume=0.0,
            minimum_ingress_slack=0.0,
            neg_roughness=0.0,
            neg_cog=-cog,
        )

    def _select_root(self, roots: Sequence[_Node]) -> _Node:
        unvisited = [node for node in roots if node.visits == 0]
        if unvisited:
            return min(unvisited, key=lambda node: node.action_key)
        total = max(1, sum(node.visits for node in roots))
        return min(
            roots,
            key=lambda node: (
                -(
                    node.total_scalar / max(1, node.visits)
                    + self.settings.mcts_exploration
                    * math.sqrt(math.log(total) / max(1, node.visits))
                ),
                node.action_key,
            ),
        )

    def _rank_actions(
        self,
        state: ProxyState,
        remaining: tuple[tuple[int, ItemSpec], ...],
        deadline: float,
    ) -> list[ProxyAction]:
        records: list[tuple[tuple, ProxyAction]] = []
        for pool_index, item in remaining:
            if time.perf_counter() >= deadline:
                break
            try:
                actions = propose_actions(
                    state,
                    item,
                    pool_index,
                    limit=max(1, min(24, self.settings.mcts_rollout_limit)),
                    deadline=deadline,
                )
            except Exception:
                continue
            for action in actions:
                if time.perf_counter() >= deadline:
                    break
                # Large, scarce items first; ties prefer low top faces and stable geometry.
                records.append(
                    ((-float(item.volume), float(action.box.maximum[2]), self._action_key(action)), action)
                )
        records.sort(key=lambda entry: entry[0])
        return [action for _, action in records]

    def _widen_limit(self, visits: int) -> int:
        return max(
            0,
            int(math.floor(
                self.settings.mcts_progressive_k
                * max(0, visits) ** self.settings.mcts_progressive_alpha
            )),
        )

    @staticmethod
    def _converged(node: _Node) -> bool:
        if node.terminal:
            return True
        return (
            node.generated
            and not node.pending
            and bool(node.children)
            and all(MCTSSearch._converged(child) for child in node.children)
        )

    def _expand(self, node: _Node, deadline: float) -> _Node | None:
        if node.terminal or time.perf_counter() >= deadline:
            return None
        if not node.remaining:
            node.terminal = True
            return None
        if not node.generated:
            node.pending = self._rank_actions(node.state, node.remaining, deadline)
            node.generated = True
        limit = self._widen_limit(node.visits)
        while node.pending and len(node.children) < limit:
            if time.perf_counter() >= deadline:
                return None
            action = node.pending.pop(0)
            try:
                successor = apply_action(node.state, action, self.settings.path_clearance)
            except Exception:
                continue
            if successor is None:
                continue
            child = _Node(
                state=successor,
                remaining=self._remaining_after(node.remaining, action.pool_index),
                action_key=self._action_key(action),
                action=action,
            )
            node.children.append(child)
            self._last_nodes.append(child)
            return child
        if node.generated and not node.pending and not node.children:
            node.terminal = True
        return None

    @staticmethod
    def _space_features(
        state: ProxyState,
        remaining: tuple[tuple[int, ItemSpec], ...],
        deadline: float,
    ) -> tuple[float, float, float]:
        MCTSSearch._check_deadline(deadline)
        if not state.spaces:
            return 0.0, 0.0, 0.0
        volumes: list[float] = []
        heights: list[float] = []
        for space in state.spaces:
            MCTSSearch._check_deadline(deadline)
            volumes.append(space.rect.area * max(0.0, space.max_height - space.bottom_z))
            heights.append(space.bottom_z)
        volumes_array = np.asarray(volumes, dtype=np.float64)
        heights_array = np.asarray(heights, dtype=np.float64)
        largest = float(np.max(volumes_array)) if len(volumes_array) else 0.0
        roughness = float(np.std(heights_array)) if len(heights_array) else 0.0
        if not remaining:
            return largest, 0.0, roughness
        slacks: list[float] = []
        for _, item in remaining:
            MCTSSearch._check_deadline(deadline)
            best = 0.0
            for space in state.spaces:
                MCTSSearch._check_deadline(deadline)
                slack = min(
                    space.rect.max_x - space.rect.min_x - item.length,
                    space.rect.max_y - space.rect.min_y - item.width,
                )
                best = max(best, slack)
            slacks.append(max(0.0, float(best)))
        return largest, min(slacks, default=0.0), roughness

    def _value(
        self,
        root: RootAction,
        actions: Sequence[ProxyAction],
        leaf: ProxyState,
        remaining: tuple[tuple[int, ItemSpec], ...],
        deadline: float,
    ) -> RolloutValue:
        self._check_deadline(deadline)
        all_items = [root.candidate.item]
        centers = [float(root.candidate.box.center[2])]
        for action in actions:
            self._check_deadline(deadline)
            all_items.append(action.item)
            centers.append(float(action.box.center[2]))
        masses_list: list[float] = []
        for item in all_items:
            self._check_deadline(deadline)
            masses_list.append(max(0.0, float(item.mass)))
        masses = np.asarray(masses_list, dtype=np.float64)
        mass_total = float(np.sum(masses))
        cog = float(np.dot(masses, np.asarray(centers, dtype=np.float64)) / mass_total) if mass_total else 0.0
        largest, ingress, roughness = self._space_features(leaf, remaining, deadline)
        packed_volume = 0.0
        for item in all_items:
            self._check_deadline(deadline)
            packed_volume += float(item.volume)
        return RolloutValue(
            packed_count=len(all_items),
            packed_volume=packed_volume,
            neg_violations=-int(root.candidate.rule_violations),
            largest_space_volume=largest,
            minimum_ingress_slack=ingress,
            neg_roughness=-roughness,
            neg_cog=-cog,
        )

    def _rollout(
        self,
        state: ProxyState,
        remaining: tuple[tuple[int, ItemSpec], ...],
        rng: random.Random,
        deadline: float,
    ) -> tuple[tuple[ProxyAction, ...], ProxyState, tuple[tuple[int, ItemSpec], ...]]:
        actions: list[ProxyAction] = []
        current = state
        left = remaining
        seen_keys: set[tuple] = set()
        for _ in range(max(0, self.settings.mcts_rollout_limit)):
            if time.perf_counter() >= deadline or not left:
                break
            key = state_key(current, tuple(item.index for _, item in left), self.settings.mcts_transposition_quantum)
            if key in seen_keys:
                break
            seen_keys.add(key)
            cached = self._cache.get(key)
            cached_is_visible = cached is not None and all(
                any(
                    pool_index == action.pool_index and item.index == action.item.index
                    for pool_index, item in left
                )
                for action in cached
            )
            if cached_is_visible:
                advanced = False
                for action in cached:
                    if time.perf_counter() >= deadline:
                        break
                    try:
                        successor = apply_action(current, action, self.settings.path_clearance)
                    except Exception:
                        successor = None
                    if successor is None:
                        break
                    actions.append(action)
                    current = successor
                    left = self._remaining_after(left, action.pool_index)
                    advanced = True
                if advanced:
                    continue
                break
            if cached is not None:
                # Keys intentionally use ItemSpec IDs; pool positions still govern removal.
                self._cache.pop(key, None)
            ranked = self._rank_actions(current, left, deadline)
            if not ranked:
                self._cache[key] = ()
                break
            picked: ProxyAction | None = None
            successor: ProxyState | None = None
            candidates = ranked[:3]
            while candidates and time.perf_counter() < deadline:
                action = candidates.pop(rng.randrange(len(candidates)))
                try:
                    trial = apply_action(current, action, self.settings.path_clearance)
                except Exception:
                    trial = None
                if trial is not None:
                    picked, successor = action, trial
                    break
            if picked is None or successor is None:
                self._cache[key] = ()
                break
            self._cache[key] = (picked,)
            actions.append(picked)
            current = successor
            left = self._remaining_after(left, picked.pool_index)
        return tuple(actions), current, left

    def _backup(self, path: Sequence[_Node], value: RolloutValue, *, deadline: float) -> bool:
        """Preflight all deadline checks before mutating any node statistics."""
        for _ in path:
            if time.perf_counter() >= deadline:
                return False
        scalar = self._scalar(value)
        for node in path:
            node.visits += 1
            node.total_scalar += scalar
            if node.best_value is None or value > node.best_value:
                node.best_value = value
        return True

    def choose(
        self,
        roots: Sequence[RootAction],
        pool: Sequence[ItemSpec],
        *,
        deadline: float,
        seed: int,
    ) -> Candidate | None:
        """Return only the best exact root candidate available before ``deadline``."""
        if not roots:
            return None
        start = time.perf_counter()
        deadline = min(
            deadline,
            start + max(0.0, float(self.settings.mcts_policy_limit_seconds)),
        )
        if start >= deadline:
            return None
        self._cache = {}
        self._last_nodes = []
        rng = random.Random(seed)
        visible = tuple(enumerate(pool))
        root_nodes: list[tuple[RootAction, _Node]] = []
        incumbent: tuple[RolloutValue, RootAction] | None = None

        for root in sorted(roots, key=self._root_key):
            remaining = self._remaining_after(visible, root.candidate.pool_index)
            node = _Node(root.next_state, remaining, self._root_key(root), terminal=not remaining)
            node.visits = 1
            try:
                baseline = self._value(root, (), root.next_state, remaining, deadline)
            except _DeadlineExpired:
                baseline = self._minimal_value(root)
            except Exception:
                continue
            node.best_value = baseline
            node.total_scalar = self._scalar(baseline)
            root_nodes.append((root, node))
            self._last_nodes.append(node)
            if self._better_root(baseline, root, incumbent):
                incumbent = (baseline, root)

        while root_nodes and time.perf_counter() < deadline:
            nodes = [node for _, node in root_nodes if not self._converged(node)]
            if not nodes:
                break
            node = self._select_root(nodes)
            root = next(root for root, candidate_node in root_nodes if candidate_node is node)
            path = [node]
            current = node
            try:
                while time.perf_counter() < deadline:
                    if current.terminal:
                        break
                    expanded = self._expand(current, deadline)
                    if expanded is not None:
                        current = expanded
                        path.append(current)
                        break
                    selected = self._select_node_child(current)
                    if selected is None:
                        break
                    current = selected
                    path.append(current)
                if current.terminal:
                    tail, leaf, left = (), current.state, current.remaining
                else:
                    tail, leaf, left = self._rollout(current.state, current.remaining, rng, deadline)
                path_actions = tuple(node.action for node in path[1:] if node.action is not None) + tail
                value = self._value(root, path_actions, leaf, left, deadline)
                if not self._backup(path, value, deadline=deadline):
                    break
                if self._better_root(value, root, incumbent):
                    incumbent = (value, root)
            except _DeadlineExpired:
                break
            except Exception:
                # The incumbent was exact-validated before search began; retain it.
                current.terminal = True
                continue

        self._last_root_values = tuple(node.best_value for _, node in root_nodes)
        return incumbent[1].candidate if incumbent is not None else None
