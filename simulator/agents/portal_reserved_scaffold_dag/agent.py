"""Competition-facing Agent: historical proposal seed behind one shield."""

from __future__ import annotations

from typing import Any

from .authorizer import (
    AuthorizerProfile,
    AuthorizationError,
    authorize_current,
    format_authorized_action,
    proposal_from_action,
)
from .historical_seed import HistoricalSeed, HistoricalSeedError


class Agent:
    """Preserve the public simulator Agent interface and fail closed online."""

    def __init__(self, module_path: str):
        self.module_path = str(module_path)
        self.profile = AuthorizerProfile()
        self.seed = HistoricalSeed(self.module_path)
        self._last_result = None

    def get_init_states(self, init_states: dict[str, Any]) -> bool:
        if not isinstance(init_states, dict):
            raise TypeError("init_states must be a dictionary")
        return bool(self.seed.get_init_states(init_states))

    def optimize(self, item_list: list[dict[str, Any]]) -> list[int]:
        try:
            return list(self.seed.optimize(item_list))
        except Exception as error:
            raise HistoricalSeedError(
                f"historical optimization failed closed: {type(error).__name__}: {error}"
            ) from error

    def policy(self, observation: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(observation, dict):
            raise HistoricalSeedError("observation must be a dictionary")
        try:
            candidate = self.seed.policy(observation)
        except Exception as error:
            raise HistoricalSeedError(
                f"historical seed could not propose: {type(error).__name__}: {error}"
            ) from error
        try:
            proposal = proposal_from_action(
                candidate,
                observation,
                route="historical",
                source_key="historical_seed",
            )
            result = authorize_current(proposal, observation, profile=self.profile)
            self._last_result = result
            if not result.accepted:
                raise HistoricalSeedError(
                    "historical proposal rejected before env.step: "
                    + ",".join(result.reject_reasons)
                )
            return format_authorized_action(result, observation, profile=self.profile)
        except HistoricalSeedError:
            raise
        except Exception as error:
            raise HistoricalSeedError(
                f"historical authorization failed closed: {type(error).__name__}: {error}"
            ) from error


__all__ = ["Agent", "HistoricalSeedError", "AuthorizationError"]
