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


# --- Plan (L1 orchestration) tests --------------------------------------
# The plan is supplied via ctx.config["plan"] and must drive ordering,
# enable/disable, per-task params, and stay backward compatible.

def _completed_ids(result):
    """Extract task ids from the completed summary list (strips '(n)')."""
    return [c.split("(")[0] for c in result.data["completed"]]


def test_plan_order_is_respected():
    """An explicit plan runs tasks in plan order, not registry order."""
    device = MockDevice()
    plan = [{"id": tid} for tid in reversed([e[0] for e in _DAILY_TASKS])]
    ctx = ProcessContext(
        device=device,
        config={"game_was_launched": True, "plan": plan},
    )
    patches = _patch_all()
    _start_patches(patches)
    try:
        result = _run(DailyRoutine().execute(ctx))
    finally:
        _stop_patches(patches)
    assert result.status == "success"
    assert _completed_ids(result) == [e["id"] for e in plan]


def test_plan_disabled_task_skipped():
    """A (non-safe) task disabled in the plan is skipped, not counted done."""
    device = MockDevice()
    disabled_id = "intel_shards"  # non-safe task, so it can be disabled
    plan = [
        {"id": tid, "enabled": tid != disabled_id}
        for tid in (e[0] for e in _DAILY_TASKS)
    ]
    ctx = ProcessContext(
        device=device,
        config={"game_was_launched": True, "plan": plan},
    )
    patches = _patch_all()
    _start_patches(patches)
    try:
        result = _run(DailyRoutine().execute(ctx))
    finally:
        _stop_patches(patches)
    ids_done = _completed_ids(result)
    assert disabled_id not in ids_done
    assert len(ids_done) == _TASK_COUNT - 1


def test_backward_compat_enabled_tasks_set():
    """Legacy enabled_tasks set still works (order = registry default)."""
    device = MockDevice()
    enabled = {"mail", "tactics"}
    ctx = ProcessContext(
        device=device,
        config={"game_was_launched": True, "enabled_tasks": enabled},
    )
    patches = _patch_all()
    _start_patches(patches)
    try:
        result = _run(DailyRoutine().execute(ctx))
    finally:
        _stop_patches(patches)
    assert set(_completed_ids(result)) == enabled
    assert len(_completed_ids(result)) == 2


def test_safe_task_forced_enabled():
    """A safe task cannot be disabled via plan — it is forced on."""
    device = MockDevice()
    plan = [
        {"id": tid, "enabled": tid != "mail"}
        for tid in (e[0] for e in _DAILY_TASKS)
    ]
    ctx = ProcessContext(
        device=device,
        config={"game_was_launched": True, "plan": plan},
    )
    patches = _patch_all()
    _start_patches(patches)
    try:
        result = _run(DailyRoutine().execute(ctx))
    finally:
        _stop_patches(patches)
    assert "mail" in _completed_ids(result)  # safe -> forced enabled


def test_plan_unknown_task_id_dropped():
    """Unknown task ids in a plan are dropped, not executed."""
    device = MockDevice()
    plan = [{"id": "mail"}, {"id": "not_a_real_task"}, {"id": "tactics"}]
    ctx = ProcessContext(
        device=device,
        config={"game_was_launched": True, "plan": plan},
    )
    patches = _patch_all()
    _start_patches(patches)
    try:
        result = _run(DailyRoutine().execute(ctx))
    finally:
        _stop_patches(patches)
    assert result.status == "success"
    assert _completed_ids(result) == ["mail", "tactics"]


def test_plan_retry_makes_task_succeed():
    """retry: a task failing once then succeeding runs twice and succeeds."""
    device = MockDevice()
    plan = [{"id": "mail", "params": {"retry": 1}}]
    ctx = ProcessContext(
        device=device,
        config={"game_was_launched": True, "plan": plan},
    )
    mail_execute = AsyncMock(
        side_effect=[
            TaskResult(status="failed", message="boom"),
            TaskResult(status="success"),
        ]
    )
    patches = [
        patch(f"{_MOD}.ReturnToHub.execute", _task_success()),
        patch(f"{_MOD}.CollectAllMail.execute", mail_execute),
        patch(f"{_MOD}.CollectAllMail.can_run", AsyncMock(return_value=True)),
    ]
    _start_patches(patches)
    try:
        result = _run(DailyRoutine().execute(ctx))
    finally:
        _stop_patches(patches)
    assert result.status == "success"
    assert mail_execute.call_count == 2


def test_plan_timeout_fails_task():
    """timeout: a task exceeding its timeout is reported failed."""
    device = MockDevice()

    async def slow_execute(_ctx):
        await asyncio.sleep(5)
        return TaskResult(status="success")

    plan = [{"id": "mail", "params": {"timeout": 0.2}}]
    ctx = ProcessContext(
        device=device,
        config={"game_was_launched": True, "plan": plan},
    )
    patches = [
        patch(f"{_MOD}.ReturnToHub.execute", _task_success()),
        patch(f"{_MOD}.CollectAllMail.execute", slow_execute),
        patch(f"{_MOD}.CollectAllMail.can_run", AsyncMock(return_value=True)),
    ]
    _start_patches(patches)
    try:
        result = _run(DailyRoutine().execute(ctx))
    finally:
        _stop_patches(patches)
    assert result.status == "failed"
    assert "mail" in result.data["failed"]
