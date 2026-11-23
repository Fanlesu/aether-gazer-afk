"""Tests for the generic WorkflowEngine (engine.workflow_engine).

These are pure-logic: no device, no real tasks. A tiny fake task registry
stands in for the real one so we can assert ordering, enable/disable,
safe-forcing, unknown-id dropping, retry/timeout, inter-step and
should-skip hooks in isolation.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import numpy as np

from anime_game_afk.engine.workflow_engine import (
    TaskMeta,
    WorkflowEngine,
)
from anime_game_afk.games.aether_gazer.processes.base import ProcessContext
from anime_game_afk.games.aether_gazer.tasks.base import TaskResult


class MockDevice:
    def screenshot(self) -> np.ndarray:
        return np.zeros((900, 1600, 3), dtype=np.uint8)
    def click(self, x: int, y: int) -> None: ...
    def press_key(self, vk_code: int) -> None: ...
    def hold_key(self, vk_code: int, duration_s: float) -> None: ...


def _ctx(**config) -> ProcessContext:
    return ProcessContext(device=MockDevice(), config=config)


def _make_task(name: str, *, can_run: bool = True,
               result: TaskResult | None = None) -> type:
    """Build a fake Task class with mocked can_run/execute."""
    return type(
        f"_T_{name}",
        (),
        {
            "name": name,
            "can_run": AsyncMock(return_value=can_run),
            "execute": AsyncMock(
                return_value=result or TaskResult(status="success")
            ),
        },
    )


def _registry() -> dict[str, TaskMeta]:
    return {
        "startup": TaskMeta(_make_task("startup"), "启动", True),
        "mail": TaskMeta(_make_task("mail"), "邮件", True),
        "intel": TaskMeta(_make_task("intel"), "情报", False),
        "fight": TaskMeta(_make_task("fight"), "战斗", False),
    }


# --- build_plan --------------------------------------------------------


def test_build_plan_explicit_order_and_unknown_drop():
    reg = _registry()
    engine = WorkflowEngine(reg)
    plan = engine.build_plan({"plan": [
        {"id": "fight"},
        {"id": "mail"},
        {"id": "ghost"},  # unknown -> dropped
    ]})
    assert [s.task_id for s in plan] == ["fight", "mail"]


def test_build_plan_respects_disabled_safe_task():
    """Since v0.5.x, safe tasks are fully user-controllable: an explicit
    plan may disable them and build_plan must honor that (no forcing)."""
    reg = _registry()
    engine = WorkflowEngine(reg)
    plan = engine.build_plan({"plan": [
        {"id": "mail", "enabled": False},   # safe -> disabled stays disabled
        {"id": "intel", "enabled": False},  # not safe -> stays off
    ]})
    by_id = {s.task_id: s for s in plan}
    assert by_id["mail"].enabled is False
    assert by_id["intel"].enabled is False


def test_build_plan_legacy_enabled_tasks_strict():
    reg = _registry()
    engine = WorkflowEngine(reg)
    plan = engine.build_plan({"enabled_tasks": {"mail", "fight"}})
    by_id = {s.task_id: s for s in plan}
    assert by_id["mail"].enabled is True
    assert by_id["fight"].enabled is True
    # legacy path does NOT force safe tasks that aren't in the whitelist
    assert by_id["startup"].enabled is False


def test_build_plan_default_all_enabled():
    reg = _registry()
    engine = WorkflowEngine(reg)
    plan = engine.build_plan({})
    assert [s.task_id for s in plan] == list(reg.keys())
    assert all(s.enabled for s in plan)


def test_build_plan_default_honors_meta_default_enabled():
    """The no-config default path honors each TaskMeta.default_enabled
    (e.g. 联防协议 ships unchecked); explicit plans still override."""
    reg = {
        "mail": TaskMeta(_make_task("mail"), "邮件", True),
        "jd": TaskMeta(_make_task("jd"), "联防", False, default_enabled=False),
    }
    engine = WorkflowEngine(reg)
    plan = engine.build_plan({})
    by_id = {s.task_id: s for s in plan}
    assert by_id["mail"].enabled is True
    assert by_id["jd"].enabled is False

    # User choice wins on the explicit-plan path
    plan = engine.build_plan({"plan": [{"id": "jd", "enabled": True}]})
    assert plan[0].enabled is True


# --- run ---------------------------------------------------------------


def test_run_completes_all_when_can_run_true():
    reg = _registry()
    engine = WorkflowEngine(reg)
    result = asyncio.run(engine.run(_ctx(game_was_launched=True)))
    assert result.status == "success"
    assert set(result.data["completed"]) == set(reg.keys())


def test_run_reports_failure():
    reg = _registry()
    # make every task fail
    for meta in reg.values():
        meta.cls.can_run = AsyncMock(return_value=True)
        meta.cls.execute = AsyncMock(
            return_value=TaskResult(status="failed", message="boom")
        )
    engine = WorkflowEngine(reg)
    result = asyncio.run(engine.run(_ctx(game_was_launched=True)))
    assert result.status == "failed"
    assert len(result.data["failed"]) == len(reg)


def test_run_skips_when_can_run_false():
    reg = _registry()
    for meta in reg.values():
        meta.cls.can_run = AsyncMock(return_value=False)
    engine = WorkflowEngine(reg)
    result = asyncio.run(engine.run(_ctx(game_was_launched=True)))
    assert result.status == "success"
    assert result.data["completed"] == []
    assert result.data["failed"] == []


def test_run_inter_step_called_between_tasks():
    reg = _registry()
    engine = WorkflowEngine(reg)
    inter = AsyncMock()
    engine._inter_step = inter
    result = asyncio.run(engine.run(_ctx(game_was_launched=True)))
    assert result.status == "success"
    # inter_step runs once after each of the 4 tasks
    assert inter.call_count == len(reg)


def test_run_should_skip_hook():
    reg = _registry()
    engine = WorkflowEngine(reg)
    engine._should_skip = lambda step, ctx: (
        "skip-reason" if step.task_id == "fight" else None
    )
    inter = AsyncMock()
    engine._inter_step = inter
    result = asyncio.run(engine.run(_ctx(game_was_launched=True)))
    assert result.status == "success"
    ids = [c.split("(")[0] for c in result.data["completed"]]
    assert "fight" not in ids
    # skipped step still triggers inter_step (return-to-hub safety)
    assert inter.call_count == len(reg)


def test_run_retry_makes_task_succeed():
    reg = _registry()
    intel = reg["intel"].cls
    intel.can_run = AsyncMock(return_value=True)
    intel.execute = AsyncMock(side_effect=[
        TaskResult(status="failed", message="boom"),
        TaskResult(status="success"),
    ])
    small = WorkflowEngine({"intel": reg["intel"]})
    result = asyncio.run(small.run(_ctx(plan=[{"id": "intel",
                                                "params": {"retry": 1}}])))
    assert result.status == "success"
    assert intel.execute.call_count == 2


def test_run_timeout_fails_task():
    reg = _registry()

    async def slow(_ctx):
        await asyncio.sleep(1)
        return TaskResult(status="success")

    fight = reg["fight"].cls
    fight.can_run = AsyncMock(return_value=True)
    fight.execute = slow
    small = WorkflowEngine({"fight": reg["fight"]})
    result = asyncio.run(small.run(_ctx(plan=[{"id": "fight",
                                                "params": {"timeout": 0.1}}])))
    assert result.status == "failed"
    assert "fight" in result.data["failed"]


# --- L2: conditions + control flow -------------------------------------


def test_build_plan_parses_groups():
    reg = _registry()
    engine = WorkflowEngine(reg)
    plan = engine.build_plan({"plan": [
        {"id": "mail"},
        {"type": "group", "name": "g", "repeat": 2,
         "steps": [{"id": "intel"}, {"id": "fight"}]},
    ]})
    from anime_game_afk.engine.workflow_engine import PlanGroup
    assert plan[0].task_id == "mail"
    assert isinstance(plan[1], PlanGroup)
    assert plan[1].repeat == 2
    assert [s.task_id for s in plan[1].steps] == ["intel", "fight"]


def test_run_condition_skip_when_resolver_false():
    reg = _registry()

    async def resolver(cond, ctx):
        # block any step whose condition carries gate == "block"
        return cond.get("gate") != "block"

    engine = WorkflowEngine(
        reg,
        resolve_condition=resolver,
    )
    plan = [
        {"id": "mail", "condition": {"gate": "block"}},
        {"id": "intel"},
    ]
    result = asyncio.run(engine.run(_ctx(plan=plan)))
    assert result.status == "success"
    completed = [c.split("(")[0] for c in result.data["completed"]]
    assert "mail" not in completed
    assert "intel" in completed


def test_run_condition_ignored_without_resolver():
    """Backward compat: no resolver wired -> conditions are no-ops."""
    reg = _registry()
    engine = WorkflowEngine(reg)
    plan = [{"id": "mail", "condition": {"gate": "block"}}]
    result = asyncio.run(engine.run(_ctx(plan=plan)))
    assert result.status == "success"
    assert "mail" in [c.split("(")[0] for c in result.data["completed"]]


def test_run_group_repeats_steps():
    reg = _registry()
    mail = reg["mail"].cls
    engine = WorkflowEngine(reg)
    plan = [{"type": "group", "name": "g", "repeat": 3,
             "steps": [{"id": "mail"}]}]
    result = asyncio.run(engine.run(_ctx(plan=plan)))
    assert result.status == "success"
    assert mail.execute.call_count == 3


def test_run_on_fail_abort_stops_run():
    reg = _registry()
    fight = reg["fight"].cls
    fight.can_run = AsyncMock(return_value=True)
    fight.execute = AsyncMock(
        return_value=TaskResult(status="failed", message="boom")
    )
    mail = reg["mail"].cls
    engine = WorkflowEngine(reg)
    plan = [
        {"id": "fight", "on_fail": "abort"},
        {"id": "mail"},
    ]
    result = asyncio.run(engine.run(_ctx(plan=plan)))
    assert result.status == "failed"
    assert result.data["aborted"] is True
    # mail must NOT run after abort
    assert mail.execute.call_count == 0


def test_run_on_fail_skip_continues_by_default():
    reg = _registry()
    fight = reg["fight"].cls
    fight.can_run = AsyncMock(return_value=True)
    fight.execute = AsyncMock(
        return_value=TaskResult(status="failed", message="boom")
    )
    mail = reg["mail"].cls
    engine = WorkflowEngine(reg)
    plan = [{"id": "fight"}, {"id": "mail"}]  # on_fail defaults to skip
    result = asyncio.run(engine.run(_ctx(plan=plan)))
    assert result.status == "failed"  # fight failed
    assert mail.execute.call_count == 1  # but mail still ran


def test_run_nested_group_and_abort_propagates():
    reg = _registry()
    intel = reg["intel"].cls
    intel.can_run = AsyncMock(return_value=True)
    intel.execute = AsyncMock(
        return_value=TaskResult(status="failed", message="boom")
    )
    mail = reg["mail"].cls
    engine = WorkflowEngine(reg)
    plan = [{
        "type": "group", "name": "outer", "repeat": 1,
        "steps": [
            {"type": "group", "name": "inner",
             "steps": [{"id": "intel", "on_fail": "abort"}]},
            {"id": "mail"},
        ],
    }]
    result = asyncio.run(engine.run(_ctx(plan=plan)))
    assert result.data["aborted"] is True
    assert mail.execute.call_count == 0


# --- L3: custom atomic-action steps ------------------------------------


def test_plan_step_from_dict_parses_actions():
    from anime_game_afk.engine.workflow_engine import PlanStep
    step = PlanStep.from_dict({
        "id": "custom_1",
        "actions": [{"type": "click", "x": 0.1, "y": 0.2}],
    })
    assert step.actions == [{"type": "click", "x": 0.1, "y": 0.2}]
    assert step.on_fail == "skip"


def test_build_plan_keeps_custom_step():
    """A custom step (actions set, unknown id) is kept, not dropped."""
    reg = _registry()
    engine = WorkflowEngine(reg)
    plan = engine.build_plan({"plan": [
        {"id": "custom_ghost", "actions": [{"type": "wait"}]},
        {"id": "mail"},
    ]})
    assert plan[0].task_id == "custom_ghost"
    assert plan[0].actions == [{"type": "wait"}]
    assert plan[1].task_id == "mail"


def test_run_custom_actions_runs_executor():
    reg = _registry()
    executor = AsyncMock(return_value=True)
    engine = WorkflowEngine(reg, action_executor=executor)
    plan = [{
        "id": "custom_1", "enabled": True,
        "actions": [{"type": "click", "x": 0.5, "y": 0.5},
                    {"type": "wait", "seconds": 1}],
    }]
    result = asyncio.run(engine.run(_ctx(plan=plan)))
    assert result.status == "success"
    assert executor.call_count == 2
    assert "custom_1" in result.data["completed"]


def test_run_custom_action_failure_abort():
    reg = _registry()
    executor = AsyncMock(side_effect=[True, False])  # 2nd action fails
    engine = WorkflowEngine(reg, action_executor=executor)
    plan = [
        {"id": "custom_1", "enabled": True, "on_fail": "abort",
         "actions": [{"type": "wait"}, {"type": "wait"}]},
        {"id": "mail"},
    ]
    result = asyncio.run(engine.run(_ctx(plan=plan)))
    assert result.data["aborted"] is True
    assert executor.call_count == 2  # 1st True, 2nd False broke the loop
    # mail must NOT run after an abort
    assert reg["mail"].cls.execute.call_count == 0


def test_run_custom_action_failure_skip():
    reg = _registry()
    executor = AsyncMock(side_effect=[True, False])
    engine = WorkflowEngine(reg, action_executor=executor)
    plan = [
        {"id": "custom_1", "enabled": True, "on_fail": "skip",
         "actions": [{"type": "wait"}, {"type": "wait"}]},
        {"id": "mail"},
    ]
    result = asyncio.run(engine.run(_ctx(plan=plan)))
    assert result.status == "failed"  # custom step failed
    assert executor.call_count == 2
    # mail still ran under the skip policy
    assert reg["mail"].cls.execute.call_count == 1


# --- params.extra (task-specific custom knobs) --------------------------


class _ExtraCaptureTask:
    """Fake task recording the ``extra`` dict attached by the engine."""

    name = "mail"
    captured: dict = {}
    can_run_called = False

    async def can_run(self, ctx) -> bool:
        _ExtraCaptureTask.can_run_called = True
        return True

    async def execute(self, ctx) -> TaskResult:
        _ExtraCaptureTask.captured = dict(getattr(self, "extra", {}) or {})
        return TaskResult(status="success")


def test_plan_step_from_dict_parses_extra_params():
    from anime_game_afk.engine.workflow_engine import PlanStep

    step = PlanStep.from_dict(
        {"id": "mail", "params": {"retry": 1, "extra": {"target_stamina": 450}}}
    )
    assert step.params.extra == {"target_stamina": 450}
    assert step.params.retry == 1
    # Missing extra → empty dict (backward compatible with old plans)
    assert PlanStep.from_dict({"id": "mail"}).params.extra == {}


def test_run_attaches_extra_params_to_task_instance():
    reg = {"mail": TaskMeta(_ExtraCaptureTask, "邮件", True)}
    engine = WorkflowEngine(reg)
    plan = [
        {"id": "mail", "enabled": True,
         "params": {"extra": {"target_stamina": 450}}},
    ]
    result = asyncio.run(engine.run(_ctx(plan=plan)))
    assert result.status == "success"
    assert _ExtraCaptureTask.can_run_called
    assert _ExtraCaptureTask.captured == {"target_stamina": 450}


def test_run_no_extra_params_leaves_task_untouched():
    reg = {"mail": TaskMeta(_ExtraCaptureTask, "邮件", True)}
    engine = WorkflowEngine(reg)
    result = asyncio.run(engine.run(_ctx(plan=[{"id": "mail"}])))
    assert result.status == "success"
    assert _ExtraCaptureTask.captured == {}
