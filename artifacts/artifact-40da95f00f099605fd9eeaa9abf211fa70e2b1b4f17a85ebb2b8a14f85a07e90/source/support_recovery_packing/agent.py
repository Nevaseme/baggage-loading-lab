"""Submission interface for current-state validated support recovery."""
from .planner import Agent as Planner, NoValidAction
from .terminal import terminal_rejection


class Agent:
    def __init__(self, module_path):
        self._planner=Planner(module_path)
        self.last_diagnostics={}

    def get_init_states(self, init_states):
        result=self._planner.get_init_states(init_states)
        self._planner.prefer_historical_action=True
        self._planner.max_authorizations=384
        mode_b=not bool(init_states['optimize']) and int(init_states['lookahead_k'])>1
        # B's historical search can use several seconds before a safe preview.
        # The measured 5.2-second cap interrupted a known-safe trial at step225.
        self._planner.policy_seconds=7.2 if mode_b else 5.2
        self._planner._historical_prefix_active=True
        self.last_diagnostics={}
        return result

    def optimize(self, item_list):
        return self._planner.optimize(item_list)

    def policy(self, observation):
        try:
            action=self._planner.policy(observation)
        except NoValidAction:
            action,proof=terminal_rejection(observation)
            self.last_diagnostics=dict(self._planner.last_diagnostics,
                                       terminal_rejection=proof)
            return action
        self.last_diagnostics=self._planner.last_diagnostics
        return action
