from __future__ import annotations

import math
import time
from typing import Any, Sequence

import numpy as np

from .beam import FutureSupportIngressBeam
from .catalog import RootCatalog, StrictRootScanner
from .geometry import oriented_dimensions
from .mask import ExactMask
from .mode_a_exact_compile import StrictSkeletonCompiler
from .mode_a_order_beam import LayeredProxyOrderBeam, ProxyOrderCandidate
from .mode_a_repair import ModeAExactSkeletonRepair
from .mode_a_types import ModeAPlan, build_offline_occurrences
from .model import ItemSpec, PackingState, PlacementProposal, ValidatedRoot, _VALIDATION_TOKEN, _item_signature
from .settings import SearchSettings
from .state import build_packing_state, state_fingerprint


class NotReadyError(RuntimeError):
    """Raised when the public lifecycle has not installed a planning mode."""


class CandidateZeroError(RuntimeError):
    """Raised when the ordered pool has no strict exact root."""


class PlanningError(RuntimeError):
    """Raised when a B/C planning stage fails closed without an action."""


class Agent:
    """Public boundary for exact-mask B/C planning and action formatting."""

    def __init__(self, module_path: str):
        self.module_path = str(module_path)
        self.settings = SearchSettings()
        self._clock = time.perf_counter
        self.optimize_enabled = False
        self.lookahead_k = 1
        self.mode: str | None = None
        self.initial_containers: list[dict] = []
        self.current_pool: list[dict] | None = None
        self._exact_revalidator = None
        self._active_output_deadline: float | None = None
        self.mode_a_plan: ModeAPlan | None = None
        self.mode_a_order_fallback_trace: dict[str, int] | None = None
        self.initial_packed_signatures: tuple[tuple, ...] = ()
        self.exact_mask = ExactMask(self.settings)
        self.scanner = StrictRootScanner(self.settings, mask=self.exact_mask)
        self.beam = FutureSupportIngressBeam(
            self.scanner,
            self.exact_mask,
            self.settings,
            beam_width=self.settings.bc_beam_width,
            max_depth=self.settings.bc_beam_depth,
            item_choices=self.settings.bc_item_choices,
            roots_per_item=self.settings.bc_roots_per_item,
        )
        self.mode_a_order_beam = LayeredProxyOrderBeam(
            clock=lambda: self._clock()
        )
        self.mode_a_compiler = StrictSkeletonCompiler(
            self.settings,
            self.scanner,
            self.exact_mask,
            clock=lambda: self._clock(),
        )
        self.mode_a_repair = ModeAExactSkeletonRepair(
            self.settings,
            self.scanner,
            self.exact_mask,
            clock=lambda: self._clock(),
        )
        self.install_exact_revalidator(self.exact_mask.revalidate)

    def install_exact_revalidator(self, callback: Any) -> None:
        """Install the exact-mask receipt revalidation capability."""

        if not callable(callback):
            raise TypeError("exact_revalidator must be callable")
        self._exact_revalidator = callback

    _install_exact_revalidator = install_exact_revalidator

    def get_init_states(self, init_states: dict[str, Any]) -> bool:
        if not isinstance(init_states, dict):
            raise TypeError("init_states must be a dictionary")
        self.optimize_enabled = bool(init_states.get("optimize", False))
        self.lookahead_k = int(init_states.get("lookahead_k", 1))
        self.initial_containers = list(init_states.get("container_list", []))
        self.mode_a_plan = None
        self.mode_a_order_fallback_trace = None
        self.initial_packed_signatures = ()
        try:
            initial_state = build_packing_state(self.initial_containers)
            self.initial_packed_signatures = tuple(
                _item_signature(placed.item)
                for container in initial_state.containers
                for placed in container.placed
            )
        except Exception:
            self.initial_packed_signatures = ()
        if self.optimize_enabled:
            self.mode = "A"
        elif self.lookahead_k > 1:
            self.mode = "B"
        else:
            self.mode = "C"
        return True

    def optimize(self, item_list: list[dict[str, Any]]) -> list[int]:
        self.mode_a_plan = None
        self.mode_a_order_fallback_trace = None
        try:
            original = [int(value["index"]) for value in item_list]
        except Exception:
            return []
        if not isinstance(item_list, list):
            return original
        try:
            started = float(self._clock())
            if not math.isfinite(started):
                return original
            validation_deadline = started + self.settings.mode_a_seed_validation_seconds
            order_deadline = started + self.settings.mode_a_order_beam_seconds
            compile_deadline = started + self.settings.mode_a_compile_seconds
            final_deadline = started + self.settings.mode_a_validation_seconds
            hard_deadline = started + self.settings.mode_a_optimize_hard_seconds
            occurrences = build_offline_occurrences(item_list)
            state = build_packing_state(self.initial_containers)
            now = float(self._clock())
            if not math.isfinite(now) or now >= validation_deadline:
                return original
            candidates = self.mode_a_order_beam.search(
                state, occurrences, item_list, order_deadline
            )
            complete = tuple(
                candidate for candidate in candidates if candidate.complete
            )
            for index, candidate in enumerate(complete):
                now = float(self._clock())
                if not math.isfinite(now) or now >= compile_deadline:
                    break
                remaining = len(complete) - index
                candidate_deadline = min(
                    compile_deadline,
                    now + (compile_deadline - now) / max(1, remaining),
                )
                plan = self.mode_a_compiler.compile(
                    state,
                    item_list,
                    occurrences,
                    candidate,
                    candidate_deadline,
                )
                if type(plan) is not ModeAPlan:
                    continue
                now = float(self._clock())
                if not math.isfinite(now) or now >= compile_deadline:
                    break
                plan.__post_init__()
                order = [
                    int(item_list[position]["index"])
                    for position in plan.returned_order
                ]
                if len(order) != len(original):
                    continue
                from collections import Counter

                if Counter(order) != Counter(original):
                    continue
                now = float(self._clock())
                if not math.isfinite(now) or now >= final_deadline:
                    break
                now = float(self._clock())
                if not math.isfinite(now) or now >= hard_deadline:
                    break
                self.mode_a_plan = plan
                return order
            if self.settings.mode_a_proxy_prefix_order_fallback:
                now = float(self._clock())
                if not math.isfinite(now) or now >= final_deadline:
                    return original
                partial = next(
                    (
                        candidate
                        for candidate in candidates
                        if type(candidate) is ProxyOrderCandidate
                        and not candidate.complete
                    ),
                    None,
                )
                if type(partial) is not ProxyOrderCandidate:
                    return original
                partial.__post_init__()
                if len(partial.occurrence_order) != len(occurrences):
                    return original
                authoritative = {
                    occurrence.original_position: occurrence
                    for occurrence in occurrences
                }
                for occurrence in partial.occurrence_order:
                    expected = authoritative.get(occurrence.original_position)
                    if expected is None or occurrence.stable_key != expected.stable_key:
                        return original
                order = [
                    int(item_list[occurrence.original_position]["index"])
                    for occurrence in partial.occurrence_order
                ]
                from collections import Counter

                if len(order) != len(original) or Counter(order) != Counter(original):
                    return original
                now = float(self._clock())
                if not math.isfinite(now) or now >= final_deadline:
                    return original
                now = float(self._clock())
                if not math.isfinite(now) or now >= hard_deadline:
                    return original
                self.mode_a_order_fallback_trace = {
                    "selected_depth": int(partial.placed_count),
                    "seed_lane": int(partial.seed_lane),
                }
                return order
        except Exception:
            pass
        self.mode_a_plan = None
        return original

    def policy(self, observation: dict[str, Any]) -> dict[str, Any]:
        try:
            started = float(self._clock())
        except Exception as error:
            raise PlanningError(f"policy clock failed: {type(error).__name__}: {error}") from error
        if not math.isfinite(started):
            raise PlanningError("policy clock returned a non-finite value")
        if self.mode is None:
            raise NotReadyError("get_init_states must fix mode before policy")
        if not isinstance(observation, dict):
            raise PlanningError("observation must be a dictionary")
        if "pool_list" not in observation or observation["pool_list"] is None:
            raise CandidateZeroError("ordered raw pool is mandatory")
        try:
            raw_pool = list(observation["pool_list"])
        except Exception as error:
            raise PlanningError(f"ordered pool decode failed: {type(error).__name__}: {error}") from error
        if not raw_pool:
            raise CandidateZeroError("empty ordered pool has no action")
        self.current_pool = raw_pool

        try:
            state = build_packing_state(
                observation.get("container_list", self.initial_containers),
                observation.get("depth_map"),
            )
        except Exception as error:
            raise PlanningError(f"state build failed: {type(error).__name__}: {error}") from error

        if self.mode == "A":
            catalog_deadline = started + self.settings.mode_a_policy_catalog_seconds
            search_deadline = started + self.settings.mode_a_policy_search_seconds
            reserve_deadline = started + self.settings.mode_a_policy_reserve_boundary_seconds
            output_deadline = started + self.settings.mode_a_policy_hard_seconds
        else:
            catalog_deadline = started + self.settings.bc_planning_limit_seconds
            search_deadline = started + self.settings.bc_search_limit_seconds
            reserve_deadline = catalog_deadline
            output_deadline = started + self.settings.bc_policy_hard_limit_seconds
        try:
            if self.mode == "A":
                advisory = self._mode_a_advisory_proposals(
                    state, raw_pool, catalog_deadline
                )
                catalog = self.scanner.scan(
                    state,
                    raw_pool,
                    deadline=catalog_deadline,
                    advisory_proposals=advisory,
                )
            else:
                catalog = self.scanner.scan(
                    state,
                    raw_pool,
                    deadline=catalog_deadline,
                )
        except Exception as error:
            raise PlanningError(f"scanner failed: {type(error).__name__}: {error}") from error
        if not isinstance(catalog, RootCatalog):
            raise PlanningError("scanner returned a non-catalog result")
        if not catalog:
            raise CandidateZeroError("strict root catalog is empty")

        deadline_incumbent = self._deadline_incumbent(catalog)
        try:
            scanner_completed = float(self._clock())
        except Exception as error:
            raise PlanningError(
                f"post-scanner clock failed: {type(error).__name__}: {error}"
            ) from error
        if not math.isfinite(scanner_completed) or scanner_completed >= output_deadline:
            raise PlanningError("scanner exhausted the 5.75s hard deadline")

        used_deadline_incumbent = (
            self.mode in ("A", "B") and scanner_completed >= search_deadline
        )
        try:
            if used_deadline_incumbent:
                root = deadline_incumbent
            elif self.mode == "A":
                root = self.mode_a_repair.choose(
                    state,
                    raw_pool,
                    catalog,
                    self.mode_a_plan,
                    self.initial_packed_signatures,
                    search_deadline,
                )
            elif self.mode == "B":
                root = self.beam.choose_b(state, raw_pool, catalog, search_deadline)
            else:
                root = self.beam.choose_c(state, raw_pool, catalog, search_deadline)
        except Exception as error:
            stage = "repair" if self.mode == "A" else "beam"
            raise PlanningError(
                f"{self.mode} {stage} failed: {type(error).__name__}: {error}"
            ) from error
        if root is None:
            try:
                beam_completed = float(self._clock())
            except Exception as error:
                raise PlanningError(
                    f"post-beam clock failed: {type(error).__name__}: {error}"
                ) from error
            if (
                math.isfinite(beam_completed)
                and beam_completed < output_deadline
                and (
                    self.mode == "A"
                    or (self.mode == "B" and beam_completed >= search_deadline)
                )
            ):
                root = deadline_incumbent
                used_deadline_incumbent = True
            else:
                stage = "repair" if self.mode == "A" else "beam"
                raise PlanningError(f"{self.mode} {stage} returned no root")
        if not any(root is catalog_root for catalog_root in catalog.roots):
            raise PlanningError("planner root is not an identical depth-zero catalog member")

        try:
            now = float(self._clock())
        except Exception as error:
            raise PlanningError(f"output clock failed: {type(error).__name__}: {error}") from error
        if not math.isfinite(now):
            raise PlanningError("output clock returned a non-finite value")
        if not used_deadline_incumbent and now >= reserve_deadline:
            raise PlanningError("planning exceeded the output-reserve boundary")
        if now >= output_deadline:
            raise PlanningError("policy exceeded the 5.75s hard deadline")
        self._active_output_deadline = output_deadline
        try:
            return self.format_validated_action(root, state, raw_pool)
        except Exception as error:
            raise PlanningError(f"format failed closed: {type(error).__name__}: {error}") from error
        finally:
            self._active_output_deadline = None

    def _mode_a_advisory_proposals(
        self,
        state: PackingState,
        raw_pool: Sequence[ItemSpec | dict],
        deadline: float,
    ) -> tuple[PlacementProposal, ...]:
        if self.mode_a_plan is None:
            return ()
        try:
            context = self.mode_a_repair._derive_context(
                state,
                self.mode_a_plan,
                self.initial_packed_signatures,
                deadline,
            )
            intent, _suffix, completed = context
            if intent is None:
                return ()
            pool = tuple(
                value if isinstance(value, ItemSpec) else ItemSpec.from_dict(value)
                for value in raw_pool
            )
            pool_index = next(
                index
                for index, item in enumerate(pool)
                if _item_signature(item) == intent.occurrence.item_signature
            )
            item = pool[pool_index]
            position = self.mode_a_repair.rebase_intent_position(
                intent, completed, self.mode_a_plan, deadline
            )
            dimensions = oriented_dimensions(item.dimensions, intent.orientation)
            container = state.containers[intent.container_ordinal]
            centers = [position[2]]
            centers.append(
                container.thickness + container.buffer + 0.008 + dimensions[2] * 0.5
            )
            for obstacle in container.static_obstacles:
                if float(self._clock()) >= deadline:
                    return tuple()
                centers.append(float(obstacle.maximum[2]) + 0.022 + dimensions[2] * 0.5)
            for placed in container.placed:
                if float(self._clock()) >= deadline:
                    return tuple()
                centers.append(float(placed.box.maximum[2]) + dimensions[2] * 0.5)
            result = []
            seen = set()
            for ordinal, z in enumerate(centers):
                key = (round(position[0], 8), round(position[1], 8), round(z, 8))
                if key in seen:
                    continue
                seen.add(key)
                result.append(
                    PlacementProposal(
                        item.index,
                        pool_index,
                        intent.container_ordinal,
                        intent.orientation,
                        (position[0], position[1], float(z)),
                        f"mode_a_online_advisory_{ordinal}",
                    )
                )
                if len(result) >= 6:
                    break
            return tuple(result)
        except Exception:
            return ()

    @staticmethod
    def _deadline_incumbent(catalog: RootCatalog) -> ValidatedRoot:
        """Select a cheap deterministic strict depth-zero deadline incumbent."""

        if not isinstance(catalog, RootCatalog) or not catalog.records:
            raise CandidateZeroError("strict root catalog is empty")

        def rank(record) -> tuple:
            root = record.root
            return (
                root.rule_violations != 0,
                not root.strict,
                int(root.rule_violations),
                -float(root.support_ratio),
                -float(root.min_clearance),
                float(root.box.maximum[2]),
                float(root.box.center[2]),
                record.stable_key,
                int(record.raw_ordinal),
            )

        return min(catalog.records, key=rank).root

    def format_validated_action(
        self,
        root: ValidatedRoot,
        current_state: PackingState,
        current_pool: Sequence[ItemSpec | dict],
    ) -> dict[str, Any]:
        if not isinstance(root, ValidatedRoot):
            raise TypeError("only a ValidatedRoot may be formatted")
        if not isinstance(current_state, PackingState):
            raise TypeError("current_state must be a PackingState")
        if current_pool is None:
            raise ValueError("current_pool is mandatory for exact action formatting")
        if self._exact_revalidator is None:
            raise NotReadyError("exact validation mask is not installed")
        if root._proof is not _VALIDATION_TOKEN:
            raise TypeError("root is not owned by the exact validation mask")
        profile_digest = self.settings.profile_digest()

        proposal = root.proposal
        if proposal.container_index >= len(current_state.containers):
            raise ValueError("proposal container ordinal is out of range")
        container = current_state.containers[proposal.container_index]
        if int(getattr(container, "ordinal", -1)) != proposal.container_index:
            raise ValueError("proposal container index must match the Gym ordinal")
        expected_key = (
            proposal.item_index,
            proposal.pool_index,
            proposal.container_index,
            proposal.orientation,
            tuple(round(value, 7) for value in proposal.position),
        )
        if tuple(root.proposal_key) != expected_key:
            raise ValueError("validated root proposal binding does not match")
        if root.profile_digest != profile_digest:
            raise ValueError("validated root profile digest does not match")
        dimensions: tuple[float, float, float] | None = None
        if current_pool is not None:
            if proposal.pool_index >= len(current_pool):
                raise ValueError("validated root pool position is no longer present")
            raw_item = current_pool[proposal.pool_index]
            item = raw_item if isinstance(raw_item, ItemSpec) else ItemSpec.from_dict(raw_item)
            if item.index != proposal.item_index or _item_signature(item) != tuple(root.item_signature):
                raise ValueError("validated root item binding does not match current pool")
            dimensions = oriented_dimensions(item.dimensions, proposal.orientation)
        if dimensions is not None and not np.allclose(
            root.box.dimensions, np.asarray(dimensions, dtype=np.float64), rtol=0.0, atol=1e-8
        ):
            raise ValueError("validated root box binding does not match current item orientation")
        if not np.all(np.isfinite(root.box.center)) or not np.allclose(
            root.box.center, np.asarray(proposal.position, dtype=np.float64), rtol=0.0, atol=1e-8
        ):
            raise ValueError("validated root box center does not match proposal")
        current_fingerprint = state_fingerprint(
            current_state,
            current_pool,
            proposal.pool_index,
            profile_digest,
        )
        if root.state_fingerprint != current_fingerprint:
            raise ValueError("validated root state fingerprint does not match current state")

        verified = self._exact_revalidator(
            current_state,
            current_pool,
            proposal,
            self.settings,
        )
        if isinstance(verified, ValidatedRoot):
            if (
                verified.proposal != root.proposal
                or not np.array_equal(verified.box.minimum, root.box.minimum)
                or not np.array_equal(verified.box.maximum, root.box.maximum)
                or verified.profile_digest != profile_digest
                or verified.state_fingerprint != current_fingerprint
                or verified.item_signature != root.item_signature
                or verified.proposal_key != root.proposal_key
                or verified.support_ratio != root.support_ratio
                or verified.min_clearance != root.min_clearance
                or verified.source != root.source
                or verified.rule_violations != 0
                or not verified.strict
            ):
                raise ValueError("exact revalidation evidence does not match root")
        else:
            raise NotReadyError(
                "exact validation must return matching strict evidence; "
                "boolean or absent evidence is not format-authorizing"
            )
        action = {
            "item_idx": int(proposal.pool_index),
            "container_idx": int(proposal.container_index),
            "place_pos": np.asarray(proposal.position, dtype=np.float32).reshape(3),
            "orientation": int(proposal.orientation),
        }
        if self._active_output_deadline is not None:
            try:
                completed = float(self._clock())
            except Exception as error:
                raise PlanningError(
                    f"output clock failed: {type(error).__name__}: {error}"
                ) from error
            if not math.isfinite(completed) or completed >= self._active_output_deadline:
                raise PlanningError("fresh action formatting exceeded the 5.75s hard deadline")
        return action
