"""Unit tests for TaskManager.save_plan (L1 user task orchestration).

Exercises plan persistence in isolation: order retention, safe-task
protection, unknown-id dropping, param persistence, and atomic config
write. The heavy TaskManager.__init__ (registry / hotkey listener / Win32
Job Object) is bypassed by constructing the instance WITHOUT calling
__init__ and injecting only the attributes ``save_plan`` touches, so the
test stays fast and does not require a game window or Windows APIs.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from anime_game_afk.ui import task_manager as tm_mod
from anime_game_afk.ui.task_manager import PipelineDef, TaskState


def _make_manager() -> tm_mod.TaskManager:
    mgr = tm_mod.TaskManager.__new__(tm_mod.TaskManager)
    mgr._lock = threading.Lock()
    mgr._pipelines = [
        PipelineDef(
            id="daily_routine",
            name="每日一条龙",
            description="",
            tasks=[
                TaskState(id="startup", name="启动游戏", description="", safe=True),
                TaskState(id="mail", name="领取邮件", description="", safe=True),
                TaskState(id="intel_shards", name="购买情报", description="", safe=False),
                TaskState(id="missions", name="每日周常任务", description="", safe=True),
            ],
        )
    ]
    return mgr


@pytest.fixture
def mgr(tmp_path: Path):
    cfg = tmp_path / "ui_state.json"
    with patch.object(tm_mod, "_CONFIG_PATH", cfg):
        yield _make_manager()


def _ids(mgr) -> list[str]:
    return [t.id for t in mgr._pipelines[0].tasks]


def test_save_plan_reorders_and_persists(mgr) -> None:
    plan = [
        {"id": "missions", "enabled": True, "params": {}},
        {"id": "mail", "enabled": True, "params": {}},
        {"id": "startup", "enabled": True, "params": {}},
        {"id": "intel_shards", "enabled": True, "params": {}},
    ]
    assert mgr.save_plan("daily_routine", plan) is True
    assert _ids(mgr) == ["missions", "mail", "startup", "intel_shards"]


def test_save_plan_drops_unknown_ids(mgr) -> None:
    plan = [
        {"id": "mail", "enabled": True, "params": {}},
        {"id": "ghost_task", "enabled": True, "params": {}},
    ]
    assert mgr.save_plan("daily_routine", plan) is True
    assert _ids(mgr) == ["mail"]
    assert "ghost_task" not in _ids(mgr)


def test_save_plan_forces_safe_enabled(mgr) -> None:
    plan = [
        {"id": "startup", "enabled": False, "params": {}},       # safe -> forced on
        {"id": "mail", "enabled": False, "params": {}},          # safe -> forced on
        {"id": "intel_shards", "enabled": False, "params": {}},  # non-safe -> stays off
    ]
    assert mgr.save_plan("daily_routine", plan) is True
    tasks = {t.id: t for t in mgr._pipelines[0].tasks}
    assert tasks["startup"].enabled is True
    assert tasks["mail"].enabled is True
    assert tasks["intel_shards"].enabled is False


def test_save_plan_persists_params(mgr) -> None:
    plan = [
        {
            "id": "mail",
            "enabled": True,
            "params": {
                "timeout": 30,
                "retry": 2,
                "wait_before": 1.5,
                "wait_after": 0.5,
            },
        }
    ]
    assert mgr.save_plan("daily_routine", plan) is True
    tasks = {t.id: t for t in mgr._pipelines[0].tasks}
    assert tasks["mail"].params == {
        "timeout": 30,
        "retry": 2,
        "wait_before": 1.5,
        "wait_after": 0.5,
    }


def test_save_plan_rejects_unknown_pipeline(mgr) -> None:
    assert mgr.save_plan("does_not_exist", []) is False


def test_save_plan_writes_config_file(mgr, tmp_path: Path) -> None:
    plan = [{"id": "mail", "enabled": True, "params": {"retry": 1}}]
    mgr.save_plan("daily_routine", plan)
    cfg = tmp_path / "ui_state.json"
    assert cfg.exists()
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert "daily_routine" in data["pipelines"]
    assert data["pipelines"]["daily_routine"]["order"] == ["mail"]
