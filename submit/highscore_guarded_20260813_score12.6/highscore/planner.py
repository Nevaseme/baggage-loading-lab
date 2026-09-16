from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Sequence

from .candidates import CandidateGenerator
from .model import Candidate, ItemSpec, PackingState, PlacedItem
from .scoring import CandidateScorer
from .settings import SearchSettings


@dataclass
class _BeamNode:
    state: PackingState
    remaining: tuple[tuple[int, ItemSpec], ...]
    first: Candidate | None
    order: tuple[int, ...]
    skeleton: tuple[Candidate, ...]
    placed_volume: float
    violations: int
    secondary_score: float

    @property
    def rank(self) -> tuple[int, float, int, float]:
        return (
            len(self.order),
            self.placed_volume,
            -self.violations,
            self.secondary_score,
        )


class Planner:
    def __init__(self, settings: SearchSettings):
        self.settings = settings
        self.generator = CandidateGenerator(settings)
        self.scorer = CandidateScorer(settings)

    def _rank_items(
        self,
        indexed_items: Sequence[tuple[int, ItemSpec]],
        state: PackingState,
        limit: int,
    ) -> list[tuple[int, ItemSpec]]:
        def scarcity(item: ItemSpec) -> float:
            fit_orientations = 0
            for oriented in (
                (item.length, item.width, item.height),
                (item.length, item.height, item.width),
                (item.height, item.width, item.length),
                (item.width, item.length, item.height),
                (item.width, item.height, item.length),
                (item.height, item.length, item.width),
            ):
                if any(
                    oriented[0] <= container.length - 2.0 * container.thickness
                    and oriented[1] <= container.width - 2.0 * container.thickness
                    and oriented[2] <= container.height - container.thickness - container.buffer
                    for container in state.containers
                ):
                    fit_orientations += 1
            return 1.0 - fit_orientations / 6.0

        return sorted(
            indexed_items,
            key=lambda pair: (
                self.scorer.item_urgency(pair[1], state.containers) + 0.5 * scarcity(pair[1]),
                pair[1].volume,
                pair[1].mass,
                -pair[0],
            ),
            reverse=True,
        )[:limit]

    @staticmethod
    def _apply(state: PackingState, candidate: Candidate) -> PackingState:
        next_state = state.clone()
        container = next(
            container for container in next_state.containers if container.index == candidate.container_index
        )
        container.placed.append(PlacedItem(candidate.item, candidate.box))
        return next_state

    @staticmethod
    def _future_feasible_fraction(
        state: PackingState,
        remaining: Sequence[tuple[int, ItemSpec]],
    ) -> float:
        if not remaining:
            return 1.0
        feasible = 0
        prioritized_containers = [container for container in state.containers if container.is_prioritized]
        for _, item in remaining:
            containers = state.containers
            if item.is_prioritized and prioritized_containers:
                containers = prioritized_containers
            elif not item.is_prioritized and any(not container.is_prioritized for container in containers):
                containers = [container for container in containers if not container.is_prioritized]
            for container in containers:
                used_volume = sum(placed.box.volume for placed in container.placed)
                if container.volume - used_volume + 1e-9 < item.volume:
                    continue
                inner = (
                    container.length - 2.0 * (container.thickness + 0.018),
                    container.width - 2.0 * (container.thickness + 0.018),
                    container.height - container.thickness - container.buffer - 0.008,
                )
                if any(
                    all(dimension <= limit + 1e-9 for dimension, limit in zip(oriented, inner))
                    for oriented in (
                        (item.length, item.width, item.height),
                        (item.length, item.height, item.width),
                        (item.height, item.width, item.length),
                        (item.width, item.length, item.height),
                        (item.width, item.height, item.length),
                        (item.height, item.length, item.width),
                    )
                ):
                    feasible += 1
                    break
        return feasible / len(remaining)

    def _top_candidates(
        self,
        state: PackingState,
        item: ItemSpec,
        pool_index: int,
        limit: int,
        deadline: float,
    ) -> list[Candidate]:
        candidates = self.generator.generate(state, item, pool_index, deadline=deadline)
        if not candidates and time.perf_counter() < deadline:
            candidates = self.generator.generate(
                state,
                item,
                pool_index,
                deadline=deadline,
                allow_rule_violations=True,
            )
        for candidate in candidates:
            self.scorer.score(state, candidate)
        candidates.sort(
            key=lambda candidate: (
                -candidate.rule_violations,
                candidate.secondary_score,
                candidate.support_ratio,
                candidate.position[1],
                -candidate.position[2],
            ),
            reverse=True,
        )
        return candidates[:limit]

    def choose_online(
        self,
        state: PackingState,
        pool: Sequence[ItemSpec],
        *,
        deadline: float,
    ) -> Candidate | None:
        if not pool:
            return None
        initial = _BeamNode(
            state=state,
            remaining=tuple(enumerate(pool)),
            first=None,
            order=(),
            skeleton=(),
            placed_volume=0.0,
            violations=0,
            secondary_score=0.0,
        )
        beam = [initial]
        best: _BeamNode | None = None
        max_depth = min(self.settings.beam_depth, len(pool))
        for _ in range(max_depth):
            expanded: list[_BeamNode] = []
            for node in beam:
                if time.perf_counter() >= deadline:
                    break
                item_choices = self._rank_items(node.remaining, node.state, min(6, len(node.remaining)))
                for pool_index, item in item_choices:
                    if time.perf_counter() >= deadline:
                        break
                    candidates = self._top_candidates(
                        node.state,
                        item,
                        pool_index,
                        self.settings.candidates_per_item,
                        deadline,
                    )
                    for candidate in candidates:
                        remaining = tuple(pair for pair in node.remaining if pair[0] != pool_index)
                        next_state = self._apply(node.state, candidate)
                        candidate.future_feasible = self._future_feasible_fraction(next_state, remaining)
                        self.scorer.score(node.state, candidate)
                        expanded.append(
                            _BeamNode(
                                state=next_state,
                                remaining=remaining,
                                first=node.first or candidate,
                                order=node.order + (item.index,),
                                skeleton=node.skeleton + (candidate,),
                                placed_volume=node.placed_volume + item.volume,
                                violations=node.violations + candidate.rule_violations,
                                secondary_score=node.secondary_score + candidate.secondary_score,
                            )
                        )
            if not expanded:
                break
            expanded.sort(key=lambda node: node.rank, reverse=True)
            beam = expanded[: self.settings.beam_width]
            if best is None or beam[0].rank > best.rank:
                best = beam[0]
        return best.first if best is not None else None

    def optimize_order(
        self,
        state: PackingState,
        items: Sequence[ItemSpec],
        *,
        deadline: float,
    ) -> tuple[list[int], list[Candidate]]:
        initial = _BeamNode(
            state=state,
            remaining=tuple(enumerate(items)),
            first=None,
            order=(),
            skeleton=(),
            placed_volume=0.0,
            violations=0,
            secondary_score=0.0,
        )
        beam = [initial]
        best = initial
        while beam and beam[0].remaining and time.perf_counter() < deadline:
            expanded: list[_BeamNode] = []
            for node in beam:
                if time.perf_counter() >= deadline:
                    break
                choices = self._rank_items(
                    node.remaining,
                    node.state,
                    self.settings.offline_item_choices,
                )
                for source_index, item in choices:
                    candidates = self._top_candidates(
                        node.state,
                        item,
                        source_index,
                        self.settings.offline_placements_per_item,
                        deadline,
                    )
                    for candidate in candidates:
                        remaining = tuple(pair for pair in node.remaining if pair[0] != source_index)
                        next_state = self._apply(node.state, candidate)
                        candidate.future_feasible = self._future_feasible_fraction(next_state, remaining)
                        self.scorer.score(node.state, candidate)
                        expanded.append(
                            _BeamNode(
                                state=next_state,
                                remaining=remaining,
                                first=node.first or candidate,
                                order=node.order + (item.index,),
                                skeleton=node.skeleton + (candidate,),
                                placed_volume=node.placed_volume + item.volume,
                                violations=node.violations + candidate.rule_violations,
                                secondary_score=node.secondary_score + candidate.secondary_score,
                            )
                        )
            if not expanded:
                break
            expanded.sort(key=lambda node: node.rank, reverse=True)
            beam = expanded[: self.settings.offline_beam_width]
            if beam[0].rank > best.rank:
                best = beam[0]

        remaining_items = [item for _, item in best.remaining]
        tail = [
            item.index
            for _, item in self._rank_items(
                list(enumerate(remaining_items)),
                best.state,
                len(remaining_items),
            )
        ]
        return list(best.order) + tail, list(best.skeleton)
