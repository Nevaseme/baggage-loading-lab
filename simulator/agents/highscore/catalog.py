"""Exact feasibility mask for compressed EMS root actions."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Sequence

from .candidates import CandidateGenerator
from .ems import ProxyAction, ProxyState, apply_action, build_proxy_state, propose_actions
from .model import Candidate, ItemSpec, PackingState
from .scoring import CandidateScorer
from .settings import SearchSettings


@dataclass(frozen=True)
class RootAction:
    candidate: Candidate
    proxy_action: ProxyAction
    next_state: ProxyState


def _root_key(root: RootAction, *, urgency: float, rarity: float) -> tuple:
    candidate = root.candidate
    return (
        candidate.rule_violations,
        -urgency,
        -rarity,
        -candidate.support_ratio,
        -candidate.min_clearance,
        float(candidate.box.maximum[2]),
        candidate.item.index,
        candidate.pool_index,
        candidate.container_index,
        candidate.orientation,
        *(float(value) for value in candidate.position),
    )


def build_root_catalog(
    state: PackingState,
    pool: Sequence[ItemSpec],
    generator: CandidateGenerator,
    settings: SearchSettings,
    *,
    deadline: float,
) -> list[RootAction]:
    """Build a bounded, deterministic catalog of exact-valid root actions."""
    start = time.perf_counter()
    catalog_deadline = min(deadline, start + max(0.0, settings.ems_root_budget_seconds))
    if not pool or start >= catalog_deadline:
        return []

    proxy_state = build_proxy_state(
        state,
        settings.path_clearance,
        support_inset=max(0.0, -settings.inclusion_margin),
        shelf_drop_gap=settings.shelf_drop_gap,
    )
    records: list[tuple[RootAction, float, float]] = []
    item_count = len(pool)
    for pool_index, item in enumerate(pool):
        now = time.perf_counter()
        if now >= catalog_deadline or len(records) >= settings.ems_root_catalog_limit:
            break
        remaining_items = item_count - pool_index
        item_deadline = now + (catalog_deadline - now) / max(1, remaining_items)
        try:
            proposals = propose_actions(
                proxy_state,
                item,
                pool_index,
                limit=settings.ems_proxy_actions_per_item,
                deadline=item_deadline,
            )
        except Exception:
            continue

        accepted = 0
        for proposal in proposals:
            now = time.perf_counter()
            if (
                now >= item_deadline
                or now >= catalog_deadline
                or accepted >= settings.ems_exact_roots_per_item
                or len(records) >= settings.ems_root_catalog_limit
            ):
                break
            try:
                candidate = generator.validate_proposal(state, proposal)
                if candidate is None:
                    continue
                successor = apply_action(proxy_state, proposal, settings.path_clearance)
            except Exception:
                continue
            if successor is None:
                continue
            accepted += 1
            rarity = 1.0 / max(1, len(proposals))
            urgency = CandidateScorer.item_urgency(item, state.containers)
            records.append((RootAction(candidate, proposal, successor), urgency, rarity))

    ordered = sorted(records, key=lambda record: _root_key(record[0], urgency=record[1], rarity=record[2]))
    return [root for root, _, _ in ordered[: settings.ems_root_catalog_limit]]
