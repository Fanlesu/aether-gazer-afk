"""User-defined atomic action runner for L3 custom steps.

A custom step is a list of declarative action dicts executed in order by a
game-specific executor. The engine stays game-agnostic and calls
:func:`run_custom_action` through its ``action_executor`` callback; only this
module knows about the device, OCR, and red dots.

Action schema (all coordinates fractional, per CLAUDE.md):

    {"type": "click", "x": 0.5, "y": 0.5}
    {"type": "wait", "seconds": 2}
    {"type": "swipe", "x1": 0.2, "y1": 0.8, "x2": 0.2, "y2": 0.2,
     "duration": 500}
    {"type": "ocr_wait", "text": "确认", "region": [x, y, w, h],
     "threshold": 0.5, "timeout": 10, "interval": 1.0}
    {"type": "reddot_wait", "key": "mail", "timeout": 10, "interval": 1.0}
    {"type": "reddot_wait", "fx": 0.87, "fy": 0.099, "timeout": 10}

Each action returns True when satisfied. A ``*_wait`` action returns False on
timeout; the engine turns a False into a skip/abort per the step's ``on_fail``
policy.
"""
from __future__ import annotations

import asyncio
import time

from anime_game_afk.core.types import Rect
from anime_game_afk.games.aether_gazer.checks.red_dot import RedDotCheck
from anime_game_afk.games.aether_gazer.knowledge.red_dots import RED_DOTS
from anime_game_afk.games.aether_gazer.processes.base import ProcessContext
from anime_game_afk.vision.ocr import ocr_find


async def run_custom_action(action: dict, ctx: ProcessContext) -> bool:
    """Execute one atomic action. Returns True if satisfied, False otherwise.

    Unknown action types are skipped (treated as satisfied) so a stale plan
    can't block a run.
    """
    atype = action.get("type")
    if atype == "click":
        ctx.device.click(float(action["x"]), float(action["y"]))
        return True
    if atype == "wait":
        await asyncio.sleep(max(0.0, float(action.get("seconds", 0))))
        return True
    if atype == "swipe":
        ctx.device.swipe(
            float(action["x1"]), float(action["y1"]),
            float(action["x2"]), float(action["y2"]),
            int(action.get("duration", 500)),
        )
        return True
    if atype == "ocr_wait":
        return await _ocr_wait(action, ctx)
    if atype == "reddot_wait":
        return await _reddot_wait(action, ctx)
    ctx.logger.warning(f"unknown custom action type: {atype}; skipping")
    return True


async def _ocr_wait(action: dict, ctx: ProcessContext) -> bool:
    """Poll OCR until ``text`` appears in ``region`` or ``timeout`` elapses."""
    text = action["text"]
    region = None
    r = action.get("region")
    if r:
        region = Rect(
            float(r[0]), float(r[1]), float(r[2]), float(r[3])
        )  # fractional -> ocr_find scales internally
    threshold = float(action.get("threshold", 0.5))
    timeout = float(action.get("timeout", 10))
    interval = float(action.get("interval", 1.0))
    deadline = time.monotonic() + timeout
    while True:
        found = ocr_find(
            ctx.device.screenshot(), text, region=region, threshold=threshold
        )
        if found is not None:
            return True
        if time.monotonic() >= deadline:
            return False
        await asyncio.sleep(interval)


async def _reddot_wait(action: dict, ctx: ProcessContext) -> bool:
    """Poll a red dot until it appears or ``timeout`` elapses."""
    fx, fy = _reddot_coords(action)
    label = action.get("key", action.get("label", ""))
    timeout = float(action.get("timeout", 10))
    interval = float(action.get("interval", 1.0))
    deadline = time.monotonic() + timeout
    while True:
        result = await RedDotCheck(fx, fy, label=label).evaluate(ctx)
        if result.passed:
            return True
        if time.monotonic() >= deadline:
            return False
        await asyncio.sleep(interval)


def _reddot_coords(action: dict) -> tuple[float, float]:
    """Resolve red-dot coordinates from a RED_DOTS key or explicit fx/fy."""
    if "key" in action:
        return RED_DOTS[action["key"]]
    return float(action["fx"]), float(action["fy"])
