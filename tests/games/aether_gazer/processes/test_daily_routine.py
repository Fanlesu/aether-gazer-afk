"""Tests for processes.daily_routine — DailyRoutine.

DailyRoutine runs 13 tasks (startup + 12 daily). All must be mocked.

Task list is read from ``_DAILY_TASKS`` at runtime rather than being
hardcoded here, so adding a task to the routine does not silently break
these tests (it previously did — the list drifted to 13 while the test
still asserted 12).
"""
import asyncio
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, patch

import numpy as np

from anime_game_afk.games.aether_gazer.processes.base import ProcessContext
from anime_game_afk.games.aether_gazer.processes.daily_routine import (
    DailyRoutine,
    _DAILY_TASKS,
)
from anime_game_afk.games.aether_gazer.tasks.base import TaskResult


@dataclass
class MockDevice:
    key_log: list = field(default_factory=list)
    click_log: list = field(default_factory=list)

    def screenshot(self) -> np.ndarray:
        return np.zeros((900, 1600, 3), dtype=np.uint8)
    def click(self, x: int, y: int) -> None:
        self.click_log.append((x, y))
    def press_key(self, vk_code: int) -> None:
        self.key_log.append(vk_code)
    def hold_key(self, vk_code: int, duration_s: float) -> None:
        pass


def _run(coro):
    return asyncio.run(coro)


def _task_success(**data):
    return AsyncMock(return_value=TaskResult(status="success", data=data))


def _task_failed():
    return AsyncMock(return_value=TaskResult(status="failed", message="err"))


_MOD = "anime_game_afk.games.aether_gazer.processes.daily_routine"

# Derived from the real routine so the two can't drift apart.
_TASK_CLASS_NAMES = [entry[1].__name__ for entry in _DAILY_TASKS]
_TASK_COUNT = len(_DAILY_TASKS)


def _patch_all(execute_mock=None, can_run_val=True):
    """Patch ReturnToHub + every task class in the routine."""
    patches = [
        patch(f"{_MOD}.ReturnToHub.execute", _task_success()),
    ]
    for cls_name in _TASK_CLASS_NAMES:
        ex_mock = execute_mock or _task_success()
        patches.append(patch(f"{_MOD}.{cls_name}.execute", ex_mock))
        patches.append(
            patch(f"{_MOD}.{cls_name}.can_run", AsyncMock(return_value=can_run_val))
        )
    return patches


def _start_patches(patches):
    for p in patches:
        p.start()


def _stop_patches(patches):
    for p in patches:
        p.stop()


# --- Tests ---

def test_daily_routine_name_and_description():
    proc = DailyRoutine()
    assert proc.name == "每日一条龙"
    assert len(proc.description) > 0


def test_daily_routine_task_count():
    """Routine exposes a non-trivial task list with unique ids."""
    assert _TASK_COUNT >= 12
    ids = [entry[0] for entry in _DAILY_TASKS]
    assert len(ids) == len(set(ids)), "duplicate task ids in _DAILY_TASKS"


def test_daily_routine_task_defs_match_task_list():
    """task_defs() (used by the UI to build the task list) stays in sync."""
    defs = DailyRoutine.task_defs()
    assert len(defs) == _TASK_COUNT
    assert [d["id"] for d in defs] == [entry[0] for entry in _DAILY_TASKS]


def test_daily_routine_completes_all_tasks():
    """Happy path: every task succeeds (game freshly launched)."""
    device = MockDevice()
    ctx = ProcessContext(device=device, config={"game_was_launched": True})

    patches = _patch_all()
    _start_patches(patches)
    try:
        result = _run(DailyRoutine().execute(ctx))
    finally:
        _stop_patches(patches)

    assert result.status == "success"
    assert len(result.data["completed"]) == _TASK_COUNT
    assert len(result.data["failed"]) == 0


def test_daily_routine_reports_failure_when_tasks_fail():
    """All tasks failing must surface as status='failed', not 'success'.

    Regression guard: the routine used to hardcode status='success', which
    made the pipeline log "1/1 succeeded" while every task had failed.
    """
    device = MockDevice()
    ctx = ProcessContext(device=device, config={"game_was_launched": True})

    patches = [
        patch(f"{_MOD}.ReturnToHub.execute", _task_success()),
    ]
    for cls_name in _TASK_CLASS_NAMES:
        patches.append(patch(f"{_MOD}.{cls_name}.execute", _task_failed()))
        patches.append(
            patch(f"{_MOD}.{cls_name}.can_run", AsyncMock(return_value=True))
        )

    _start_patches(patches)
    try:
        result = _run(DailyRoutine().execute(ctx))
    finally:
        _stop_patches(patches)

    assert result.status == "failed"
    assert result.data["completed"] == []
    assert len(result.data["failed"]) == _TASK_COUNT
    # Message must name the failures so the UI/log is actionable.
    assert "failed" in result.message


def test_daily_routine_skips_if_cannot_run():
    """Tasks with can_run=False are skipped and count as neither done nor failed."""
    device = MockDevice()
    ctx = ProcessContext(device=device)

    patches = _patch_all(can_run_val=False)
    _start_patches(patches)
    try:
        result = _run(DailyRoutine().execute(ctx))
    finally:
        _stop_patches(patches)

    assert result.status == "success"
    assert result.data["completed"] == []
    assert result.data["failed"] == []
