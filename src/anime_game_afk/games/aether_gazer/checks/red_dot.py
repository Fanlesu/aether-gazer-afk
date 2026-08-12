"""Red dot detection check.

Red dots are the game's "you have something to claim" markers — small
bright-red circles on hub icons and sidebar tabs. This check wraps
:func:`anime_game_afk.vision.color.red_dot_ratio` so tasks can gate on a
red dot without importing the vision layer directly (see
``tests/test_architecture.py::test_tasks_do_not_import_vision``).

No side effects — takes a screenshot and analyses it.
"""
from __future__ import annotations

import numpy as np

from anime_game_afk.games.aether_gazer.checks.base import CheckResult
from anime_game_afk.games.aether_gazer.ops.base import OpContext
from anime_game_afk.vision.color import red_dot_ratio


class RedDotCheck:
    """Check whether a red dot is present at a normalized coordinate.

    Args:
        fx: Horizontal position as a fraction [0.0, 1.0].
        fy: Vertical position as a fraction [0.0, 1.0].
        label: Optional name used in log/result messages (e.g. "mail").
        image: Optional pre-captured BGR image. When omitted the check
            takes its own screenshot. Pass it when the caller already has
            a screenshot (e.g. to also snap it to the run log) to avoid a
            redundant capture.

    ``CheckResult.data`` carries the confidence ratio (float) so callers
    can log it or compare several dots; ``passed`` is ``ratio > 0``.
    """

    def __init__(
        self,
        fx: float,
        fy: float,
        *,
        label: str = "",
        image: np.ndarray | None = None,
    ) -> None:
        self._fx = fx
        self._fy = fy
        self._label = label
        self._image = image

    async def evaluate(self, ctx: OpContext) -> CheckResult:
        if self._image is not None:
            img = self._image
        else:
            img = ctx.device.screenshot()
        h, w = img.shape[:2]
        ratio = red_dot_ratio(img, self._fx, self._fy, w, h)
        passed = ratio > 0
        name = self._label or f"({self._fx:.3f},{self._fy:.3f})"
        ctx.logger.debug(
            f"RedDotCheck[{name}]: ratio={ratio:.3f} passed={passed}"
        )
        return CheckResult(
            passed=passed,
            data=ratio,
            message=f"red dot {name}: ratio={ratio:.3f}",
        )
