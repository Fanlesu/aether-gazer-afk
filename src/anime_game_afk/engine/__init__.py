"""Generic, game-agnostic automation engine.

Houses the reusable workflow engine (plan runner) plus the device
abstraction and game launcher. Concrete game behaviour — task classes,
red-dot checks, content packs — lives under ``games.<id>``.

Public API: re-export the workflow engine's data types so callers can
``from anime_game_afk.engine import WorkflowEngine, PlanStep, ...``
without reaching into the game-specific package.
"""
from anime_game_afk.engine.workflow_engine import (
    PlanGroup,
    PlanItem,
    PlanStep,
    TaskMeta,
    TaskParams,
    WorkflowEngine,
)

__all__ = [
    "WorkflowEngine",
    "PlanStep",
    "PlanGroup",
    "PlanItem",
    "TaskParams",
    "TaskMeta",
]
