"""Budget-fair historical candidates with current-observation authorization.

Historical optimization, candidate geometry, support thresholds, and scoring
remain unchanged. Search allocation and rejection recovery are the experiment.
"""
from collections import deque
import time

import numpy as np

from . import historical as h
from .authorizer import (AuthorizerProfile, authorize_current,
                         format_authorized_action, proposal_from_action)


class NoValidAction(RuntimeError):
    """The bounded search found no currently authorized action."""


class Agent(h.Agent):
    max_candidate_checks = 6500
    candidate_point_limit = 300
    search_seconds = 3.0
    policy_seconds = 5.2
    shortlist_limit = 96
    max_authorizations = 12
    use_offline_plan = True

    def __init__(self, module_path):
        super().__init__(module_path)
        self.profile = AuthorizerProfile()
        self.last_diagnostics = {}

    def _authorize(self, action, observation, route):
        result = authorize_current(
            proposal_from_action(action, observation, route=route, source_key='fair_candidate_packing'),
            observation, profile=self.profile)
        self.last_diagnostics['authorizations'] += 1
        if result.accepted:
            return format_authorized_action(result, observation, profile=self.profile)
        reasons = self.last_diagnostics['rejections']
        for reason in result.reject_reasons:
            reasons[reason] = reasons.get(reason, 0) + 1
        return None

    def policy(self, observation):
        started = time.perf_counter()
        self.last_diagnostics = dict(candidate_checks=0, combinations_visited=0,
                                     authorizations=0, rejections={}, elapsed=0.)
        pool = list(observation.get('pool_list', []))
        containers = list(observation.get('container_list', []))
        if not pool or not containers:
            raise NoValidAction('No visible cargo or containers')
        geometry = [(h._packed_boxes_for_container(c), h._shelf_boxes(c)) for c in containers]

        # Preserve the historical virtual plan, but never return it unchecked.
        if self.use_offline_plan and observation.get('optimize') and self.offline_plan:
            plans = sorted((self.offline_rank.get(it['index'], 10**9), pi, it,
                            self.offline_plan[it['index']])
                           for pi, it in enumerate(pool) if it['index'] in self.offline_plan)
            for _, pi, it, plan in plans:
                ci, orn = int(plan['container_idx']), int(plan['orientation'])
                if not 0 <= ci < len(containers) or not 0 <= orn < 6:
                    continue
                packed, shelves = geometry[ci]
                dims = h.orientation_dims(it, orn)
                if not h._candidate_is_acceptable(it, containers[ci], dims, plan['place_pos'], packed, shelves)[0]:
                    continue
                action = dict(item_idx=pi, container_idx=ci, orientation=orn,
                              place_pos=np.asarray(plan['place_pos'], dtype=np.float32))
                accepted = self._authorize(action, observation, 'historical_plan')
                if accepted is not None:
                    self.last_diagnostics['elapsed'] = time.perf_counter() - started
                    return accepted
                break

        # One point per combination per round. Container varies fastest, then
        # orientation, then visible item: no combination can consume the budget.
        ranked = sorted(enumerate(pool), key=lambda pair: (-h._item_urgency(pair[1]), pair[0]))
        pending = deque()
        for pi, it in ranked:
            for orn, dims in h._unique_orientations(it):
                for ci, c in enumerate(containers):
                    if any(d > float(c[key]) + 1e-6 for d, key in zip(dims, ('length','width','height'))):
                        continue
                    pending.append((pi, ci, orn, dims, None))
        shortlist = []
        checked = 0
        search_deadline = min(started + self.policy_seconds - 1.5, time.perf_counter() + self.search_seconds)
        while pending and checked < self.max_candidate_checks and time.perf_counter() < search_deadline:
            pi, ci, orn, dims, points = pending.popleft()
            it, c = pool[pi], containers[ci]
            packed, shelves = geometry[ci]
            if points is None:
                points = iter(h._candidate_points(c, dims, packed, max_points=self.candidate_point_limit))
                self.last_diagnostics['combinations_visited'] += 1
            try:
                center = next(points)
            except StopIteration:
                continue
            pending.append((pi, ci, orn, dims, points))
            checked += 1
            ok, ratio, support_z = h._candidate_is_acceptable(it, c, dims, center, packed, shelves)
            if not ok:
                continue
            score = h._score_candidate(it, c, dims, center, ratio, support_z, c.get('packed_items', []), containers)
            key = (score, -center[2], center[1], -abs(center[0]), -orn, -pi, -ci)
            action = dict(item_idx=int(pi), container_idx=int(ci), orientation=int(orn),
                          place_pos=np.asarray(center, dtype=np.float32))
            shortlist.append((key, action))
            if len(shortlist) > self.shortlist_limit * 2:
                shortlist.sort(key=lambda pair: pair[0], reverse=True)
                del shortlist[self.shortlist_limit:]
        self.last_diagnostics['candidate_checks'] = checked
        shortlist.sort(key=lambda pair: pair[0], reverse=True)
        for _, action in shortlist[:self.shortlist_limit]:
            if (time.perf_counter() >= started + self.policy_seconds or
                    self.last_diagnostics['authorizations'] >= self.max_authorizations):
                break
            accepted = self._authorize(action, observation, 'fair_search')
            if accepted is not None:
                self.last_diagnostics['elapsed'] = time.perf_counter() - started
                return accepted
        self.last_diagnostics['elapsed'] = time.perf_counter() - started
        raise NoValidAction(f'No authorized candidate: {self.last_diagnostics}')
