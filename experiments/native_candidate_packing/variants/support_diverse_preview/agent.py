"""Native-validated support candidates with a bounded settling preview option.

Historical optimization, support thresholds, and scoring remain unchanged.
Footprint-aligned and dense support roots supplement historical candidates.
"""
from collections import deque
import time

import numpy as np

from . import historical as h
from .candidates import mixed_points, SharedPoints
from .native import NativeValidator


class NoValidAction(RuntimeError):
    """The bounded search found no currently authorized action."""


class Agent(h.Agent):
    max_candidate_checks = 6500
    candidate_point_limit = 300
    search_seconds = 3.0
    policy_seconds = 5.2
    shortlist_limit = 96
    max_authorizations = 96
    use_offline_plan = True
    use_support_candidates = True
    use_settling_preview = True
    preview_search_seconds = 1.5
    reject_preview_volume_loss = False
    prefer_historical_action = False
    backfill_weight = 0.

    def __init__(self, module_path):
        super().__init__(module_path)
        self.last_diagnostics = {}
        self._preview = None
        self._native = {}
        self._historical_prefix_active = True

    @staticmethod
    def _prefilter(item, container, dims, center, packed, shelves):
        # Preserve the historical support checks; the approximate historical
        # transport test is deliberately absent. Native queries own that test.
        if not h._inside_container(container, center, dims, -.007):
            return False, 0., h._floor_z(container)
        if not h._target_clear(center, dims, packed, shelves):
            return False, 0., h._floor_z(container)
        ratio, support_z = h._support_ratio(container, center, dims, packed)
        threshold = .72 if float(item.get('mass',1.)) >= 12. else .62
        if item.get('is_soft',False):
            threshold = max(threshold,.70)
        return (ratio >= threshold and h._center_supported(container, center, dims, packed)), ratio, support_z

    def _preview_action(self, action, observation):
        if not self.use_settling_preview:
            return True
        if self._preview is None:
            from .preview import SettlingPreview
            self._preview = SettlingPreview()
        result = self._preview.evaluate(observation['container_list'][action['container_idx']],
                                        observation['pool_list'][action['item_idx']], action,
                                        deadline=self._policy_deadline)
        supports = self._support_items(action, observation)
        self.last_diagnostics['previews'].append(dict(action={key: value.tolist() if hasattr(value, 'tolist') else value
                                                             for key, value in action.items()},
                                                       support_items=[list(value) for value in sorted(supports)], **result))
        if not result['safe'] and result['steps'] == 300:
            self._failed_supports.update(supports)
        return result['safe'] and (not self.reject_preview_volume_loss or result['lost_volume'] == 0.)

    def _support_items(self, action, observation):
        """Identify observed contact supporters, independent of target rotation."""
        ci = int(action['container_idx'])
        container = observation['container_list'][ci]
        cargo = observation['pool_list'][int(action['item_idx'])]
        half = np.asarray(h.orientation_dims(cargo, int(action['orientation']))) * .5
        center = np.asarray(action['place_pos'], dtype=np.float64)
        bottom = center[2]-half[2]
        low, high = center[:2]-half[:2], center[:2]+half[:2]
        supporters = set()
        if abs(bottom-h._floor_z(container)) <= .03:
            supporters.add((ci,'floor',-1))
        packed, shelves = self._current_geometry[ci]
        for lo, hi, meta in packed+shelves:
            if abs(bottom-float(hi[2])) <= .03 and h._rect_overlap_area(low,high,lo[:2],hi[:2]) > 1e-8:
                supporters.add((ci,str(meta.get('kind','cargo')),int(meta.get('index',-1))))
        return frozenset(supporters)

    def _authorize(self, action, observation, route):
        ci, pi = int(action['container_idx']), int(action['item_idx'])
        if ci not in self._native:
            self._native[ci] = NativeValidator(observation['container_list'][ci])
        result = self._native[ci].check(observation['pool_list'][pi], action, deadline=self._policy_deadline)
        self.last_diagnostics['authorizations'] += 1
        if all(result[key] for key in ('included','target_clear','transport')):
            if not self._preview_action(action, observation):
                return None
            return dict(item_idx=pi,container_idx=ci,orientation=int(action['orientation']),
                        place_pos=np.asarray(action['place_pos'],dtype=np.float32).copy())
        reasons = self.last_diagnostics['rejections']
        for reason in ('included','target_clear','transport','deadline_exceeded'):
            if (reason == 'deadline_exceeded' and result[reason]) or (reason != 'deadline_exceeded' and not result[reason]):
                reasons[reason] = reasons.get(reason, 0) + 1
        return None

    def policy(self, observation):
        started = time.perf_counter()
        self._policy_deadline = started + self.policy_seconds
        for validator in self._native.values():
            validator.close()
        self._native = {}
        self._failed_supports = set()
        self.last_diagnostics = dict(candidate_checks=0, combinations_visited=0,
                                     authorizations=0, rejections={}, previews=[], elapsed=0.)
        pool = list(observation.get('pool_list', []))
        containers = list(observation.get('container_list', []))
        if not pool or not containers:
            raise NoValidAction('No visible cargo or containers')
        geometry = [(h._packed_boxes_for_container(c), h._shelf_boxes(c)) for c in containers]
        self._current_geometry = geometry

        # Optional controlled successor: preserve the historical trajectory
        # while its proposed actions continue to pass current-state checks.
        if self.prefer_historical_action and self._historical_prefix_active:
            historical_action = h.Agent.policy(self, observation)
            if time.perf_counter() < self._policy_deadline:
                accepted = self._authorize(historical_action, observation, 'historical_policy')
                if accepted is not None:
                    self.last_diagnostics['elapsed'] = time.perf_counter() - started
                    return accepted
            # Once the historical path fails, preserve the remaining budget in
            # subsequent observations for native recovery rather than repeat it.
            self._historical_prefix_active = False

        # Preserve the historical virtual plan, but never return it unchecked.
        if self.use_offline_plan and observation.get('optimize') and self.offline_plan:
            plans = sorted((self.offline_rank.get(it['index'], 10**9), pi, it,
                            self.offline_plan[it['index']])
                           for pi, it in enumerate(pool) if it['index'] in self.offline_plan)
            for _, pi, it, plan in plans:
                if time.perf_counter() >= started + self.policy_seconds:
                    break
                ci, orn = int(plan['container_idx']), int(plan['orientation'])
                if not 0 <= ci < len(containers) or not 0 <= orn < 6:
                    continue
                packed, shelves = geometry[ci]
                dims = h.orientation_dims(it, orn)
                if not self._prefilter(it, containers[ci], dims, plan['place_pos'], packed, shelves)[0]:
                    continue
                action = dict(item_idx=pi, container_idx=ci, orientation=orn,
                              place_pos=np.asarray(plan['place_pos'], dtype=np.float32))
                accepted = self._authorize(action, observation, 'historical_plan')
                if accepted is not None:
                    self.last_diagnostics['elapsed'] = time.perf_counter() - started
                    return accepted

        # One point per combination per round. Container varies fastest, then
        # orientation, then visible item: no combination can consume the budget.
        ranked = sorted(enumerate(pool), key=lambda pair: (-h._item_urgency(pair[1]), pair[0]))
        pending = deque()
        point_cache = {}
        acceptance_cache = {}
        for pi, it in ranked:
            for orn, dims in h._unique_orientations(it):
                for ci, c in enumerate(containers):
                    if any(d > float(c[key]) + 1e-6 for d, key in zip(dims, ('length','width','height'))):
                        continue
                    pending.append((pi, ci, orn, dims, None))
        shortlist = []
        checked = 0
        search_duration = self.preview_search_seconds if self.use_settling_preview else self.search_seconds
        search_deadline = min(started + self.policy_seconds - 1.5, time.perf_counter() + search_duration)
        while pending and checked < self.max_candidate_checks and time.perf_counter() < search_deadline:
            pi, ci, orn, dims, points = pending.popleft()
            it, c = pool[pi], containers[ci]
            packed, shelves = geometry[ci]
            if points is None:
                generator = mixed_points if self.use_support_candidates else h._candidate_points
                geometry_key = (ci, tuple(dims))
                if geometry_key not in point_cache:
                    point_cache[geometry_key] = SharedPoints(generator(c, dims, packed, max_points=self.candidate_point_limit))
                points = iter(point_cache[geometry_key])
                self.last_diagnostics['combinations_visited'] += 1
            try:
                center = next(points)
            except StopIteration:
                continue
            pending.append((pi, ci, orn, dims, points))
            checked += 1
            acceptance_key = (ci, tuple(dims), tuple(center), float(it.get('mass', 1.)) >= 12., bool(it.get('is_soft', False)))
            if acceptance_key not in acceptance_cache:
                acceptance_cache[acceptance_key] = self._prefilter(it, c, dims, center, packed, shelves)
            ok, ratio, support_z = acceptance_cache[acceptance_key]
            if not ok:
                continue
            score = h._score_candidate(it, c, dims, center, ratio, support_z, c.get('packed_items', []), containers)
            score += self.backfill_weight * (center[1]/float(c['width'])+.5)
            key = (score, -center[2], center[1], -abs(center[0]), -orn, -pi, -ci)
            action = dict(item_idx=int(pi), container_idx=int(ci), orientation=int(orn),
                          place_pos=np.asarray(center, dtype=np.float32))
            shortlist.append((key, action))
            # Candidate generation already has a fixed check/time budget.
            # Keep those bounded roots until basin diversification; trimming
            # by score here used to erase every feasible low-ranked basin.
        self.last_diagnostics['candidate_checks'] = checked
        shortlist.sort(key=lambda pair: pair[0], reverse=True)
        if shortlist:
            # Try one representative from each support basin before revisiting
            # nearly identical tower placements. This is search diversity, not
            # an extra physical rejection criterion.
            groups = {}
            seen_physical = set()
            for key, action in shortlist:
                pos = action['place_pos']
                cargo = pool[action['item_idx']]
                dims = h.orientation_dims(cargo, action['orientation'])
                physical = (tuple(dims), tuple((name, cargo.get(name)) for name in
                            ('mass','is_soft','lateralFriction','rollingFriction','spinningFriction',
                             'restitution','angularDamping','contactStiffness','contactDamping','linearDamping')))
                exact = (action['container_idx'], physical, tuple(float(v) for v in pos))
                if exact in seen_physical:
                    continue
                seen_physical.add(exact)
                basin = (action['container_idx'],
                         round(float(pos[2]-dims[2]*.5)/.15),
                         round(float(pos[0])/.3), round(float(pos[1])/.3))
                groups.setdefault(basin, []).append((key, action))
            self.last_diagnostics['candidate_basins'] = [list(key) for key in groups]
            shortlist = []
            while groups:
                for basin in list(groups):
                    shortlist.append(groups[basin].pop(0))
                    if not groups[basin]:
                        del groups[basin]
        remaining = deque(shortlist[:self.shortlist_limit])
        deferred = deque()
        revisit_failed_supports = False
        self.last_diagnostics['deferred_support_candidates'] = 0
        while remaining or deferred:
            if not remaining:
                remaining, deferred = deferred, deque()
                revisit_failed_supports = True
            _, action = remaining.popleft()
            if (time.perf_counter() >= started + self.policy_seconds or
                    self.last_diagnostics['authorizations'] >= self.max_authorizations):
                break
            if (self.use_settling_preview and not revisit_failed_supports and
                    self._support_items(action, observation) & self._failed_supports):
                deferred.append((None,action))
                self.last_diagnostics['deferred_support_candidates'] += 1
                continue
            accepted = self._authorize(action, observation, 'fair_search')
            if accepted is not None:
                self.last_diagnostics['elapsed'] = time.perf_counter() - started
                return accepted
        self.last_diagnostics['elapsed'] = time.perf_counter() - started
        raise NoValidAction(f'No authorized candidate: {self.last_diagnostics}')
