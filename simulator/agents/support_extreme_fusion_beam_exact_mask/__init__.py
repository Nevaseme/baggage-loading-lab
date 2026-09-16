"""Strict-root packing agent package.

The package intentionally exposes only the public agent entry point and the
small immutable boundary types.  Search/planner modules are added in later
implementation phases; this first boundary is usable without importing the
historical ``highscore`` package.
"""

from .agent import Agent, CandidateZeroError, NotReadyError, PlanningError
from .model import PlacementProposal, ValidatedRoot

__all__ = [
    "Agent",
    "CandidateZeroError",
    "NotReadyError",
    "PlanningError",
    "PlacementProposal",
    "ValidatedRoot",
]
