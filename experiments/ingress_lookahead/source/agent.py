"""Native-validated packing with bounded future-ingress lookahead."""
from collections import deque
import copy
from itertools import islice
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
    # Keep a seven-second internal deadline under the official eight-second
    # policy allowance; native future probes share this same deadline.
    policy_seconds = 7.0
    shortlist_limit = 96
    non_c_max_authorizations = 96
    c_max_authorizations = 384
    max_authorizations = non_c_max_authorizations
    use_offline_plan = True
    use_support_candidates = True
    use_settling_preview = True
    preview_search_seconds = 3.0
    reject_preview_volume_loss = False
    # These are explicit variant switches.  A keeps the measured offline
    # order by default; C keeps the historical prefix.  The mode guard below
    # prevents a late B observation with one visible item from entering C.
    use_historical_prefix_a = False
    use_historical_prefix_c = True
    backfill_weight = 0.
    use_ingress_lookahead = True
    lookahead_candidate_limit = 24
    lookahead_type_limit = 8
    lookahead_points_per_type = 36
    lookahead_valid_limit = 8
    lookahead_seconds = 1.6
    preview_reserve_seconds = 3.0
    future_fit_weight = 18.0
    future_loss_penalty = 60.0
    future_all_fit_bonus = 20.0
    future_basin_weight = 1.5
    future_slot_weight = .5

    def __init__(self, module_path):
        super().__init__(module_path)
        self.last_diagnostics = {}
        self._preview = None
        self._native = {}
        self._historical_prefix_active = True
        self._lookahead_cache = {}
        self._lookahead_deadline = None
        self.mode = None
        self._historical_prefix_enabled = False

    def get_init_states(self, init_states):
        """Install the mode once; later pool size must not change policy."""
        result = super().get_init_states(init_states)
        if self.optimize_enabled:
            self.mode = 'A'
        elif self.lookahead_k > 1:
            self.mode = 'B'
        else:
            self.mode = 'C'
        self._historical_prefix_enabled = bool(
            (self.mode == 'A' and self.use_historical_prefix_a)
            or (self.mode == 'C' and self.use_historical_prefix_c)
        )
        self._historical_prefix_active = self._historical_prefix_enabled
        self.max_authorizations = int(
            self.c_max_authorizations if self.mode == 'C'
            else self.non_c_max_authorizations
        )
        self._lookahead_cache = {}
        self._lookahead_deadline = None
        for validator in self._native.values():
            validator.close()
        self._native = {}
        return result

    def _lookahead_allowed(self, pool):
        """Return whether the initialized mode may use ingress lookahead."""
        if not self.use_ingress_lookahead:
            return False
        if self.mode is None:
            # Direct helper calls in focused tests have no lifecycle call.
            # The public policy path always has an initialized mode.
            return len(pool) > 1
        return self.mode in ('A', 'B')

    def _ensure_lookahead_deadline(self):
        """Create one probe deadline while preserving the final preview."""
        if self._lookahead_deadline is not None:
            return self._lookahead_deadline
        now = time.perf_counter()
        policy_deadline = getattr(
            self, '_policy_deadline', now + self.policy_seconds,
        )
        reserve = max(3.0, float(self.preview_reserve_seconds))
        self._lookahead_deadline = min(
            float(policy_deadline) - reserve,
            now + float(self.lookahead_seconds),
        )
        return self._lookahead_deadline

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

    def _diversify(self, candidates, pool):
        groups = {}
        seen = set()
        for key, action in sorted(candidates,key=lambda pair:pair[0],reverse=True):
            pos=action['place_pos']
            cargo=pool[action['item_idx']]
            dims=h.orientation_dims(cargo,action['orientation'])
            physical=(tuple(dims),tuple((name,cargo.get(name)) for name in
                       ('mass','is_soft','lateralFriction','rollingFriction','spinningFriction',
                        'restitution','angularDamping','contactStiffness','contactDamping','linearDamping')))
            exact=(action['container_idx'],physical,tuple(float(v) for v in pos))
            if exact in seen:
                continue
            seen.add(exact)
            basin=(action['container_idx'],round(float(pos[2]-dims[2]*.5)/.15),
                   round(float(pos[0])/.3),round(float(pos[1])/.3))
            groups.setdefault(basin,[]).append((key,action))
        basins=[list(key) for key in groups]
        result=[]
        while groups:
            for basin in list(groups):
                result.append(groups[basin].pop(0))
                if not groups[basin]:
                    del groups[basin]
        return result,basins

    @staticmethod
    def _item_type_key(item):
        """Physical identity for a visible cargo type."""
        keys = ('length', 'width', 'height', 'mass', 'is_prioritized', 'is_soft',
                'lateralFriction', 'rollingFriction', 'spinningFriction',
                'restitution', 'angularDamping', 'contactStiffness',
                'contactDamping', 'linearDamping')
        return tuple((key, item.get(key)) for key in keys)

    @classmethod
    def _future_types(cls, pool, selected_idx):
        """Deduplicate the remaining visible pool without losing its order."""
        result = []
        seen = set()
        for index, item in enumerate(pool):
            if index == selected_idx:
                continue
            key = cls._item_type_key(item)
            if key in seen:
                continue
            seen.add(key)
            result.append(item)
        return result

    @staticmethod
    def _virtual_add(container, item, action):
        """Add an action at its proposed pose to a copied container state."""
        placed = dict(item)
        center = np.asarray(action['place_pos'], dtype=np.float64)
        center[0] += float(container.get('center', [0.])[0])
        placed['pos'] = list(center)
        placed['orn'] = list(h._orientation_quat(int(action['orientation'])))
        placed['belongs_to'] = int(container.get('index', 0))
        container.setdefault('packed_items', []).append(placed)

    def _future_fit(self, item, containers, deadline):
        """Check whether one visible type keeps a native-valid insertion.

        The point budget is global to this type.  Streams are visited in
        rounds so every fitting container/orientation gets a chance before a
        deeper stream consumes the budget.  A valid insertion is a proof even
        when the deadline interrupts the remaining coverage; a timeout before
        any proof is unknown and must not be scored as a miss.
        """
        validators = {}
        checks = 0
        valid_count = 0
        basins = set()
        point_budget = max(1, int(self.lookahead_points_per_type))

        def finish(value, *, unknown=False, complete=True):
            if unknown:
                status = 'unknown'
            elif value:
                status = 'complete_true' if complete else 'proven_partial'
            else:
                status = 'complete_false' if complete else 'unproven_partial'
            self._future_probe_detail = {
                'valid_insertions': valid_count,
                'valid_basins': len(basins),
                'unknown': unknown,
                'complete': complete,
                'status': status,
            }
            return value, checks

        def interrupted():
            if valid_count:
                return finish(True, complete=False)
            return finish(None, unknown=True, complete=False)

        try:
            streams = []
            for container_idx, container in enumerate(containers):
                packed = h._packed_boxes_for_container(container)
                for orientation, dims in h._unique_orientations(item):
                    if any(d > float(container[key]) + 1e-6
                           for d, key in zip(dims, ('length', 'width', 'height'))):
                        continue
                    # mixed_points interleaves several families and its
                    # max_points argument only limits the historical family.
                    # islice supplies the explicit hard cap for this stream;
                    # the outer counter supplies the global per-type cap.
                    streams.append({
                        'container_idx': container_idx,
                        'container': container,
                        'orientation': int(orientation),
                        'dims': dims,
                        'packed': packed,
                        'shelves': h._shelf_boxes(container),
                        'points': iter(islice(mixed_points(
                            container, dims, packed, max_points=point_budget,
                        ), point_budget)),
                    })

            # Round-robin streams preserve orientation/container coverage while
            # keeping the total number of generated checks bounded.
            while streams and checks < point_budget:
                next_streams = []
                for stream in streams:
                    if checks >= point_budget:
                        break
                    if time.perf_counter() >= deadline:
                        return interrupted()
                    try:
                        center = next(stream['points'])
                    except StopIteration:
                        continue
                    next_streams.append(stream)
                    checks += 1
                    container_idx = stream['container_idx']
                    container = stream['container']
                    orientation = stream['orientation']
                    dims = stream['dims']
                    packed = stream['packed']
                    shelves = stream['shelves']
                    ok, _ratio, _support_z = self._prefilter(
                        item, container, dims, center, packed, shelves,
                    )
                    if not ok:
                        continue
                    action = {
                        'item_idx': 0,
                        'container_idx': container_idx,
                        'orientation': orientation,
                        'place_pos': np.asarray(center, dtype=np.float32),
                    }
                    if container_idx not in validators:
                        validators[container_idx] = NativeValidator(container)
                    result = validators[container_idx].check(
                        item, action, deadline=deadline,
                    )
                    if result.get('deadline_exceeded'):
                        return interrupted()
                    if all(result[key] for key in
                           ('included', 'target_clear', 'transport')):
                        valid_count += 1
                        basins.add((container_idx,
                                    round(float(center[2] - dims[2] * .5) / .15),
                                    round(float(center[0]) / .3),
                                    round(float(center[1]) / .3)))
                        if valid_count >= int(self.lookahead_valid_limit):
                            return finish(True, complete=False)
                streams = next_streams
            if streams:
                # The explicit point cap stopped coverage before all streams
                # were exhausted.  No proof means unknown, never a completed
                # no-fit result; a proof was already handled above.
                return interrupted()
            return finish(valid_count > 0)
        finally:
            for validator in validators.values():
                validator.close()

    def _lookahead_rank(self, candidates, observation):
        """Re-score bounded top candidates by future visible ingress."""
        if not candidates:
            return candidates
        pool = list(observation.get('pool_list', []))
        if not self._lookahead_allowed(pool):
            return candidates
        # The first call creates the window.  Subsequent ranking passes in the
        # same policy reuse it instead of silently spending another slice.
        probe_deadline = self._ensure_lookahead_deadline()
        ranked = sorted(candidates, key=lambda pair: pair[0], reverse=True)
        probe = ranked[:int(self.lookahead_candidate_limit)]
        scores = []
        stats = self.last_diagnostics.setdefault('lookahead', dict(
            candidates_considered=0, candidates_scored=0,
            current_native_rejects=0, future_types=0, future_checks=0,
            unknown=0, partial_proofs=0, candidate_scores=[], score_range=None,
        ))
        for key, action in probe:
            exact = (
                int(action['item_idx']), int(action['container_idx']),
                int(action['orientation']),
                tuple(float(value) for value in action['place_pos']),
            )
            if exact in getattr(self, '_lookahead_cache', {}):
                scores.append(self._lookahead_cache[exact])
                continue
            stats['candidates_considered'] += 1
            if time.perf_counter() >= probe_deadline:
                stats['unknown'] += 1
                scores.append((key, action))
                continue
            container_idx = int(action['container_idx'])
            if container_idx not in self._native:
                self._native[container_idx] = NativeValidator(
                    observation['container_list'][container_idx]
                )
            current = self._native[container_idx].check(
                pool[int(action['item_idx'])], action, deadline=probe_deadline,
            )
            if current.get('deadline_exceeded'):
                stats['unknown'] += 1
                scores.append((key, action))
                continue
            if not all(current[name] for name in
                       ('included', 'target_clear', 'transport')):
                stats['current_native_rejects'] += 1
                self._lookahead_cache[exact] = (key, action)
                scores.append((key, action))
                continue
            virtual_containers = copy.deepcopy(observation['container_list'])
            self._virtual_add(
                virtual_containers[container_idx],
                pool[int(action['item_idx'])], action,
            )
            future_items = self._future_types(pool, int(action['item_idx']))
            future_items = future_items[:int(self.lookahead_type_limit)]
            stats['future_types'] = max(stats['future_types'], len(future_items))
            survivors = 0
            future_valid_slots = 0
            future_basins = 0
            unknown = False
            for future_item in future_items:
                if time.perf_counter() >= probe_deadline:
                    unknown = True
                    break
                fit, checks = self._future_fit(
                    future_item, virtual_containers, probe_deadline,
                )
                stats['future_checks'] += checks
                if fit is None:
                    unknown = True
                    break
                survivors += int(fit)
                detail = getattr(self, '_future_probe_detail', {})
                future_valid_slots += int(detail.get('valid_insertions', 0))
                future_basins += int(detail.get('valid_basins', 0))
                if not detail.get('complete', True):
                    stats['partial_proofs'] = stats.get('partial_proofs', 0) + 1
            if unknown:
                stats['unknown'] += 1
                new_key = key
                score_survivors = None
                score_missing = None
                score_valid_slots = None
                score_valid_basins = None
                score_status = 'unknown'
            else:
                missing = len(future_items) - survivors
                value = float(key[0])
                value += float(self.future_fit_weight) * survivors
                value -= float(self.future_loss_penalty) * missing
                if future_items and missing == 0:
                    value += float(self.future_all_fit_bonus)
                value += float(self.future_slot_weight) * min(future_valid_slots, 8)
                value += float(self.future_basin_weight) * min(future_basins, 8)
                new_key = (value,) + tuple(key[1:])
                stats['candidates_scored'] += 1
                score_survivors = survivors
                score_missing = missing
                score_valid_slots = future_valid_slots
                score_valid_basins = future_basins
                score_status = 'proven' if future_items else 'no_future_types'
            score_record = {
                'item_idx': int(action['item_idx']),
                'container_idx': int(action['container_idx']),
                'base_score': float(key[0]),
                'score': float(new_key[0]),
                'future_types': len(future_items),
                'survivors': score_survivors,
                'missing': score_missing,
                'valid_insertions': score_valid_slots,
                'valid_basins': score_valid_basins,
                'status': score_status,
                'unknown': unknown,
            }
            if len(stats['candidate_scores']) < 32:
                stats['candidate_scores'].append(score_record)
            self._lookahead_cache[exact] = (new_key, action)
            scores.append((new_key, action))
        # Keep unprobed candidates available for the progressive wide stage.
        scores.extend(pair for pair in ranked[int(self.lookahead_candidate_limit):])
        scores.sort(key=lambda pair: pair[0], reverse=True)
        probed_scores = [float(pair[0][0]) for pair in scores[:int(self.lookahead_candidate_limit)]]
        if probed_scores:
            stats['score_range'] = [min(probed_scores), max(probed_scores)]
        return scores

    def policy(self, observation):
        started = time.perf_counter()
        self._policy_deadline = started + self.policy_seconds
        for validator in self._native.values():
            validator.close()
        self._native = {}
        self._failed_supports = set()
        self._lookahead_cache = {}
        self._lookahead_deadline = None
        self.last_diagnostics = dict(candidate_checks=0, combinations_visited=0,
                                     authorizations=0, rejections={}, previews=[], elapsed=0.)
        self.last_diagnostics['mode'] = self.mode
        pool = list(observation.get('pool_list', []))
        containers = list(observation.get('container_list', []))
        if not pool or not containers:
            raise NoValidAction('No visible cargo or containers')
        geometry = [(h._packed_boxes_for_container(c), h._shelf_boxes(c)) for c in containers]
        self._current_geometry = geometry

        # Optional controlled successor: preserve the historical trajectory
        # while its proposed actions continue to pass current-state checks.
        if self._historical_prefix_enabled and self._historical_prefix_active:
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
        narrow_shortlist = []
        checked = 0
        search_duration = self.preview_search_seconds if self.use_settling_preview else self.search_seconds
        search_deadline = min(
            started + self.policy_seconds - max(3.0, self.preview_reserve_seconds),
            time.perf_counter() + search_duration,
        )
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
            # Preserve the original native policy's score-trimmed stream as
            # the first stage, independent of enabling settling preview.
            narrow_shortlist.append((key,action))
            if len(narrow_shortlist) > self.shortlist_limit*2:
                narrow_shortlist.sort(key=lambda pair:pair[0],reverse=True)
                del narrow_shortlist[self.shortlist_limit:]
        self.last_diagnostics['candidate_checks'] = checked
        if self._lookahead_allowed(pool):
            self._ensure_lookahead_deadline()
            shortlist = self._lookahead_rank(shortlist, observation)
            narrow_shortlist = self._lookahead_rank(narrow_shortlist, observation)
        narrow,narrow_basins=self._diversify(narrow_shortlist,pool)
        wide,wide_basins=self._diversify(shortlist,pool)
        self.last_diagnostics['narrow_basins']=narrow_basins
        self.last_diagnostics['candidate_basins']=wide_basins
        remaining=deque([('narrow',action) for _,action in narrow[:self.shortlist_limit]]+
                        [('wide',action) for _,action in wide[:self.shortlist_limit]])
        attempted=set()
        deferred = deque()
        revisit_failed_supports = False
        self.last_diagnostics['deferred_support_candidates'] = 0
        while remaining or deferred:
            if not remaining:
                remaining, deferred = deferred, deque()
                revisit_failed_supports = True
            stage, action = remaining.popleft()
            if (time.perf_counter() >= started + self.policy_seconds or
                    self.last_diagnostics['authorizations'] >= self.max_authorizations):
                break
            exact=(action['item_idx'],action['container_idx'],action['orientation'],
                   tuple(float(v) for v in action['place_pos']))
            if exact in attempted:
                continue
            if (self.use_settling_preview and not revisit_failed_supports and
                    self._support_items(action, observation) & self._failed_supports):
                deferred.append((stage,action))
                self.last_diagnostics['deferred_support_candidates'] += 1
                continue
            attempted.add(exact)
            accepted = self._authorize(action, observation, 'fair_search')
            if accepted is not None:
                self.last_diagnostics['selected_stage']=stage
                self.last_diagnostics['elapsed'] = time.perf_counter() - started
                return accepted
        self.last_diagnostics['elapsed'] = time.perf_counter() - started
        raise NoValidAction(f'No authorized candidate: {self.last_diagnostics}')
