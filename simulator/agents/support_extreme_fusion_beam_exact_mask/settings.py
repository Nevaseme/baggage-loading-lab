from dataclasses import asdict, dataclass, field
import hashlib
import json


STRICT_VALIDATION_PROFILE_VERSION = "support-extreme-fusion-strict-v2"


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
    """Shared strict-mask limits; planner-specific modules consume these later."""

    use_monotone_ingress: bool = False
    use_geometry_rescue: bool = False
    use_mpc_mcts_ems: bool = False
    inclusion_margin: float = -0.008
    path_clearance: float = 0.018
    center_support_margin: float = 0.02
    rigid_support_ratio: float = 0.75
    soft_support_ratio: float = 0.90
    support_height_tolerance: float = 0.012
    support_inset: float = 0.008
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
    ems_proxy_actions_per_item: int = 24
    ems_exact_roots_per_item: int = 6
    ems_root_catalog_limit: int = 48
    ems_root_budget_seconds: float = 1.35
    mcts_exploration: float = 1.15
    mcts_progressive_k: float = 2.0
    mcts_progressive_alpha: float = 0.50
    mcts_rollout_limit: int = 64
    mcts_transposition_quantum: float = 0.01
    mcts_policy_limit_seconds: float = 5.40
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
    policy_hard_limit_seconds: float = 5.75
    optimize_limit_seconds: float = 150.0
    normal_catalog_limit_seconds: float = 1.80
    deterministic_limit_seconds: float = 5.30
    zero_root_rescue_limit_seconds: float = 5.45
    output_reserve_seconds: float = 0.30
    bc_beam_width: int = 20
    bc_beam_depth: int = 4
    bc_item_choices: int = 6
    bc_roots_per_item: int = 2
    bc_search_limit_seconds: float = 5.30
    bc_planning_limit_seconds: float = 5.45
    bc_policy_hard_limit_seconds: float = 5.75
    bc_output_reserve_seconds: float = 0.30
    # Mode-A orchestration only.  These fields are intentionally excluded
    # from the strict geometry profile digest below.
    mode_a_seed_validation_seconds: float = 8.0
    mode_a_order_beam_seconds: float = 82.0
    mode_a_compile_seconds: float = 138.0
    mode_a_validation_seconds: float = 145.0
    mode_a_optimize_hard_seconds: float = 150.0
    mode_a_policy_catalog_seconds: float = 4.40
    mode_a_policy_search_seconds: float = 5.30
    mode_a_policy_reserve_boundary_seconds: float = 5.45
    mode_a_policy_hard_seconds: float = 5.75
    mode_a_proxy_prefix_order_fallback: bool = False
    proposal_quantum: int = 4
    raw_proposal_limit: int = 4096
    weights: ScoreWeights = field(default_factory=ScoreWeights)

    def profile_digest(self) -> str:
        """Canonical digest bound to exact-root receipts and fingerprints."""

        settings = asdict(self)
        for key in tuple(settings):
            if key.startswith("mode_a_"):
                settings.pop(key)
        payload = {
            "version": STRICT_VALIDATION_PROFILE_VERSION,
            "settings": settings,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()
