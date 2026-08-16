"""User-facing condition resolver for L2 orchestration.

Translates a declarative condition dict (written by the user in a plan)
into a boolean against the live :class:`ProcessContext`. The engine stays
game-agnostic and calls this via its ``resolve_condition`` callback; only
this module knows about red dots, OCR, and the run-local value store.

Condition schema (all coordinates fractional, per CLAUDE.md):
    {"type": "reddot", "key": "mail"}
    {"type": "reddot", "fx": 0.87, "fy": 0.099}
    {"type": "ocr", "text": "情报", "region": [x, y, w, h]}
    {"type": "value", "key": "stamina", "op": ">", "value": 100}
    {"type": "always"} | {"type": "never"}
    {"type": "not", "cond": <cond>}
    {"type": "all", "conds": [<cond>, ...]}
    {"type": "any", "conds": [<cond>, ...]}

Unknown types log a warning and resolve truthy (forward-compatible).
"""
from __future__ import annotations

from typing import Any

from anime_game_afk.core.types import Rect
from anime_game_afk.games.aether_gazer.checks.red_dot import RedDotCheck
from anime_game_afk.games.aether_gazer.knowledge.red_dots import RED_DOTS
from anime_game_afk.games.aether_gazer.processes.base import ProcessContext
from anime_game_afk.vision.ocr import ocr_find

_OPS: dict[str, Any] = {
    ">": float.__gt__,
    ">=": float.__ge__,
    "<": float.__lt__,
    "<=": float.__le__,
    "==": float.__eq__,
    "!=": float.__ne__,
}


async def resolve_condition(cond: dict, ctx: ProcessContext) -> bool:
    """Evaluate a condition dict against the live context.

    Never raises for an unknown type (resolves truthy so a stale/missing
    condition can't block a run); resolver *bugs* are caught upstream by the
    engine, which also treats them as unmet.
    """
    ctype = cond.get("type")
    if ctype in ("always", None):
        return True
    if ctype == "never":
        return False
    if ctype == "not":
        return not await resolve_condition(cond["cond"], ctx)
    if ctype == "all":
        return all([await resolve_condition(c, ctx) for c in cond["conds"]])
    if ctype == "any":
        return any([await resolve_condition(c, ctx) for c in cond["conds"]])
    if ctype == "reddot":
        fx, fy = _reddot_coords(cond)
        result = await RedDotCheck(fx, fy, label=cond.get("key", "")).evaluate(ctx)
        return result.passed
    if ctype == "ocr":
        return await _ocr_condition(cond, ctx)
    if ctype == "value":
        return _value_condition(cond, ctx)
    ctx.logger.warning(f"unknown condition type: {ctype}; resolving truthy")
    return True


def _reddot_coords(cond: dict) -> tuple[float, float]:
    """Resolve red-dot coordinates from a RED_DOTS key or explicit fx/fy."""
    if "key" in cond:
        fx, fy = RED_DOTS[cond["key"]]
        return fx, fy
    return float(cond["fx"]), float(cond["fy"])


async def _ocr_condition(cond: dict, ctx: ProcessContext) -> bool:
    region = None
    if "region" in cond:
        x, y, w, h = cond["region"]
        region = Rect(x, y, w, h)  # fractional -> ocr_find scales internally
    img = ctx.device.screenshot()
    found = ocr_find(
        img,
        cond["text"],
        region=region,
        threshold=float(cond.get("threshold", 0.5)),
    )
    return found is not None


def _value_condition(cond: dict, ctx: ProcessContext) -> bool:
    key = cond["key"]
    # Prefer run-local state, fall back to the static plan config.
    actual = ctx.state.get(key, ctx.config.get(key))
    if actual is None:
        ctx.logger.debug(f"value condition: key {key!r} not present")
        return False
    op = _OPS.get(cond.get("op", "=="))
    if op is None:
        ctx.logger.warning(f"value condition: unknown op {cond.get('op')!r}")
        return False
    try:
        return bool(op(float(actual), float(cond["value"])))
    except (TypeError, ValueError) as exc:
        ctx.logger.warning(f"value condition compare failed: {exc}")
        return False
