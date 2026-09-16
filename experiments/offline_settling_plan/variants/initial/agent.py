"""Mode-A order planning backed by virtual native validation and settling."""
from collections import deque
import copy
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
    # Task A has a long optimization allowance.  Keep a margin for the
    # runner while spending the bulk of it on complete settled virtual trials.
    offline_budget_seconds = 150.0
    planning_policy_seconds = 5.8
    planning_preview_search_seconds = 2.8
    planning_max_candidate_checks = 4200
    planning_candidate_point_limit = 220
    # Native transport queries are cheap compared with settling trials.  Keep
    # this wide enough to reach a valid low-ranked basin after early rejects;
    # the per-trial deadline remains the hard bound.
    planning_max_authorizations = 96

    def __init__(self, module_path):
        super().__init__(module_path)
        self.last_diagnostics = {}
        self._preview = None
        self._native = {}
        self._historical_prefix_active = True
        self._planning = False
        self._capture_preview_state = False
        self._last_preview_result = None
        self.offline_diagnostics = {}
        self.last_plan_stats = {}

    def get_init_states(self, init_states):
        result = super().get_init_states(init_states)
        self._historical_prefix_active = True
        self._planning = False
        self._capture_preview_state = False
        self._last_preview_result = None
        for validator in self._native.values():
            validator.close()
        self._native = {}
        if self._preview is not None:
            self._preview.close()
            self._preview = None
        return result

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
            self._last_preview_result = None
            return True
        if self._preview is None:
            from .preview import SettlingPreview
            self._preview = SettlingPreview()
        result = self._preview.evaluate(observation['container_list'][action['container_idx']],
                                        observation['pool_list'][action['item_idx']], action,
                                        deadline=self._policy_deadline,
                                        capture_final_state=self._planning and self._capture_preview_state)
        self._last_preview_result = result
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

    @staticmethod
    def _item_equivalence_key(item):
        """Return the physical identity used to collapse duplicate cargo.

        Stream indices and runtime poses are intentionally excluded.  Two
        occurrences with the same physical profile have the same feasible
        placements, so one representative is enough during a virtual trial.
        """
        keys = ('length', 'width', 'height', 'mass', 'is_prioritized', 'is_soft',
                'lateralFriction', 'rollingFriction', 'spinningFriction',
                'restitution', 'angularDamping', 'contactStiffness',
                'contactDamping', 'linearDamping')
        return tuple((key, item.get(key)) for key in keys)

    @classmethod
    def _representatives(cls, remaining):
        representatives = []
        seen = set()
        for item in remaining:
            key = cls._item_equivalence_key(item)
            if key in seen:
                continue
            seen.add(key)
            representatives.append(item)
        return representatives

    @staticmethod
    def _diversify(candidates, pool):
        """Interleave spatial basins while retaining each basin's ranking."""
        groups = {}
        seen = set()
        for key, action in sorted(candidates, key=lambda pair: pair[0], reverse=True):
            pos = action['place_pos']
            cargo = pool[action['item_idx']]
            dims = h.orientation_dims(cargo, action['orientation'])
            physical = (tuple(dims), tuple((name, cargo.get(name)) for name in
                        ('mass', 'is_soft', 'lateralFriction', 'rollingFriction',
                         'spinningFriction', 'restitution', 'angularDamping',
                         'contactStiffness', 'contactDamping', 'linearDamping')))
            exact = (action['container_idx'], physical,
                     tuple(float(v) for v in pos))
            if exact in seen:
                continue
            seen.add(exact)
            basin = (action['container_idx'],
                     round(float(pos[2] - dims[2] * .5) / .15),
                     round(float(pos[0]) / .3), round(float(pos[1]) / .3))
            groups.setdefault(basin, []).append((key, action))
        basins = [list(key) for key in groups]
        result = []
        while groups:
            for basin in list(groups):
                result.append(groups[basin].pop(0))
                if not groups[basin]:
                    del groups[basin]
        return result, basins

    @staticmethod
    def _apply_settled_state(container, item, action, result):
        """Update a virtual container with every pose returned by preview."""
        poses = {
            int(packed['index']): packed
            for packed in result.get('final_packed_items', [])
            if packed.get('index') is not None and packed.get('pos') is not None
        }
        for packed in container.setdefault('packed_items', []):
            updated = poses.get(int(packed.get('index', -1)))
            if updated is None:
                continue
            packed['pos'] = list(updated['pos'])
            packed['orn'] = list(updated['orn'])

        placed = dict(item)
        final_position = result.get('final_position')
        final_orientation = result.get('final_orientation')
        if final_position is None or final_orientation is None:
            center = np.asarray(action['place_pos'], dtype=np.float64)
            center[0] += float(container.get('center', [0.])[0])
            final_position = center.tolist()
            final_orientation = h._orientation_quat(int(action['orientation']))
        placed['pos'] = list(final_position)
        placed['orn'] = list(final_orientation)
        placed['belongs_to'] = int(container.get('index', 0))
        container.setdefault('packed_items', []).append(placed)

    def optimize(self, item_list):
        """Build an order from virtual actions that passed full settling.

        Each accepted preview becomes the next virtual state.  If the
        physics-backed prefix cannot continue, the unresolved occurrences are
        appended in the historical deterministic order so optimization always
        returns a complete permutation.
        """
        self.offline_plan = {}
        self.offline_rank = {}
        remaining = [dict(item) for item in item_list]
        if not remaining:
            self.offline_diagnostics = {'planned_count': 0, 'remaining_count': 0,
                                        'planned_order_length': 0,
                                        'plan_complete': True,
                                        'stop_reason': 'empty_input'}
            self.last_plan_stats = dict(self.offline_diagnostics)
            return []
        if not self.containers:
            ordered = sorted(remaining, key=h._static_order_key)
            self.offline_diagnostics = {
                'planned_count': 0, 'remaining_count': len(ordered),
                'planned_order_length': len(ordered), 'plan_complete': True,
                'stop_reason': 'no_containers', 'elapsed_seconds': 0.,
            }
            self.last_plan_stats = dict(self.offline_diagnostics)
            return [int(item['index']) for item in ordered]

        virtual_containers = copy.deepcopy(self.containers)
        planned = []
        started = time.perf_counter()
        overall_deadline = started + float(self.offline_budget_seconds)
        old_settings = (
            self.policy_seconds, self.preview_search_seconds,
            self.max_candidate_checks, self.candidate_point_limit,
            self.max_authorizations, self.use_settling_preview,
        )
        self._planning = True
        self._capture_preview_state = True
        self.use_settling_preview = True
        self.policy_seconds = float(self.planning_policy_seconds)
        self.preview_search_seconds = float(self.planning_preview_search_seconds)
        self.max_candidate_checks = int(self.planning_max_candidate_checks)
        self.candidate_point_limit = int(self.planning_candidate_point_limit)
        self.max_authorizations = int(self.planning_max_authorizations)
        try:
            stop_reason = 'completed_prefix'
            while remaining and time.perf_counter() < overall_deadline:
                representatives = self._representatives(remaining)
                if not representatives:
                    break
                # Keep the per-trial deadline inside the remaining overall
                # budget.  The online policy still uses its normal settings
                # after this method returns.
                left = overall_deadline - time.perf_counter()
                if left <= 0.15:
                    stop_reason = 'overall_budget'
                    break
                self.policy_seconds = min(float(self.planning_policy_seconds), max(0.2, left - 0.05))
                observation = {
                    'optimize': True,
                    'lookahead_k': len(representatives),
                    'pool_list': representatives,
                    'container_list': virtual_containers,
                }
                self._last_preview_result = None
                try:
                    action = self._search_policy(observation)
                except NoValidAction:
                    stop_reason = 'no_settled_action'
                    break
                pool_idx = int(action.get('item_idx', -1))
                if not 0 <= pool_idx < len(representatives):
                    stop_reason = 'invalid_planner_action'
                    break
                item = representatives[pool_idx]
                result = self._last_preview_result
                if not result or not result.get('safe'):
                    stop_reason = 'missing_settling_result'
                    break
                container_idx = int(action.get('container_idx', -1))
                if not 0 <= container_idx < len(virtual_containers):
                    stop_reason = 'invalid_container'
                    break
                container = virtual_containers[container_idx]
                self._apply_settled_state(container, item, action, result)
                item_id = int(item['index'])
                self.offline_plan[item_id] = {
                    'container_idx': container_idx,
                    'place_pos': np.asarray(action['place_pos'], dtype=np.float32).copy(),
                    'orientation': int(action['orientation']),
                }
                self.offline_rank[item_id] = len(planned)
                planned.append(item_id)
                # Identity removes the selected occurrence even when a test
                # fixture intentionally contains duplicate stream indices.
                for occurrence, candidate in enumerate(remaining):
                    if candidate is item or candidate.get('index') == item.get('index'):
                        remaining.pop(occurrence)
                        break
            remaining.sort(key=h._static_order_key)
            planned.extend(int(item['index']) for item in remaining)
            self.offline_diagnostics = {
                'planned_count': len(self.offline_plan),
                'remaining_count': len(remaining),
                'planned_order_length': len(planned),
                'plan_complete': not remaining,
                'elapsed_seconds': time.perf_counter() - started,
                'budget_seconds': float(self.offline_budget_seconds),
                'stop_reason': stop_reason,
                'deduplicated_last_pool': len(representatives) if 'representatives' in locals() else 0,
            }
            self.last_plan_stats = dict(self.offline_diagnostics)
            return planned
        finally:
            self._planning = False
            self._capture_preview_state = False
            (self.policy_seconds, self.preview_search_seconds,
             self.max_candidate_checks, self.candidate_point_limit,
             self.max_authorizations, self.use_settling_preview) = old_settings
            for validator in self._native.values():
                validator.close()
            self._native = {}
            if self._preview is not None:
                self._preview.close()
                self._preview = None

    def _recover_action(self, observation):
        """Return the best current-state action after a planned/search miss."""
        candidates = []
        try:
            candidates.append(h.Agent.policy(self, observation))
        except Exception:
            pass
        try:
            candidates.append(h._fallback_action(observation))
        except Exception:
            pass
        previous_preview = self.use_settling_preview
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            for preview_enabled in (previous_preview, False):
                self.use_settling_preview = preview_enabled
                try:
                    accepted = self._authorize(candidate, observation, 'recovery')
                except Exception:
                    accepted = None
                if accepted is not None:
                    self.use_settling_preview = previous_preview
                    return accepted
        self.use_settling_preview = previous_preview
        # The historical fallback has the official action shape.  Returning it
        # keeps the runner alive if no native-valid recovery remains; the
        # environment then records the physical failure in its normal path.
        return candidates[-1] if candidates else {
            'item_idx': 0, 'container_idx': 0,
            'place_pos': np.asarray([0., 0., .1], dtype=np.float32),
            'orientation': 0,
        }

    def policy(self, observation):
        try:
            return self._search_policy(observation)
        except NoValidAction:
            if self._planning:
                raise
            return self._recover_action(observation)

    def _search_policy(self, observation):
        started = time.perf_counter()
        self._policy_deadline = started + self.policy_seconds
        self._last_preview_result = None
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
        if (not self._planning and self.use_offline_plan and
                observation.get('optimize') and self.offline_plan):
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
        narrow_shortlist = []
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
            # Keep a compact high-score stream as a control, while retaining
            # the full stream for a second spatially diverse pass.
            narrow_shortlist.append((key, action))
            if len(narrow_shortlist) > self.shortlist_limit * 2:
                narrow_shortlist.sort(key=lambda pair: pair[0], reverse=True)
                del narrow_shortlist[self.shortlist_limit:]
        self.last_diagnostics['candidate_checks'] = checked
        narrow, narrow_basins = self._diversify(narrow_shortlist, pool)
        wide, wide_basins = self._diversify(shortlist, pool)
        self.last_diagnostics['narrow_basins'] = narrow_basins
        self.last_diagnostics['candidate_basins'] = wide_basins
        remaining = deque(
            [('narrow', action) for _, action in narrow[:self.shortlist_limit]] +
            [('wide', action) for _, action in wide[:self.shortlist_limit]]
        )
        deferred = deque()
        revisit_failed_supports = False
        attempted = set()
        self.last_diagnostics['deferred_support_candidates'] = 0
        while remaining or deferred:
            if not remaining:
                remaining, deferred = deferred, deque()
                revisit_failed_supports = True
            _stage, action = remaining.popleft()
            if (time.perf_counter() >= started + self.policy_seconds or
                    self.last_diagnostics['authorizations'] >= self.max_authorizations):
                break
            exact = (action['item_idx'], action['container_idx'], action['orientation'],
                     tuple(float(v) for v in action['place_pos']))
            if exact in attempted:
                continue
            if (self.use_settling_preview and not revisit_failed_supports and
                    self._support_items(action, observation) & self._failed_supports):
                deferred.append((None,action))
                self.last_diagnostics['deferred_support_candidates'] += 1
                continue
            attempted.add(exact)
            accepted = self._authorize(action, observation, 'fair_search')
            if accepted is not None:
                self.last_diagnostics['elapsed'] = time.perf_counter() - started
                return accepted
        self.last_diagnostics['elapsed'] = time.perf_counter() - started
        raise NoValidAction(f'No authorized candidate: {self.last_diagnostics}')
