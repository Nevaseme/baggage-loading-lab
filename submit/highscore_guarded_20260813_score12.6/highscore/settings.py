from dataclasses import dataclass, field


@dataclass(frozen=True)
class ScoreWeights:
    future_feasible: float = 3.0
    continuity: float = 2.0
    support_and_stability: float = 1.5
    low_cog: float = 1.25
    path_preservation: float = 1.0
    urgency: float = 1.0
    void_penalty: float = 2.0
    uncertainty_penalty: float = 4.0


@dataclass(frozen=True)
class SearchSettings:
    inclusion_margin: float = -0.008
    path_clearance: float = 0.018
    center_support_margin: float = 0.02
    rigid_support_ratio: float = 0.75
    soft_support_ratio: float = 0.90
    support_height_tolerance: float = 0.012
    extra_margins: tuple[float, ...] = (0.003, 0.001, 0.0)
    rigid_support_relaxations: tuple[float, ...] = (0.75, 0.70, 0.65)
    soft_support_relaxations: tuple[float, ...] = (0.90, 0.85, 0.80)
    coordinate_limit: int = 14
    fallback_coordinate_limit: int = 16
    candidates_per_orientation: int = 48
    local_grid_step: float = 0.02
    recovery_grid_step: float = 0.02
    recovery_candidate_limit: int = 32
    recovery_candidates_per_orientation: int = 16
    depth_tolerance: float = 0.15
    depth_min_blocking_pixels: int = 2
    lane_frontier_skew: float = 0.55
    shelf_drop_gap: float = 0.022
    front_floor_release_fill: float = 0.20
    candidates_per_item: int = 8
    beam_width: int = 16
    beam_depth: int = 3
    offline_beam_width: int = 24
    offline_item_choices: int = 4
    offline_placements_per_item: int = 4
    policy_soft_limit_seconds: float = 1.0
    # Leave serialization/scheduler headroom below the public six-second cutoff.
    policy_hard_limit_seconds: float = 5.75
    optimize_limit_seconds: float = 150.0
    weights: ScoreWeights = field(default_factory=ScoreWeights)
