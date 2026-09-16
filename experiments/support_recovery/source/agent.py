"""Historical-prefix recovery with a bounded second support search."""
import time

from .base_agent import Agent as BaseAgent, NoValidAction
from . import historical as h


class Agent(BaseAgent):
    prefer_historical_action = True
    max_authorizations = 384
    total_policy_seconds = 7.2

    def __init__(self, module_path):
        super().__init__(module_path)
        self._relaxed_support = False

    def _prefilter(self, item, container, dims, center, packed, shelves):
        if not self._relaxed_support:
            return BaseAgent._prefilter(item, container, dims, center, packed, shelves)
        if not h._inside_container(container, center, dims, -.007):
            return False, 0., h._floor_z(container)
        if not h._target_clear(center, dims, packed, shelves):
            return False, 0., h._floor_z(container)
        ratio, support_z = h._support_ratio(container, center, dims, packed)
        # This is a proposal heuristic. Native geometry and a complete settling
        # preview still decide every returned action, including bridges.
        return ratio >= .5, ratio, support_z

    def policy(self, observation):
        started = time.perf_counter()
        try:
            action = super().policy(observation)
            self.last_diagnostics['recovery_stage'] = 'strict'
            self.last_diagnostics['total_elapsed'] = time.perf_counter()-started
            return action
        except NoValidAction:
            strict = self.last_diagnostics
            remaining = self.total_policy_seconds-(time.perf_counter()-started)-.03
            if remaining < 1.5:
                raise
        names = ('policy_seconds','shortlist_limit','max_authorizations','max_candidate_checks')
        saved = {name: getattr(self,name) for name in names}
        self.policy_seconds = remaining
        self.shortlist_limit = 512
        self.max_authorizations = 512
        self.max_candidate_checks = 16000
        self._relaxed_support = True
        try:
            return super().policy(observation)
        finally:
            for name, value in saved.items(): setattr(self,name,value)
            self._relaxed_support = False
            self.last_diagnostics['strict_search'] = strict
            self.last_diagnostics['recovery_stage'] = 'relaxed_support'
            self.last_diagnostics['total_elapsed'] = time.perf_counter()-started
