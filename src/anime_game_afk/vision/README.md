# vision/ — Vision Toolkit (Layer 2)

Game-agnostic computer vision tools. Pure functions: image in, results out.

## Files

| File | Purpose |
|------|---------|
| `types.py` | `MatchResult`, `TextResult` dataclasses |
| `matcher.py` | Template matching (`cv2.matchTemplate` wrapper) |
| `geometry.py` | Crop, resize, contour detection *(planned)* |
| `color.py` | HSV colour detection *(planned)* |
| `ocr.py` | OCR interface — template-based initially *(planned)* |

## Rules

- Stateless pure functions only
- No device access, no file I/O, no game resources
- Callers pass images in (`np.ndarray`), get results out
- Only imports from `core.types`

## Usage

```python
import cv2
import numpy as np
from anime_game_afk.core.types import Rect
from anime_game_afk.vision.matcher import match_template, match_best, match_all

# Load images however you like (device capture, file, etc.)
image: np.ndarray = ...
template: np.ndarray = cv2.imread("template.png", cv2.IMREAD_GRAYSCALE)

# Single template search
result = match_template(image, template, threshold=0.8)
if result.matched:
    print(f"Found at ({result.x}, {result.y}) with score {result.score:.3f}")

# Search within a sub-region
region = Rect(x=100, y=50, w=400, h=300)
result = match_template(image, template, region=region, threshold=0.8)

# Best of many templates
result = match_best(image, [tmpl_a, tmpl_b, tmpl_c], threshold=0.75)

# All occurrences (non-maximum suppression applied)
results = match_all(image, template, threshold=0.8)
for r in results:
    print(f"  ({r.x}, {r.y})  score={r.score:.3f}")
```

## Scoring Convention

All functions use **higher = better** scoring regardless of the underlying
`cv2` method:

- `TM_CCOEFF_NORMED`, `TM_CCORR_NORMED` — raw score (already higher = better)
- `TM_SQDIFF`, `TM_SQDIFF_NORMED` — score inverted to `1 - raw_value`

`MatchResult.matched` is `True` when `score >= threshold`.

## Recognition strategy (resolution / aspect independent)

All screenshots are normalized by `engine/device.DeviceAdapter.screenshot()`
to the content pack's `design_resolution` (default 1280x720) via viewport crop
+ FIT resize. On top of that, the matching layer is tolerant by design:

1. **OCR + red-dot first (primary state detection).** `ocr.py` crops to a
   region, downscales, recognizes, then maps coordinates back to the original
   image space — so it is scale-robust. Red-dot detection is blob-based and
   aspect-agnostic. Prefer these for state/UI gating.
2. **Template matching as fallback** (`matcher.py`) for icon-only targets
   with no text. `match_template` now searches multiple scales (see
   `MATCH_SCALES`) so it absorbs DPI / minor UI scaling that single-scale
   matching would miss.
3. **Explicit `viewport`** on `DeviceConfig` (fractional rect) overrides
   auto letterbox detection when the game area is not the full window.

Rule of thumb: if a state can be told from text or a red dot, do NOT use a
template — it is the most brittle to layout/scaling changes.
