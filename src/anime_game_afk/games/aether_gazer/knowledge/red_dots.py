"""Red-dot anchor coordinates (fractional [0, 1]).

These are pure UI facts — the normalized screen positions where the game
renders its "you have something to claim" red-dot badges on each relevant
page. They belong in Layer 4 (knowledge) alongside ``pages.py``: a UI
layout change only ever touches this one file, and every task that gates
on a red dot pulls its anchor from here rather than hardcoding a literal.

Each value is ``(fx, fy)`` in the project's normalized coordinate space
(see CLAUDE.md: never scan pixels for UI; reference known positions). The
values were verified with the coordinate picker at the design resolution
and are resolution-independent by construction.

The *detection logic* (HSV red-dot matching) intentionally stays in
``checks/red_dot.py`` (Layer 5) — only the *data* lives here.
"""
from __future__ import annotations

# Key -> (fx, fy). Keys are named by the UI element the dot marks.
RED_DOTS: dict[str, tuple[float, float]] = {
    # Mail inbox — unread mail badge on the hub mail icon
    "mail": (0.870, 0.099),
    # Shop — pending 情报徽章 exchange badge
    "intel_shards_badge": (0.056, 0.256),
    # Shop — free stamina supply area badge
    "free_stamina_supply": (0.386, 0.801),
    # Shop — daily stamina packs badge
    "stamina_pack": (0.522, 0.028),
    # Guild — matrix supply claimable indicator
    "guild_supply_door": (0.961, 0.907),
    # Guild — guild task claimable indicator
    "guild_task_entry": (0.837, 0.906),
    # Amusement — park task claimable indicator
    "amusement_park_task": (0.682, 0.898),
    # Hub — mission center (daily/weekly claim) icon
    "hub_mission": (0.828, 0.094),
    # Observation — 日常任务 tab
    "daily_tab": (0.058, 0.142),
    # Observation — 周常任务 tab (detection only)
    "weekly_tab": (0.058, 0.248),
    # Observation — tactics protocol task
    "tactics": (0.052, 0.153),
    # Activity — joint defense reward
    "joint_defense_reward": (0.058, 0.540),
}
