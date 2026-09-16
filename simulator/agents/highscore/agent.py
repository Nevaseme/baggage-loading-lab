from __future__ import annotations

import time
from typing import Any

import numpy as np

from .model import Candidate, ItemSpec, PackingState
from .planner import Planner
from .settings import SearchSettings
from .state import build_packing_state


class Agent:
    def __init__(self, module_path: str):
        self.module_path = module_path
        self.settings = SearchSettings()
        self.planner = Planner(self.settings)
        self.optimize_enabled = False
        self.lookahead_k = 1
        self.initial_containers: list[dict] = []
        self.offline_skeleton: list[Candidate] = []

    def get_init_states(self, init_states: dict[str, Any]) -> bool:
        self.optimize_enabled = bool(init_states.get("optimize", False))
        self.lookahead_k = int(init_states.get("lookahead_k", 1))
        self.initial_containers = list(init_states.get("container_list", []))
        return True

    def optimize(self, item_list: list[dict[str, Any]]) -> list[int]:
        items = [ItemSpec.from_dict(value) for value in item_list]
        original = [item.index for item in items]
        deadline = time.perf_counter() + self.settings.optimize_limit_seconds
        try:
            state = build_packing_state(self.initial_containers)
            order, skeleton = self.planner.optimize_order(state, items, deadline=deadline)
            if (
                len(order) == len(original)
                and set(order) == set(original)
                and len(skeleton) == len(items)
            ):
                self.offline_skeleton = skeleton
                return [int(index) for index in order]
        except Exception:
            pass
        self.offline_skeleton = []
        return [int(index) for index in original]

    def policy(self, observation: dict[str, Any]) -> dict[str, Any]:
        raw_pool = list(observation.get("pool_list", []))
        if not raw_pool:
            return self._format_action(0, 0, (0.0, 0.0, 0.0), 0)

        pool = [ItemSpec.from_dict(value) for value in raw_pool]
        started = time.perf_counter()
        candidate: Candidate | None = None
        state = None
        try:
            state = build_packing_state(
                observation.get("container_list", self.initial_containers),
                observation.get("depth_map"),
            )
        except Exception:
            state = None

        if state is not None and self.settings.use_mpc_mcts_ems:
            policy_deadline = started + self.settings.mcts_policy_limit_seconds
            try:
                candidate = self.planner.choose_mpc(
                    state,
                    pool,
                    deadline=policy_deadline,
                    seed=Planner.stable_mpc_seed(state, pool),
                )
            except Exception:
                candidate = None
            emergency_deadline = started + self.settings.policy_hard_limit_seconds
            if candidate is None and time.perf_counter() < emergency_deadline:
                try:
                    if self.settings.use_geometry_rescue:
                        candidate = self._geometry_rescue(
                            observation,
                            pool,
                            emergency_deadline,
                        )
                    else:
                        candidate = self._depth_aware_emergency(
                            state,
                            pool,
                            emergency_deadline,
                        )
                except Exception:
                    candidate = None
        elif state is not None:
            # Preserve the default-off legacy route, including its exception boundary.
            try:
                deadline = started + self.settings.policy_soft_limit_seconds
                candidate = self.planner.choose_online(state, pool, deadline=deadline)
                emergency_deadline = started + self.settings.policy_hard_limit_seconds
                if candidate is None and time.perf_counter() < emergency_deadline:
                    if self.settings.use_geometry_rescue:
                        candidate = self._geometry_rescue(
                            observation,
                            pool,
                            emergency_deadline,
                        )
                    else:
                        candidate = self._depth_aware_emergency(
                            state,
                            pool,
                            emergency_deadline,
                        )
            except Exception:
                candidate = None

        if candidate is not None:
            pool_index = min(max(int(candidate.pool_index), 0), len(pool) - 1)
            container_index = min(
                max(int(candidate.container_index), 0),
                max(0, len(observation.get("container_list", self.initial_containers)) - 1),
            )
            return self._format_action(
                pool_index,
                container_index,
                candidate.position,
                candidate.orientation,
            )
        return self._deterministic_last_resort(observation, pool)

    def _depth_aware_emergency(
        self,
        state: PackingState,
        pool: list[ItemSpec],
        hard_deadline: float,
    ) -> Candidate | None:
        for pool_index, item in sorted(
            enumerate(pool),
            key=lambda pair: (pair[1].volume, min(pair[1].dimensions), pair[0]),
        ):
            generated = self.planner.generator.generate(
                state,
                item,
                pool_index,
                deadline=hard_deadline,
                allow_rule_violations=True,
            )
            if generated:
                for option in generated:
                    self.planner.scorer.score(state, option)
                return max(
                    generated,
                    key=lambda option: (
                        -option.rule_violations,
                        option.support_ratio,
                        option.min_clearance,
                        -option.position[2],
                    ),
                )
        return None

    def _geometry_rescue(
        self,
        observation: dict[str, Any],
        pool: list[ItemSpec],
        hard_deadline: float,
    ) -> Candidate | None:
        state = build_packing_state(
            observation.get("container_list", self.initial_containers)
        )
        ordered = sorted(
            enumerate(pool),
            key=lambda pair: (pair[1].volume, min(pair[1].dimensions), pair[0]),
        )
        best: Candidate | None = None
        for ordinal, (pool_index, item) in enumerate(ordered):
            now = time.perf_counter()
            if now >= hard_deadline:
                break
            remaining_items = len(ordered) - ordinal
            item_deadline = now + (hard_deadline - now) / remaining_items
            try:
                generated = self.planner.generator.generate(
                    state,
                    item,
                    pool_index,
                    deadline=item_deadline,
                    allow_rule_violations=True,
                )
            except Exception:
                continue
            for option in generated:
                if time.perf_counter() >= hard_deadline:
                    return best
                try:
                    self.planner.scorer.score(state, option)
                except Exception:
                    continue
                if (
                    best is None
                    or self._geometry_rescue_rank(option)
                    > self._geometry_rescue_rank(best)
                ):
                    best = option
        return best

    @staticmethod
    def _geometry_rescue_rank(candidate: Candidate) -> tuple[int, float, float, float, float]:
        return (
            -candidate.rule_violations,
            candidate.secondary_score,
            candidate.support_ratio,
            candidate.min_clearance,
            -candidate.position[2],
        )

    @staticmethod
    def _format_action(
        item_idx: int,
        container_idx: int,
        position: tuple[float, float, float],
        orientation: int,
    ) -> dict[str, Any]:
        return {
            "item_idx": int(item_idx),
            "container_idx": int(container_idx),
            "place_pos": np.asarray(position, dtype=np.float32).reshape(3),
            "orientation": int(orientation),
        }

    def _deterministic_last_resort(
        self,
        observation: dict[str, Any],
        pool: list[ItemSpec],
    ) -> dict[str, Any]:
        pool_index, item = min(
            enumerate(pool),
            key=lambda pair: (pair[1].volume, min(pair[1].dimensions), pair[0]),
        )
        containers = observation.get("container_list", self.initial_containers)
        container_index = 0
        if item.is_prioritized:
            for index, container in enumerate(containers):
                if container.get("is_prioritized", False):
                    container_index = index
                    break
        container = containers[container_index]
        orientation = min(range(6), key=lambda index: self._oriented_height(item, index))
        dimensions = self._orientation_dimensions(item, orientation)
        points = np.asarray(container.get("points", []), dtype=np.float64)
        normals = np.asarray(container.get("n_vecs", []), dtype=np.float64)
        floor = float(container["thickness"])
        if points.ndim == 2 and normals.shape == points.shape:
            floor_points = points[normals[:, 2] < -0.9, 2]
            if len(floor_points):
                floor = float(np.max(floor_points))
        z = floor + 0.008 + dimensions[2] / 2.0
        y = (
            float(container["width"]) / 2.0
            - float(container["thickness"])
            - self.settings.path_clearance
            - dimensions[1] / 2.0
        )
        return self._format_action(pool_index, container_index, (0.0, y, z), orientation)

    @staticmethod
    def _orientation_dimensions(item: ItemSpec, orientation: int) -> tuple[float, float, float]:
        from .geometry import oriented_dimensions

        return oriented_dimensions(item.dimensions, orientation)

    @classmethod
    def _oriented_height(cls, item: ItemSpec, orientation: int) -> float:
        return cls._orientation_dimensions(item, orientation)[2]
