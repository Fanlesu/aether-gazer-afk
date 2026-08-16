"""多维变量 (Multidimensional Variable) process.

Standalone process (NOT part of daily routine) that repeats 多维变量
dungeon runs indefinitely until the user stops the process.

The loop driver, consecutive-failure stop, status notification and result
aggregation live in :class:`LoopProcess` (processes.base); this module
only declares which task to loop.
"""
from __future__ import annotations

from anime_game_afk.games.aether_gazer.processes.base import LoopProcess
from anime_game_afk.games.aether_gazer.tasks.duowei_tasks import DuoweiCombat


class DuoweiProcess(LoopProcess):
    """Repeatedly run 多维变量 challenges for score accumulation.

    Each cycle runs DuoweiCombat (navigate → setup → fight → exit).
    Loops until user stops or 3 consecutive failures.
    """

    name = "多维变量"
    description = "自动重复挑战多维变量，累积积分（无限循环直到手动停止）"
    task_cls = DuoweiCombat
    task_id = "duowei_combat"
    max_consecutive_failures = 3
