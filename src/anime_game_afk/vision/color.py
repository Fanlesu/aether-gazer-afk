"""HSV color detection utilities.

Pure functions for identifying pixel ratios by HSV color range.
No state, no side effects.
"""
from __future__ import annotations

import cv2
import numpy as np

from anime_game_afk.core.types import Rect


def color_ratio(
    image: np.ndarray,
    hsv_low: tuple[int, int, int],
    hsv_high: tuple[int, int, int],
    region: Rect | None = None,
) -> float:
    """Calculate the fraction of pixels matching an HSV color range.

    Args:
        image: BGR source image.
        hsv_low: Lower HSV bound as (H, S, V).
        hsv_high: Upper HSV bound as (H, S, V).
        region: Optional sub-region to analyse. When provided, only pixels
                inside the rectangle are considered.

    Returns:
        Float in [0.0, 1.0] — ratio of matching pixels to total pixels.
        Returns 0.0 for an empty region.
    """
    if region is not None:
        from anime_game_afk.vision.geometry import crop  # local import avoids circular deps
        image = crop(image, region)

    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array(hsv_low, dtype=np.uint8), np.array(hsv_high, dtype=np.uint8))

    total = mask.size
    if total == 0:
        return 0.0
    return float(np.count_nonzero(mask)) / total


# ── Red dot detection ───────────────────────────────────────────
# 红点是游戏中标记"有可领取奖励"的小圆点，亮红色。HSV 红色跨色相环
# 0-10 和 170-180 两段，所以需要两个 inRange 取并集。

# Default HSV ranges for the red dot (both segments)
_RED_LOW_1 = np.array((0, 120, 120), dtype=np.uint8)
_RED_HIGH_1 = np.array((10, 255, 255), dtype=np.uint8)
_RED_LOW_2 = np.array((170, 120, 120), dtype=np.uint8)
_RED_HIGH_2 = np.array((180, 255, 255), dtype=np.uint8)


def red_dot_ratio(
    image: np.ndarray,
    fx: float,
    fy: float,
    w: int,
    h: int,
    *,
    region_ratio: float = 0.025,
    min_ratio: float = 0.05,
    min_blob_ratio: float = 0.03,
) -> float:
    """Red-dot confidence at normalized coord (fx, fy) in a BGR image.

    Crops a square region around (fx, fy) whose side scales with the
    window's shorter edge (adapts to 720p / 1080p / 1440p), masks red
    pixels across both HSV red segments, then requires a single
    connected blob large enough to be a real dot - this rejects
    scattered red noise (skill icons, hp bars, etc.).

    Args:
        image: BGR source image (screenshot).
        fx, fy: Normalized coordinate [0,1] of the dot center.
        w, h: Image pixel width / height (pass screenshot dims).
        region_ratio: Crop side as a fraction of min(w, h).
        min_ratio: Minimum overall red-pixel ratio to proceed (pre-check).
        min_blob_ratio: Minimum largest-connected-component ratio to accept.

    Returns:
        0.0 if no convincing red dot found, otherwise the largest blob's
        area as a fraction of the crop (higher = more confident).
    """
    if w <= 0 or h <= 0:
        return 0.0
    if not (0.0 <= fx <= 1.0 and 0.0 <= fy <= 1.0):
        return 0.0

    cx = int(fx * w)
    cy = int(fy * h)
    side = max(8, int(region_ratio * min(w, h)))
    hs = side // 2

    x1, x2 = max(0, cx - hs), min(w, cx + hs)
    y1, y2 = max(0, cy - hs), min(h, cy + hs)
    crop = image[y1:y2, x1:x2]
    if crop.size == 0:
        return 0.0

    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, _RED_LOW_1, _RED_HIGH_1)
    mask = cv2.bitwise_or(mask, cv2.inRange(hsv, _RED_LOW_2, _RED_HIGH_2))

    total = mask.size
    if total == 0:
        return 0.0

    if np.count_nonzero(mask) / float(total) < min_ratio:
        return 0.0

    num, _labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    if num <= 1:
        return 0.0
    blob_areas = stats[1:, cv2.CC_STAT_AREA]
    largest = int(blob_areas.max())
    largest_ratio = largest / float(total)
    if largest_ratio < min_blob_ratio:
        return 0.0
    return largest_ratio
