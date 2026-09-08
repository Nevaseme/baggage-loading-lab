from __future__ import annotations

from typing import Sequence

import math

from .model import Candidate, ContainerState, ItemSpec, PackingState
from .settings import SearchSettings


def protection_rule_violations(item: ItemSpec, supporting_items: Sequence[ItemSpec]) -> int:
    violations = 0
    for below in supporting_items:
        if below.is_prioritized and not item.is_prioritized:
            violations += 1
        if below.is_soft and not item.is_soft:
            violations += 1
    return violations


class CandidateScorer:
    def __init__(self, settings: SearchSettings):
        self.settings = settings

    @staticmethod
    def item_urgency(item: ItemSpec, containers: Sequence[ContainerState]) -> float:
        minimum_container_volume = min((container.volume for container in containers), default=1.0)
        relative_volume = min(1.0, item.volume / max(0.01, minimum_container_volume) * 20.0)
        density = min(1.0, item.mass / max(item.volume, 1e-6) / 500.0)
        constrained = (0.75 if item.is_prioritized else 0.0) + (0.45 if item.is_soft else 0.0)
        return min(1.0, 0.35 * relative_volume + 0.15 * density + constrained)

    def score(self, state: PackingState, candidate: Candidate) -> float:
        container = next(
            container for container in state.containers if container.index == candidate.container_index
        )
        height = max(container.height, 1e-6)
        width = max(container.width, 1e-6)
        length = max(container.length, 1e-6)

        existing_mass = sum(placed.item.mass for placed in container.placed)
        existing_moment = sum(
            placed.item.mass * float(placed.box.center[2]) for placed in container.placed
        )
        combined_mass = existing_mass + candidate.item.mass
        combined_cog = (
            existing_moment + candidate.item.mass * candidate.position[2]
        ) / max(combined_mass, 1e-9)
        low_cog = max(0.0, 1.0 - combined_cog / height)
        backness = min(1.0, max(0.0, (candidate.position[1] + width / 2.0) / width))
        wall_distances = (
            abs(candidate.box.minimum[0] + length / 2.0 - container.thickness),
            abs(container.length / 2.0 - container.thickness - candidate.box.maximum[0]),
            abs(container.width / 2.0 - container.thickness - candidate.box.maximum[1]),
        )
        alignment = math.exp(-min(wall_distances) / 0.08)
        continuity = min(1.0, 0.55 * alignment + 0.45 * backness)
        stability = min(1.0, 0.7 * candidate.support_ratio + 0.3 * low_cog)
        masses = [sum(placed.item.mass for placed in current.placed) for current in state.containers]
        for index, current in enumerate(state.containers):
            if current.index == candidate.container_index:
                masses[index] += candidate.item.mass
                break
        mass_balance = 1.0
        if len(masses) > 1 and sum(masses) > 1e-9:
            mass_balance = max(0.0, 1.0 - (max(masses) - min(masses)) / sum(masses))
        path_preservation = min(1.0, 0.5 * backness + 0.3 * low_cog + 0.2 * mass_balance)
        urgency = self.item_urgency(candidate.item, state.containers)

        # Unsupported height and tiny clearances create voids or physically brittle placements.
        floor_gap = max(
            0.0,
            candidate.box.minimum[2] - (container.thickness + container.buffer),
        )
        void_penalty = min(1.0, floor_gap / height) * (1.0 - candidate.support_ratio)
        clearance_risk = max(
            0.0,
            (self.settings.path_clearance - candidate.min_clearance)
            / max(self.settings.path_clearance, 1e-6),
        )
        support_target = self.settings.soft_support_ratio if candidate.item.is_soft else self.settings.rigid_support_ratio
        support_risk = max(0.0, support_target - candidate.support_ratio) / max(support_target, 1e-6)
        uncertainty = min(1.0, 0.65 * clearance_risk + 0.35 * support_risk)

        weights = self.settings.weights
        score = (
            weights.future_feasible * candidate.future_feasible
            + weights.continuity * continuity
            + weights.support_and_stability * stability
            + weights.low_cog * low_cog
            + weights.path_preservation * path_preservation
            + weights.urgency * urgency
            - weights.void_penalty * void_penalty
            - weights.uncertainty_penalty * uncertainty
        )
        candidate.secondary_score = float(score)
        return float(score)
