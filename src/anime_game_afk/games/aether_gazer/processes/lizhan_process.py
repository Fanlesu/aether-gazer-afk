"""历战轮回 (Battle Recurrence) process.

Standalone process (NOT part of daily routine) that repeats 历战轮回
indefinitely until the user stops the process.

The loop driver, consecutive-failure stop, status notification and result
aggregation live in :class:`LoopProcess` (processes.base); this module
only declares which task to loop.
"""
from __future__ import annotations

from anime_game_afk.games.aether_gazer.processes.base import LoopProcess
from anime_game_afk.games.aether_gazer.tasks.lizhan_tasks import LizhanCombat


class LizhanProcess(LoopProcess):
    """Repeatedly run 历战轮回 for proficiency/affection grinding.

    Each cycle runs LizhanCombat (verify → fight → restart).
    Loops until user stops or 3 consecutive failures.
    """

    name = "历战刷熟练度"
    description = "自动无限刷历战轮回，用于刷熟练度或好感度（需手动导航到作战准备页面）"
    task_cls = LizhanCombat
    task_id = "lizhan_combat"
    max_consecutive_failures = 3
