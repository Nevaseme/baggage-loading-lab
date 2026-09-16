"""Fair deterministic catalog of strict exact roots.

This module is the only bridge from raw fused proposal records to planner
input.  It never promotes a raw proposal itself: every exposed entry is a
``ValidatedRoot`` returned by ``ExactMask.validate`` for the current ordered
pool and state fingerprint.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math
import time
from typing import Iterator, Sequence

import numpy as np

from .geometry import oriented_dimensions
from .mask import ExactMask, RejectReason
from .model import (
    ItemSpec,
    PackingState,
    PlacementProposal,
    ValidatedRoot,
    _VALIDATION_TOKEN,
    _item_signature,
)
from .proposals import (
    FusedProposal,
    ProposalProvenance,
    ProposalSource,
    iter_fused_records,
)
from .settings import SearchSettings
from .state import state_fingerprint


def _root_matches_current_proposal(
    root: object,
    state: PackingState,
    pool: Sequence[ItemSpec | dict],
    proposal: PlacementProposal,
    profile_digest: str,
) -> bool:
    """Check all receipt/action bindings without trusting a minted object."""

    if (
        not isinstance(root, ValidatedRoot)
        or root._proof is not _VALIDATION_TOKEN
        or not root.strict
        or root.rule_violations != 0
        or root.profile_digest != profile_digest
        or root.proposal != proposal
        or root.source != proposal.source
        or not root.box.axis_aligned
        or proposal.pool_index >= len(pool)
        or proposal.container_index >= len(state.containers)
        or state.containers[proposal.container_index].ordinal
        != proposal.container_index
    ):
        return False
    raw_item = pool[proposal.pool_index]
    try:
        item = raw_item if isinstance(raw_item, ItemSpec) else ItemSpec.from_dict(raw_item)
    except (KeyError, TypeError, ValueError):
        return False
    expected_key = (
        proposal.item_index,
        proposal.pool_index,
        proposal.container_index,
        proposal.orientation,
        tuple(round(value, 7) for value in proposal.position),
    )
    expected_fingerprint = state_fingerprint(
        state, pool, proposal.pool_index, profile_digest
    )
    expected_dimensions = np.asarray(
        oriented_dimensions(item.dimensions, proposal.orientation), dtype=np.float64
    )
    return bool(
        item.index == proposal.item_index
        and tuple(root.item_signature) == _item_signature(item)
        and tuple(root.proposal_key) == expected_key
        and root.state_fingerprint == expected_fingerprint
        and np.allclose(
            root.box.center,
            np.asarray(proposal.position, dtype=np.float64),
            rtol=0.0,
            atol=1e-8,
        )
        and np.allclose(
            root.box.dimensions, expected_dimensions, rtol=0.0, atol=1e-8
        )
        and math.isfinite(root.support_ratio)
        and root.support_ratio >= 0.0
        and math.isfinite(root.min_clearance)
        and root.min_clearance >= 0.0
    )


def _fresh_receipt_matches(diagnosed: object, fresh: object) -> bool:
    """Mirror the formatter/transition full receipt comparison."""

    return bool(
        isinstance(diagnosed, ValidatedRoot)
        and isinstance(fresh, ValidatedRoot)
        and fresh is not diagnosed
        and diagnosed._proof is _VALIDATION_TOKEN
        and fresh._proof is _VALIDATION_TOKEN
        and diagnosed.proposal == fresh.proposal
        and np.array_equal(diagnosed.box.minimum, fresh.box.minimum)
        and np.array_equal(diagnosed.box.maximum, fresh.box.maximum)
        and diagnosed.box.axis_aligned == fresh.box.axis_aligned
        and diagnosed.profile_digest == fresh.profile_digest
        and diagnosed.state_fingerprint == fresh.state_fingerprint
        and diagnosed.item_signature == fresh.item_signature
        and diagnosed.proposal_key == fresh.proposal_key
        and diagnosed.support_ratio == fresh.support_ratio
        and diagnosed.min_clearance == fresh.min_clearance
        and diagnosed.source == fresh.source
        and diagnosed.rule_violations == fresh.rule_violations == 0
        and diagnosed.strict
        and fresh.strict
    )


@dataclass(frozen=True)
class RootRecord:
    """One exact root plus proposal provenance and scheduling metadata."""

    root: ValidatedRoot
    provenance: ProposalProvenance
    pass_name: str
    raw_ordinal: int

    @property
    def proposal(self) -> PlacementProposal:
        return self.root.proposal

    @property
    def pool_index(self) -> int:
        return self.root.proposal.pool_index

    @property
    def item_index(self) -> int:
        return self.root.proposal.item_index

    @property
    def container_index(self) -> int:
        return self.root.proposal.container_index

    @property
    def orientation(self) -> int:
        return self.root.proposal.orientation

    @property
    def stable_key(self) -> tuple:
        return (
            self.pool_index,
            self.item_index,
            self.container_index,
            self.orientation,
            tuple(round(value, 7) for value in self.proposal.position),
            self.pass_name,
        )


@dataclass(frozen=True)
class CatalogStats:
    raw_examined: int = 0
    exact_attempts: int = 0
    accepted_roots: int = 0
    duplicate_roots: int = 0
    normal_roots: int = 0
    deferred_roots: int = 0
    rescue_roots: int = 0
    per_pool_raw: tuple[int, ...] = ()
    per_pool_roots: tuple[int, ...] = ()
    rejection_counts: tuple[tuple[str, int], ...] = ()
    item_exceptions: tuple[tuple[int, str], ...] = ()
    passes_completed: tuple[str, ...] = ()
    deadline_reached: bool = False
    global_cap_reached: bool = False
    stage_attempts: tuple[tuple[str, int], ...] = ()
    stage_roots: tuple[tuple[str, int], ...] = ()
    first_root_stage: tuple[str | None, ...] = ()
    fixed_pools_attempted: int = 0
    fixed_pools_covered: int = 0
    fixed_exact_attempt_cap: int = 0
    fixed_quota_exhausted: bool = False
    adaptive_dense_activated: bool = False
    adaptive_dense_raw_generated: int = 0
    adaptive_dense_exact_attempts: int = 0
    adaptive_dense_covered_occurrences: int = 0
    adaptive_dense_early_stop: bool = False
    adaptive_dense_deadline_reached: bool = False
    adaptive_dense_raw_per_pool: tuple[int, ...] = ()
    adaptive_dense_exact_per_pool: tuple[int, ...] = ()

    def rejection_count(self, reason: str | RejectReason) -> int:
        key = reason.value if isinstance(reason, RejectReason) else str(reason)
        return dict(self.rejection_counts).get(key, 0)


@dataclass(frozen=True)
class RootCatalog:
    records: tuple[RootRecord, ...]
    stats: CatalogStats

    def __iter__(self) -> Iterator[RootRecord]:
        return iter(self.records)

    def __len__(self) -> int:
        return len(self.records)

    def __bool__(self) -> bool:
        return bool(self.records)

    @property
    def roots(self) -> tuple[ValidatedRoot, ...]:
        return tuple(record.root for record in self.records)

    def for_pool(self, pool_index: int) -> tuple[RootRecord, ...]:
        return tuple(record for record in self.records if record.pool_index == pool_index)

    @classmethod
    def empty(cls, pool_size: int = 0) -> "RootCatalog":
        counts = tuple(0 for _ in range(max(0, int(pool_size))))
        first = tuple(None for _ in counts)
        return cls(
            (),
            CatalogStats(
                per_pool_raw=counts,
                per_pool_roots=counts,
                first_root_stage=first,
            ),
        )


@dataclass(frozen=True)
class CatalogWorkQuota:
    """Deterministic work budget for coverage-first analytical scans."""

    per_pool_raw_limit: int = 128
    global_exact_attempt_cap: int = 64
    include_dense: bool = False
    include_deferred: bool = False
    include_rescue: bool = False

    def __post_init__(self) -> None:
        if type(self.per_pool_raw_limit) is not int or self.per_pool_raw_limit <= 0:
            raise ValueError("per_pool_raw_limit must be a positive exact int")
        if (
            type(self.global_exact_attempt_cap) is not int
            or self.global_exact_attempt_cap <= 0
        ):
            raise ValueError("global_exact_attempt_cap must be a positive exact int")
        for name in ("include_dense", "include_deferred", "include_rescue"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be an exact bool")


@dataclass(frozen=True)
class AdaptiveDenseRescueConfig:
    """Non-profile work policy for a globally empty strict catalog."""

    raw_work_limit: int = 4096
    covered_occurrence_target: int = 8
    output_reserve_seconds: float = 0.75

    def __post_init__(self) -> None:
        if type(self.raw_work_limit) is not int or self.raw_work_limit <= 0:
            raise ValueError("raw_work_limit must be a positive exact int")
        if (
            type(self.covered_occurrence_target) is not int
            or self.covered_occurrence_target <= 0
        ):
            raise ValueError(
                "covered_occurrence_target must be a positive exact int"
            )
        reserve = float(self.output_reserve_seconds)
        if reserve != reserve or reserve in (float("inf"), -float("inf")) or reserve < 0.0:
            raise ValueError("output_reserve_seconds must be finite and non-negative")


@dataclass
class _PoolWork:
    pool_index: int
    item: ItemSpec | None
    failed: bool = False
    seen_exact: set[tuple] | None = None

    def __post_init__(self) -> None:
        self.seen_exact = set()


@dataclass(frozen=True)
class _FamilyStage:
    name: str
    families: tuple[ProposalSource, ...]
    raw_budget: int


class _StatsBuilder:
    def __init__(self, pool_size: int) -> None:
        self.raw_examined = 0
        self.exact_attempts = 0
        self.duplicate_roots = 0
        self.normal_roots = 0
        self.deferred_roots = 0
        self.rescue_roots = 0
        self.per_pool_raw = [0] * pool_size
        self.per_pool_roots = [0] * pool_size
        self.rejections: Counter[str] = Counter()
        self.item_exceptions: list[tuple[int, str]] = []
        self.passes_completed: list[str] = []
        self.deadline_reached = False
        self.global_cap_reached = False
        self.stage_attempts: Counter[str] = Counter()
        self.stage_roots: Counter[str] = Counter()
        self.first_root_stage: list[str | None] = [None] * pool_size
        self.fixed_pools_attempted = 0
        self.fixed_pools_covered = 0
        self.fixed_exact_attempt_cap = 0
        self.fixed_quota_exhausted = False
        self.adaptive_dense_activated = False
        self.adaptive_dense_raw_generated = 0
        self.adaptive_dense_exact_attempts = 0
        self.adaptive_dense_covered_occurrences = 0
        self.adaptive_dense_early_stop = False
        self.adaptive_dense_deadline_reached = False
        self.adaptive_dense_raw_per_pool = [0] * pool_size
        self.adaptive_dense_exact_per_pool = [0] * pool_size

    def freeze(self, accepted_roots: int) -> CatalogStats:
        return CatalogStats(
            raw_examined=self.raw_examined,
            exact_attempts=self.exact_attempts,
            accepted_roots=accepted_roots,
            duplicate_roots=self.duplicate_roots,
            normal_roots=self.normal_roots,
            deferred_roots=self.deferred_roots,
            rescue_roots=self.rescue_roots,
            per_pool_raw=tuple(self.per_pool_raw),
            per_pool_roots=tuple(self.per_pool_roots),
            rejection_counts=tuple(sorted(self.rejections.items())),
            item_exceptions=tuple(self.item_exceptions),
            passes_completed=tuple(self.passes_completed),
            deadline_reached=self.deadline_reached,
            global_cap_reached=self.global_cap_reached,
            stage_attempts=tuple(self.stage_attempts.items()),
            stage_roots=tuple(self.stage_roots.items()),
            first_root_stage=tuple(self.first_root_stage),
            fixed_pools_attempted=self.fixed_pools_attempted,
            fixed_pools_covered=self.fixed_pools_covered,
            fixed_exact_attempt_cap=self.fixed_exact_attempt_cap,
            fixed_quota_exhausted=self.fixed_quota_exhausted,
            adaptive_dense_activated=self.adaptive_dense_activated,
            adaptive_dense_raw_generated=self.adaptive_dense_raw_generated,
            adaptive_dense_exact_attempts=self.adaptive_dense_exact_attempts,
            adaptive_dense_covered_occurrences=self.adaptive_dense_covered_occurrences,
            adaptive_dense_early_stop=self.adaptive_dense_early_stop,
            adaptive_dense_deadline_reached=self.adaptive_dense_deadline_reached,
            adaptive_dense_raw_per_pool=tuple(self.adaptive_dense_raw_per_pool),
            adaptive_dense_exact_per_pool=tuple(self.adaptive_dense_exact_per_pool),
        )


class StrictRootScanner:
    """Family-yield staged scan followed by optional rootless-only dense work."""

    def __init__(
        self,
        settings: SearchSettings | None = None,
        *,
        mask: ExactMask | None = None,
        per_pool_cap: int = 8,
        global_cap: int = 64,
        first_pass_raw_cap: int = 16,
        pass2_raw_increment: int = 256,
        adaptive_dense_rescue: AdaptiveDenseRescueConfig | None = None,
        clock=None,
    ) -> None:
        self.settings = settings or SearchSettings()
        self.mask = mask or ExactMask(self.settings)
        if self.mask.profile_digest != self.settings.profile_digest():
            raise ValueError("exact mask profile does not match catalog settings profile")
        self.per_pool_cap = max(1, int(per_pool_cap))
        self.global_cap = max(1, int(global_cap))
        self.first_pass_raw_cap = max(1, int(first_pass_raw_cap))
        self.pass2_raw_increment = max(1, int(pass2_raw_increment))
        if adaptive_dense_rescue is not None and not isinstance(
            adaptive_dense_rescue, AdaptiveDenseRescueConfig
        ):
            raise TypeError(
                "adaptive_dense_rescue must be AdaptiveDenseRescueConfig or None"
            )
        self.adaptive_dense_rescue = adaptive_dense_rescue
        self.clock = clock or time.perf_counter

    def scan(
        self,
        state: PackingState,
        pool: Sequence[ItemSpec | dict],
        *,
        deadline: float | None = None,
        breadth_rescue: bool = False,
        allow_deferred: bool = True,
        allow_rescue: bool = True,
        advisory_proposals: Sequence[PlacementProposal] = (),
    ) -> RootCatalog:
        if not isinstance(state, PackingState):
            raise TypeError("state must be a PackingState")
        if pool is None:
            raise TypeError("ordered pool is required")
        ordered_pool = tuple(pool)
        if not ordered_pool:
            return RootCatalog.empty()
        started_at = float(self.clock())
        if deadline is None:
            hard_deadline = started_at + self.settings.zero_root_rescue_limit_seconds
        else:
            hard_deadline = float(deadline)
        normal_deadline = min(
            hard_deadline,
            started_at + self.settings.normal_catalog_limit_seconds,
        )

        stats = _StatsBuilder(len(ordered_pool))
        accepted: list[RootRecord] = []
        accepted_keys: set[tuple] = set()
        work: list[_PoolWork] = []
        for pool_index, raw_item in enumerate(ordered_pool):
            try:
                item = raw_item if isinstance(raw_item, ItemSpec) else ItemSpec.from_dict(raw_item)
                if not isinstance(item, ItemSpec):
                    raise TypeError("pool entry must be ItemSpec or dict")
            except Exception as error:
                stats.item_exceptions.append((pool_index, f"{type(error).__name__}: {error}"))
                work.append(_PoolWork(pool_index, None, failed=True))
            else:
                work.append(_PoolWork(pool_index, item))

        # The default empty advisory sequence deliberately leaves the legacy
        # B/C path byte-for-byte unchanged.  Mode A may prepend up to six
        # current-state hints, but only fully matched fresh exact receipts are
        # admitted as ordinary catalog members.
        if advisory_proposals:
            self._scan_advisory(
                state,
                ordered_pool,
                work,
                advisory_proposals,
                normal_deadline,
                accepted,
                accepted_keys,
                stats,
            )

        stages = self._normal_stages()
        self._scan_stages(
            state,
            ordered_pool,
            work,
            stages,
            normal_deadline,
            accepted,
            accepted_keys,
            stats,
            pass_name="normal",
            deferred=False,
        )
        # Keep historical pass labels stable for diagnostics even though the
        # work is now scheduled by proposal-family yield.
        stats.passes_completed.extend(("coverage", "scarcity"))

        deferred_targets = [
            entry
            for entry in work
            if allow_deferred
            and not entry.failed
            and entry.item is not None
            and stats.per_pool_roots[entry.pool_index] == 0
            and self._has_deferred_tier(state, entry.item)
        ]
        if deferred_targets and not self._expired(normal_deadline, stats):
            self._scan_stages(
                state,
                ordered_pool,
                deferred_targets,
                stages,
                normal_deadline,
                accepted,
                accepted_keys,
                stats,
                pass_name="deferred",
                deferred=True,
            )

        if len(accepted) >= self.global_cap:
            stats.global_cap_reached = True

        # Default recovery only follows a globally empty normal catalog.
        # Breadth recovery is explicit and is still restricted to rootless
        # pool positions.  Rescue families never share a provenance record
        # with normal families.
        rescue_targets: list[_PoolWork] = []
        if len(accepted) == 0:
            rescue_targets = [entry for entry in work if not entry.failed and entry.item is not None]
        elif breadth_rescue:
            rescue_targets = [
                entry for entry in work
                if not entry.failed
                and entry.item is not None
                and stats.per_pool_roots[entry.pool_index] == 0
            ]
        if (
            self.adaptive_dense_rescue is not None
            and allow_rescue
            and len(accepted) == 0
            and rescue_targets
        ):
            self._scan_adaptive_dense(
                state,
                ordered_pool,
                rescue_targets,
                hard_deadline,
                accepted,
                accepted_keys,
                stats,
            )
            stats.passes_completed.append("adaptive_rescue")
        elif allow_rescue and rescue_targets and not self._expired(hard_deadline, stats):
            dense_budget = min(
                self.settings.raw_proposal_limit,
                max(128, self.first_pass_raw_cap, self.pass2_raw_increment),
            )
            self._scan_stages(
                state,
                ordered_pool,
                rescue_targets,
                (
                    _FamilyStage(
                        "dense_last",
                        (ProposalSource.DENSE_SUPPORT_LATTICE,),
                        dense_budget,
                    ),
                ),
                hard_deadline,
                accepted,
                accepted_keys,
                stats,
                pass_name="rescue",
                deferred=False,
            )
            stats.passes_completed.append("rescue")

        if len(accepted) >= self.global_cap:
            stats.global_cap_reached = True
        return RootCatalog(tuple(accepted), stats.freeze(len(accepted)))

    def _scan_advisory(
        self,
        state: PackingState,
        pool: tuple[ItemSpec | dict, ...],
        work: Sequence[_PoolWork],
        proposals: Sequence[PlacementProposal],
        deadline: float,
        accepted: list[RootRecord],
        accepted_keys: set[tuple],
        stats: _StatsBuilder,
    ) -> None:
        seen: set[tuple] = set()
        attempts = 0
        for proposal in proposals:
            if attempts >= 6 or self._expired(deadline, stats):
                break
            if not isinstance(proposal, PlacementProposal):
                continue
            key = self._proposal_key(proposal)
            if key in seen:
                stats.duplicate_roots += 1
                continue
            seen.add(key)
            attempts += 1
            pool_index = proposal.pool_index
            if pool_index >= len(pool) or pool_index >= len(work):
                stats.rejections["advisory_pool_binding"] += 1
                continue
            current = work[pool_index]
            if current.failed or current.item is None:
                stats.rejections["advisory_pool_binding"] += 1
                continue
            current.seen_exact.add(key)
            stats.raw_examined += 1
            stats.per_pool_raw[pool_index] += 1
            stats.exact_attempts += 1
            stats.stage_attempts["advisory"] += 1
            try:
                trace = self.mask.diagnose(
                    state, pool, proposal, deadline=deadline
                )
            except Exception as error:
                stats.item_exceptions.append(
                    (pool_index, f"{type(error).__name__}: {error}")
                )
                continue
            if self._expired(deadline, stats):
                stats.rejections[RejectReason.DEADLINE.value] += 1
                break
            if not trace.accepted or trace.root is None:
                reason = (
                    trace.first_reason.value
                    if trace.first_reason is not None
                    else "unknown"
                )
                stats.rejections[reason] += 1
                continue
            diagnosed = trace.root
            try:
                root = self.mask.validate(
                    state, pool, proposal, deadline=deadline
                )
            except Exception as error:
                stats.item_exceptions.append(
                    (pool_index, f"{type(error).__name__}: {error}")
                )
                continue
            if self._expired(deadline, stats):
                stats.rejections[RejectReason.DEADLINE.value] += 1
                break
            if root is None:
                reason = (
                    RejectReason.DEADLINE.value
                    if float(self.clock()) >= float(deadline)
                    else "accept_revalidation_failed"
                )
                stats.rejections[reason] += 1
                continue
            if not (
                _root_matches_current_proposal(
                    diagnosed, state, pool, proposal, self.mask.profile_digest
                )
                and _root_matches_current_proposal(
                    root, state, pool, proposal, self.mask.profile_digest
                )
                and _fresh_receipt_matches(diagnosed, root)
            ):
                stats.rejections["invalid_exact_evidence"] += 1
                continue
            root_key = tuple(root.proposal_key)
            if root_key in accepted_keys:
                stats.duplicate_roots += 1
                continue
            if (
                stats.per_pool_roots[pool_index] >= self.per_pool_cap
                or len(accepted) >= self.global_cap
            ):
                continue
            accepted_keys.add(root_key)
            accepted.append(
                RootRecord(
                    root=root,
                    provenance=ProposalProvenance(
                        (proposal.source or "mode_a_advisory",),
                        ("mode_a_advisory",),
                        (),
                    ),
                    pass_name="advisory",
                    raw_ordinal=stats.raw_examined - 1,
                )
            )
            stats.per_pool_roots[pool_index] += 1
            stats.stage_roots["advisory"] += 1
            if stats.first_root_stage[pool_index] is None:
                stats.first_root_stage[pool_index] = "advisory"
            stats.normal_roots += 1

    def _scan_adaptive_dense(
        self,
        state: PackingState,
        pool: tuple[ItemSpec | dict, ...],
        targets: Sequence[_PoolWork],
        hard_deadline: float,
        accepted: list[RootRecord],
        accepted_keys: set[tuple],
        stats: _StatsBuilder,
    ) -> None:
        """Expose one strict dense root per occurrence under a reserved deadline."""

        config = self.adaptive_dense_rescue
        if config is None:
            return
        stats.adaptive_dense_activated = True
        adaptive_deadline = float(hard_deadline) - float(
            config.output_reserve_seconds
        )
        if float(self.clock()) >= adaptive_deadline:
            stats.adaptive_dense_deadline_reached = True
            return

        ordered = sorted(
            (
                current
                for current in targets
                if not current.failed and current.item is not None
            ),
            key=lambda current: current.pool_index,
        )
        pending: list[tuple[_PoolWork, list[FusedProposal], int]] = []
        for ordinal, current in enumerate(ordered):
            if float(self.clock()) >= adaptive_deadline:
                stats.adaptive_dense_deadline_reached = True
                break
            generation_deadline = self._fair_generation_deadline(
                adaptive_deadline, len(ordered) - ordinal
            )
            records = self._generate(
                state,
                current,
                generation_deadline,
                stats,
                deferred=False,
                family_subset=(ProposalSource.DENSE_SUPPORT_LATTICE,),
                raw_budget=config.raw_work_limit,
            )
            if records is None:
                continue
            stats.adaptive_dense_raw_generated += len(records)
            stats.adaptive_dense_raw_per_pool[current.pool_index] += len(records)
            unseen = [
                record
                for record in records
                if self._proposal_key(record.proposal) not in current.seen_exact
            ]
            if unseen:
                pending.append((current, unseen, 0))

        target = min(
            config.covered_occurrence_target,
            self.global_cap,
            len(ordered),
        )
        while pending:
            if float(self.clock()) >= adaptive_deadline:
                stats.adaptive_dense_deadline_reached = True
                return
            next_pending: list[tuple[_PoolWork, list[FusedProposal], int]] = []
            progressed = False
            for current, records, cursor in pending:
                if float(self.clock()) >= adaptive_deadline:
                    stats.adaptive_dense_deadline_reached = True
                    return
                if stats.per_pool_roots[current.pool_index] > 0:
                    continue
                fused = None
                while cursor < len(records):
                    candidate = records[cursor]
                    cursor += 1
                    key = self._proposal_key(candidate.proposal)
                    if key not in current.seen_exact:
                        current.seen_exact.add(key)
                        fused = candidate
                        break
                if fused is None:
                    continue
                progressed = True
                stats.adaptive_dense_exact_attempts += 1
                stats.adaptive_dense_exact_per_pool[current.pool_index] += 1
                self._consider_adaptive(
                    state,
                    pool,
                    fused,
                    adaptive_deadline,
                    accepted,
                    accepted_keys,
                    stats,
                )
                if float(self.clock()) >= adaptive_deadline:
                    stats.adaptive_dense_deadline_reached = True
                    return
                covered = sum(1 for value in stats.per_pool_roots if value > 0)
                stats.adaptive_dense_covered_occurrences = covered
                if covered >= target or len(accepted) >= self.global_cap:
                    stats.adaptive_dense_early_stop = True
                    return
                if (
                    stats.per_pool_roots[current.pool_index] == 0
                    and cursor < len(records)
                ):
                    next_pending.append((current, records, cursor))
            if not progressed:
                break
            pending = next_pending
        stats.adaptive_dense_covered_occurrences = sum(
            1 for value in stats.per_pool_roots if value > 0
        )

    def _consider_adaptive(
        self,
        state: PackingState,
        pool: tuple[ItemSpec | dict, ...],
        fused: FusedProposal,
        deadline: float,
        accepted: list[RootRecord],
        accepted_keys: set[tuple],
        stats: _StatsBuilder,
    ) -> None:
        pool_index = fused.proposal.pool_index
        stage_name = "adaptive.dense_global_zero"
        stats.raw_examined += 1
        stats.per_pool_raw[pool_index] += 1
        stats.exact_attempts += 1
        stats.stage_attempts[stage_name] += 1
        try:
            trace = self.mask.diagnose(
                state, pool, fused.proposal, deadline=deadline
            )
        except Exception as error:
            stats.item_exceptions.append(
                (pool_index, f"{type(error).__name__}: {error}")
            )
            return
        if float(self.clock()) >= float(deadline):
            stats.rejections[RejectReason.DEADLINE.value] += 1
            return
        if not trace.accepted or trace.root is None:
            reason = (
                trace.first_reason.value
                if trace.first_reason is not None
                else "unknown"
            )
            stats.rejections[reason] += 1
            return
        diagnosed = trace.root
        try:
            root = self.mask.validate(
                state, pool, fused.proposal, deadline=deadline
            )
        except Exception as error:
            stats.item_exceptions.append(
                (pool_index, f"{type(error).__name__}: {error}")
            )
            return
        if float(self.clock()) >= float(deadline):
            stats.rejections[RejectReason.DEADLINE.value] += 1
            return
        if root is None:
            stats.rejections["accept_revalidation_failed"] += 1
            return
        if not (
            _root_matches_current_proposal(
                diagnosed,
                state,
                pool,
                fused.proposal,
                self.mask.profile_digest,
            )
            and _root_matches_current_proposal(
                root,
                state,
                pool,
                fused.proposal,
                self.mask.profile_digest,
            )
            and _fresh_receipt_matches(diagnosed, root)
        ):
            stats.rejections["invalid_exact_evidence"] += 1
            return
        root_key = tuple(root.proposal_key)
        if root_key in accepted_keys:
            stats.duplicate_roots += 1
            return
        if (
            stats.per_pool_roots[pool_index] > 0
            or len(accepted) >= self.global_cap
        ):
            return
        accepted_keys.add(root_key)
        accepted.append(
            RootRecord(
                root=root,
                provenance=fused.provenance,
                pass_name="rescue",
                raw_ordinal=stats.raw_examined - 1,
            )
        )
        stats.per_pool_roots[pool_index] += 1
        stats.stage_roots[stage_name] += 1
        stats.first_root_stage[pool_index] = stage_name
        stats.rescue_roots += 1

    def scan_coverage_fixed(
        self,
        state: PackingState,
        pool: Sequence[ItemSpec | dict],
        *,
        deadline: float,
        quota: CatalogWorkQuota,
        allow_deferred: bool = False,
        allow_rescue: bool = False,
    ) -> RootCatalog:
        """Return at most one strict root per occurrence under fixed work.

        Proposal materialisation is bounded independently for every ordered
        pool occurrence.  Exact attempts then advance one occurrence at a
        time, so all available first attempts precede every second attempt.
        """

        if not isinstance(state, PackingState):
            raise TypeError("state must be a PackingState")
        if not isinstance(quota, CatalogWorkQuota):
            raise TypeError("quota must be a CatalogWorkQuota")
        if not isinstance(deadline, (int, float)):
            raise TypeError("deadline must be a finite number")
        hard_deadline = float(deadline)
        if not hard_deadline == hard_deadline or hard_deadline in (float("inf"), -float("inf")):
            raise ValueError("deadline must be finite")
        if allow_deferred and not quota.include_deferred:
            raise ValueError("deferred work requires quota.include_deferred")
        if allow_rescue and not quota.include_rescue:
            raise ValueError("rescue work requires quota.include_rescue")

        ordered_pool = tuple(pool)
        if not ordered_pool:
            return RootCatalog.empty()
        stats = _StatsBuilder(len(ordered_pool))
        stats.fixed_exact_attempt_cap = quota.global_exact_attempt_cap
        accepted: list[RootRecord] = []
        accepted_keys: set[tuple] = set()
        generated: list[list[FusedProposal]] = [[] for _ in ordered_pool]
        converted: list[ItemSpec | None] = []
        families = [
            ProposalSource.FREE_RECTANGLE_BOUNDARY,
            ProposalSource.OBSTACLE_FACE_EXTREME,
            ProposalSource.PLANE_DERIVED_EDGE,
            ProposalSource.FLOOR_WALL_EXTREME,
            ProposalSource.RESERVED_SUPPORT_LATTICE,
            ProposalSource.SUPPORT_EDGE_FLUSH,
            ProposalSource.LEGACY_EXTREME_CROSS,
        ]
        if quota.include_dense:
            families.append(ProposalSource.DENSE_SUPPORT_LATTICE)

        for pool_index, raw_item in enumerate(ordered_pool):
            try:
                item = raw_item if isinstance(raw_item, ItemSpec) else ItemSpec.from_dict(raw_item)
                if not isinstance(item, ItemSpec):
                    raise TypeError("pool entry must be ItemSpec or dict")
            except Exception as error:
                stats.item_exceptions.append(
                    (pool_index, f"{type(error).__name__}: {error}")
                )
                converted.append(None)
                continue
            converted.append(item)
            if self._expired(hard_deadline, stats):
                break
            remaining_pools = len(ordered_pool) - pool_index
            generation_deadline = self._fair_generation_deadline(
                hard_deadline, remaining_pools
            )
            try:
                if allow_rescue:
                    records = list(
                        iter_fused_records(
                            state,
                            item,
                            pool_index,
                            deadline=generation_deadline,
                            rescue_only=True,
                            settings=self.settings,
                            raw_work_limit=quota.per_pool_raw_limit,
                            quantum=self.settings.proposal_quantum,
                            clock=self.clock,
                        )
                    )
                else:
                    records = list(
                        iter_fused_records(
                            state,
                            item,
                            pool_index,
                            deadline=generation_deadline,
                            deferred=allow_deferred,
                            family_subset=tuple(families),
                            settings=self.settings,
                            raw_work_limit=quota.per_pool_raw_limit,
                            quantum=self.settings.proposal_quantum,
                            clock=self.clock,
                        )
                    )
                generated[pool_index] = records[: quota.per_pool_raw_limit]
            except Exception as error:
                stats.item_exceptions.append(
                    (pool_index, f"{type(error).__name__}: {error}")
                )

        cursors = [0] * len(ordered_pool)
        seen_proposals: list[set[tuple]] = [set() for _ in ordered_pool]
        stopped = [item is None for item in converted]
        attempted_pools: set[int] = set()
        while not self._expired(hard_deadline, stats):
            progressed = False
            for pool_index, records in enumerate(generated):
                if stopped[pool_index]:
                    continue
                if stats.exact_attempts >= quota.global_exact_attempt_cap:
                    stats.fixed_quota_exhausted = True
                    break
                cursor = cursors[pool_index]
                fused = None
                while cursor < len(records):
                    candidate = records[cursor]
                    cursor += 1
                    key = self._proposal_key(candidate.proposal)
                    if key not in seen_proposals[pool_index]:
                        seen_proposals[pool_index].add(key)
                        fused = candidate
                        break
                cursors[pool_index] = cursor
                if fused is None:
                    stopped[pool_index] = True
                    continue
                progressed = True
                attempted_pools.add(pool_index)
                stats.raw_examined += 1
                stats.per_pool_raw[pool_index] += 1
                stats.exact_attempts += 1
                stats.stage_attempts["fixed.normal"] += 1
                try:
                    trace = self.mask.diagnose(
                        state, ordered_pool, fused.proposal, deadline=hard_deadline
                    )
                except Exception as error:
                    stats.item_exceptions.append(
                        (pool_index, f"{type(error).__name__}: {error}")
                    )
                    continue
                if self._expired(hard_deadline, stats):
                    break
                if not trace.accepted:
                    reason = (
                        trace.first_reason.value
                        if trace.first_reason is not None
                        else "unknown"
                    )
                    stats.rejections[reason] += 1
                    continue
                root = trace.root
                if (
                    not isinstance(root, ValidatedRoot)
                    or not root.strict
                    or root.rule_violations != 0
                    or root.profile_digest != self.mask.profile_digest
                ):
                    stats.rejections["accept_revalidation_failed"] += 1
                    continue
                root_key = tuple(root.proposal_key)
                if root_key in accepted_keys:
                    stats.duplicate_roots += 1
                    continue
                accepted_keys.add(root_key)
                accepted.append(
                    RootRecord(
                        root,
                        fused.provenance,
                        "normal",
                        stats.raw_examined - 1,
                    )
                )
                stats.per_pool_roots[pool_index] = 1
                stats.normal_roots += 1
                stats.stage_roots["fixed.normal"] += 1
                stats.first_root_stage[pool_index] = "fixed.normal"
                stopped[pool_index] = True
                if len(accepted) >= self.global_cap:
                    stats.global_cap_reached = True
                    break
            if (
                stats.fixed_quota_exhausted
                or stats.global_cap_reached
                or not progressed
            ):
                break
        stats.fixed_pools_attempted = len(attempted_pools)
        stats.fixed_pools_covered = sum(1 for count in stats.per_pool_roots if count)
        if stats.exact_attempts >= quota.global_exact_attempt_cap:
            stats.fixed_quota_exhausted = True
        return RootCatalog(tuple(accepted), stats.freeze(len(accepted)))

    build = scan

    def _normal_stages(self) -> tuple[_FamilyStage, ...]:
        raw_limit = max(1, int(self.settings.raw_proposal_limit))
        probe = min(raw_limit, self.first_pass_raw_cap)
        deepen = min(raw_limit, max(128, probe))
        return (
            _FamilyStage("free_probe", (ProposalSource.FREE_RECTANGLE_BOUNDARY,), probe),
            _FamilyStage("obstacle_probe", (ProposalSource.OBSTACLE_FACE_EXTREME,), probe),
            _FamilyStage("plane_probe", (ProposalSource.PLANE_DERIVED_EDGE,), probe),
            _FamilyStage("free_deepen", (ProposalSource.FREE_RECTANGLE_BOUNDARY,), deepen),
            _FamilyStage("obstacle_deepen", (ProposalSource.OBSTACLE_FACE_EXTREME,), deepen),
            _FamilyStage("plane_deepen", (ProposalSource.PLANE_DERIVED_EDGE,), deepen),
            _FamilyStage(
                "compact",
                (
                    ProposalSource.FLOOR_WALL_EXTREME,
                    ProposalSource.RESERVED_SUPPORT_LATTICE,
                    ProposalSource.SUPPORT_EDGE_FLUSH,
                ),
                deepen,
            ),
            _FamilyStage("legacy", (ProposalSource.LEGACY_EXTREME_CROSS,), deepen),
        )

    def _scan_stages(
        self,
        state: PackingState,
        pool: tuple[ItemSpec | dict, ...],
        targets: Sequence[_PoolWork],
        stages: Sequence[_FamilyStage],
        deadline: float,
        accepted: list[RootRecord],
        accepted_keys: set[tuple],
        stats: _StatsBuilder,
        *,
        pass_name: str,
        deferred: bool,
    ) -> None:
        quantum = max(1, int(self.settings.proposal_quantum))
        for stage in stages:
            if self._expired(deadline, stats) or len(accepted) >= self.global_cap:
                return
            stage_name = f"{pass_name}.{stage.name}"
            ordered = sorted(
                (
                    entry
                    for entry in targets
                    if not entry.failed
                    and entry.item is not None
                    and stats.per_pool_roots[entry.pool_index] < self.per_pool_cap
                ),
                key=lambda entry: (stats.per_pool_roots[entry.pool_index], entry.pool_index),
            )
            pending: list[tuple[_PoolWork, list[FusedProposal], int]] = []
            for ordinal, current in enumerate(ordered):
                if self._expired(deadline, stats) or len(accepted) >= self.global_cap:
                    return
                remaining_pools = len(ordered) - ordinal
                generation_deadline = self._fair_generation_deadline(
                    deadline, remaining_pools
                )
                records = self._generate(
                    state,
                    current,
                    generation_deadline,
                    stats,
                    deferred=deferred,
                    family_subset=stage.families,
                    raw_budget=stage.raw_budget,
                )
                if records is None:
                    continue
                unseen = [
                    record
                    for record in records
                    if self._proposal_key(record.proposal) not in current.seen_exact
                ]
                if unseen:
                    pending.append((current, unseen, 0))

            # A family stage is consumed in deterministic item quanta.  This
            # makes proposal construction quotas primary while retaining the
            # absolute wall-clock guard before each exact check.
            while pending and not self._expired(deadline, stats):
                next_pending: list[tuple[_PoolWork, list[FusedProposal], int]] = []
                for current, records, cursor in pending:
                    if self._expired(deadline, stats) or len(accepted) >= self.global_cap:
                        return
                    if stats.per_pool_roots[current.pool_index] >= self.per_pool_cap:
                        continue
                    stop = min(len(records), cursor + quantum)
                    roots_before = stats.per_pool_roots[current.pool_index]
                    for fused in records[cursor:stop]:
                        if self._expired(deadline, stats) or len(accepted) >= self.global_cap:
                            return
                        key = self._proposal_key(fused.proposal)
                        if key in current.seen_exact:
                            continue
                        current.seen_exact.add(key)
                        self._consider(
                            state,
                            pool,
                            fused,
                            pass_name,
                            stage_name,
                            deadline,
                            accepted,
                            accepted_keys,
                            stats,
                        )
                        if stats.per_pool_roots[current.pool_index] >= self.per_pool_cap:
                            break
                        if (
                            stage.name.endswith("_probe")
                            and stats.per_pool_roots[current.pool_index] > roots_before
                        ):
                            break
                    if (
                        stop < len(records)
                        and stats.per_pool_roots[current.pool_index] < self.per_pool_cap
                        and not (
                            stage.name.endswith("_probe")
                            and stats.per_pool_roots[current.pool_index] > roots_before
                        )
                    ):
                        next_pending.append((current, records, stop))
                pending = next_pending

    def _generate(
        self,
        state: PackingState,
        current: _PoolWork,
        deadline: float,
        stats: _StatsBuilder,
        *,
        deferred: bool,
        family_subset: tuple[ProposalSource, ...],
        raw_budget: int,
    ) -> list[FusedProposal] | None:
        try:
            return list(
                iter_fused_records(
                    state,
                    current.item,
                    current.pool_index,
                    deadline=deadline,
                    deferred=deferred,
                    family_subset=family_subset,
                    settings=self.settings,
                    raw_work_limit=raw_budget,
                    quantum=self.settings.proposal_quantum,
                    clock=self.clock,
                )
            )
        except Exception as error:
            stats.item_exceptions.append(
                (current.pool_index, f"{type(error).__name__}: {error}")
            )
            current.failed = True
            return None

    def _consider(
        self,
        state: PackingState,
        pool: tuple[ItemSpec | dict, ...],
        fused: FusedProposal,
        pass_name: str,
        stage_name: str,
        deadline: float,
        accepted: list[RootRecord],
        accepted_keys: set[tuple],
        stats: _StatsBuilder,
    ) -> None:
        pool_index = fused.proposal.pool_index
        stats.raw_examined += 1
        stats.per_pool_raw[pool_index] += 1
        stats.exact_attempts += 1
        stats.stage_attempts[stage_name] += 1
        try:
            trace = self.mask.diagnose(state, pool, fused.proposal, deadline=deadline)
        except Exception as error:
            stats.item_exceptions.append(
                (pool_index, f"{type(error).__name__}: {error}")
            )
            return
        if not trace.accepted:
            reason = trace.first_reason.value if trace.first_reason is not None else "unknown"
            stats.rejections[reason] += 1
            return
        # Diagnostics cheaply classify the rejection-heavy stream.  Only a
        # diagnostic accept is run through validate, ensuring every exposed
        # catalog root is a fresh receipt returned by the authoritative API.
        try:
            root = self.mask.validate(state, pool, fused.proposal, deadline=deadline)
        except Exception as error:
            stats.item_exceptions.append(
                (pool_index, f"{type(error).__name__}: {error}")
            )
            return
        if root is None:
            reason = (
                RejectReason.DEADLINE.value
                if float(self.clock()) >= float(deadline)
                else "accept_revalidation_failed"
            )
            stats.rejections[reason] += 1
            return
        if not isinstance(root, ValidatedRoot) or not root.strict:
            stats.rejections["invalid_exact_evidence"] += 1
            return
        root_key = tuple(root.proposal_key)
        if root_key in accepted_keys:
            stats.duplicate_roots += 1
            return
        if stats.per_pool_roots[pool_index] >= self.per_pool_cap or len(accepted) >= self.global_cap:
            return
        accepted_keys.add(root_key)
        accepted.append(
            RootRecord(
                root=root,
                provenance=fused.provenance,
                pass_name=pass_name,
                raw_ordinal=stats.raw_examined - 1,
            )
        )
        stats.per_pool_roots[pool_index] += 1
        stats.stage_roots[stage_name] += 1
        if stats.first_root_stage[pool_index] is None:
            stats.first_root_stage[pool_index] = stage_name
        if pass_name == "normal":
            stats.normal_roots += 1
        elif pass_name == "deferred":
            stats.deferred_roots += 1
        else:
            stats.rescue_roots += 1

    def _expired(self, deadline: float, stats: _StatsBuilder) -> bool:
        expired = float(self.clock()) >= float(deadline)
        if expired:
            stats.deadline_reached = True
        return expired

    def _fair_generation_deadline(self, deadline: float, remaining_pools: int) -> float:
        """Reserve an equal share of remaining construction time per pool.

        Proposal iterators already round-robin orientation/family/container
        work.  This outer slice prevents one pool occurrence from consuming
        the entire stage deadline while materialising its bounded records.
        """

        now = float(self.clock())
        remaining = max(1, int(remaining_pools))
        if now >= float(deadline):
            return float(deadline)
        # Construction may consume at most half of the remaining interval.
        # The other half is retained for ExactMask diagnose/validate work on
        # the records already materialised by every visible pool occurrence.
        return min(
            float(deadline),
            now + 0.5 * (float(deadline) - now) / float(remaining),
        )

    @staticmethod
    def _proposal_key(proposal: PlacementProposal) -> tuple:
        return (
            proposal.pool_index,
            proposal.container_index,
            proposal.orientation,
            tuple(round(value, 4) for value in proposal.position),
        )

    @staticmethod
    def _has_deferred_tier(state: PackingState, item: ItemSpec) -> bool:
        if item.is_prioritized:
            return False
        return any(not container.is_prioritized for container in state.containers) and any(
            container.is_prioritized for container in state.containers
        )

__all__ = [
    "AdaptiveDenseRescueConfig",
    "CatalogStats",
    "CatalogWorkQuota",
    "RootCatalog",
    "RootRecord",
    "StrictRootScanner",
]
