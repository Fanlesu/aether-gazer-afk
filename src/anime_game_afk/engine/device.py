"""DeviceAdapter — single point of contact with MaaFramework for device I/O.

Responsibilities:
- Window discovery and connection lifecycle (connect / disconnect)
- Screenshot capture with proportional scaling (height-capped, aspect-ratio preserved)
- Input delegation via fractional coordinates (click, swipe, press_key, hold_key)

Coordinate convention:
    All click/swipe coordinates are **fractional** values in [0.0, 1.0].
    (0.0, 0.0) = top-left, (1.0, 1.0) = bottom-right, (0.5, 0.5) = center.
    Internally converted to actual window pixels for input delivery.

Screenshot scaling:
    Captures are normalized to the content pack's ``design_resolution``
    (default 1280x720) via viewport crop + FIT resize.  This makes recognition
    resolution- and aspect-ratio-independent: non-16:9 windows (e.g. a 16:10
    laptop running a 16:9 game) are auto-cropped to the game viewport and
    normalized to the same canvas, so templates / OCR / red-dot anchors stay valid.

Explicitly out of scope:
- Resource loading (no ``maa.resource.Resource``)
- Pipeline / Tasker execution (no ``maa.tasker.Tasker``)
"""
from __future__ import annotations

import ctypes
import threading
import time
from ctypes import wintypes as _wintypes

import cv2
import numpy as np
from loguru import logger
from maa.controller import Win32Controller
from maa.toolkit import Toolkit

from anime_game_afk.core.errors import (
    DeviceConnectionError,
    ScreenshotError,
    WindowNotFoundError,
)
from anime_game_afk.core.input_guard import (
    InputGuard,
    release_modifiers_globally,
)
from anime_game_afk.core.types import DeviceConfig, Resolution

# Maximum screenshot output height.  Captures taller than this are scaled
# down proportionally (preserving aspect ratio).  Shorter captures are
# returned as-is (never upscaled).  720 keeps ~32 px icons readable and
# matches the effective OCR resolution.
MAX_HEIGHT = 720


class DeviceAdapter:
    """Low-level device I/O adapter wrapping MaaFramework's Win32 controller.

    All click/swipe coordinates are **fractional** ``(fx, fy)`` in [0.0, 1.0].
    Screenshots are normalized to the content pack's ``design_resolution``
    (default 1280x720) via viewport crop + FIT resize.

    Example::

        from anime_game_afk.games.content_pack import get_content_pack

        device = DeviceAdapter(get_content_pack().config.to_device_config())
        device.connect()
        img = device.screenshot()       # proportionally-scaled BGR ndarray
        device.click(0.5, 0.5)          # fractional center click
        device.disconnect()
    """

    def __init__(self, config: DeviceConfig) -> None:
        self._config = config
        self._controller: Win32Controller | None = None
        self._hwnd: ctypes.c_void_p | None = None

        # Actual window resolution — set on connect(), None when disconnected.
        self._actual: Resolution | None = None
        # Game viewport crop (x, y, w, h) in client-area pixels, resolved once
        # at connect(). screenshot() crops to this rect before normalizing and
        # click() maps fractional coords back through it, so recognition (which
        # operates on the cropped, normalized canvas) and input always share
        # one coordinate frame. None = use the whole window (16:9 windows land
        # here). This is what fixes clicks landing inside letterbox bars or
        # being vertically shifted on non-16:9 windows.
        self._viewport_crop: tuple[int, int, int, int] | None = None
        # Last screenshot output dimensions (after proportional scaling).
        self._screenshot_res: Resolution | None = None
        self._input_lock = threading.Lock()
        # Low-level mouse hook guard: pins the cursor in place while we
        # click, so a user moving the mouse cannot deflect the click.
        # NOTE: this guard is instantiated but NOT started — cursor pinning
        # is instead done inline in click() via SetCursorPos + ClipCursor
        # (see click() below). InputGuard.start()/stop() are currently
        # unused; do not claim the hook is active.
        self._input_guard: InputGuard = InputGuard()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def connected(self) -> bool:
        """True when a controller connection is active."""
        return self._controller is not None

    @property
    def config(self) -> DeviceConfig:
        """The :class:`DeviceConfig` this adapter was created with."""
        return self._config

    @property
    def actual_resolution(self) -> Resolution:
        """Real window resolution detected after :meth:`connect`.

        Raises ``DeviceConnectionError`` if not connected.
        """
        if self._actual is None:
            raise DeviceConnectionError("Not connected — actual_resolution unavailable")
        return self._actual

    @property
    def resolution(self) -> tuple[int, int]:
        """Current screenshot output dimensions ``(width, height)`` after scaling.

        This is what downstream vision code (matcher, OCR) should use as
        the coordinate reference frame.

        Raises ``DeviceConnectionError`` if no screenshot has been taken yet.
        """
        if self._screenshot_res is None:
            raise DeviceConnectionError("No screenshot taken yet — resolution unknown")
        return (self._screenshot_res.width, self._screenshot_res.height)

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    def find_window(self) -> ctypes.c_void_p:
        """Search for the game window by title.

        Two-pass matching:
        1. Exact title match (strongest signal)
        2. Substring match but ONLY for Unity windows (UnityWndClass)
           to avoid attaching to our own tool windows

        Returns:
            Win32 window handle (HWND) of the matching window.

        Raises:
            WindowNotFoundError: No matching window found.
        """
        windows = Toolkit.find_desktop_windows()
        title = self._config.window_title

        # Pass 1: exact title match
        for w in windows:
            if w.window_name == title:
                logger.info(
                    "Found game window (exact): title={!r} hwnd={} class={!r}",
                    w.window_name,
                    w.hwnd,
                    w.class_name,
                )
                return w.hwnd

        # Pass 2: substring match, Unity windows only
        for w in windows:
            if title in w.window_name and w.class_name == "UnityWndClass":
                logger.info(
                    "Found game window (Unity): title={!r} hwnd={} class={!r}",
                    w.window_name,
                    w.hwnd,
                    w.class_name,
                )
                return w.hwnd

        raise WindowNotFoundError(
            f"Window not found: {title!r}"
        )

    def connect(self) -> None:
        """Locate the game window and establish a MaaFw controller connection.

        Raises:
            WindowNotFoundError: Game window not found on the desktop.
            DeviceConnectionError: MaaFw controller could not be initialised.
        """
        self._connect_foreground()

    def _connect_foreground(self) -> None:
        """Standard foreground connection with screencap fallback.

        Tries the configured screencap method first, then falls back through
        increasingly compatible alternatives:
            FramePool → DXGI_DesktopDup → GDI
        """
        from maa.define import MaaWin32ScreencapMethodEnum

        self._hwnd = self.find_window()

        # Fallback chain: preferred method first, then progressively
        # more compatible (but potentially slower) alternatives.
        preferred = self._config.screencap_method
        fallbacks = [
            MaaWin32ScreencapMethodEnum.DXGI_DesktopDup,
            MaaWin32ScreencapMethodEnum.GDI,
        ]
        methods_to_try = [preferred] + [m for m in fallbacks if m != preferred]

        last_error: Exception | None = None
        for method in methods_to_try:
            try:
                logger.info(
                    "Trying screencap method: {}",
                    method.name if hasattr(method, 'name') else method,
                )
                self._controller = Win32Controller(
                    hWnd=self._hwnd,
                    screencap_method=method,
                    mouse_method=self._config.mouse_method,
                    keyboard_method=self._config.keyboard_method,
                )
                self._finish_connection()
                if method != preferred:
                    logger.warning(
                        "Using fallback screencap method '{}' (preferred '{}' failed)",
                        method.name if hasattr(method, 'name') else method,
                        preferred.name if hasattr(preferred, 'name') else preferred,
                    )
                return  # Success
            except (RuntimeError, OSError) as exc:
                last_error = exc
                logger.warning(
                    "Screencap method {} failed: {}",
                    method.name if hasattr(method, 'name') else method,
                    exc,
                )
                self._controller = None
                continue
            except DeviceConnectionError as exc:
                # _finish_connection raised — try next method
                last_error = exc
                logger.warning(
                    "Connection with {} failed: {}",
                    method.name if hasattr(method, 'name') else method,
                    exc,
                )
                self._controller = None
                continue

        # All methods exhausted
        raise DeviceConnectionError(
            f"All screencap methods failed. Last error: {last_error}\n"
            f"Please ensure Visual C++ Redistributable 2015-2022 is installed:\n"
            f"https://aka.ms/vs/17/release/vc_redist.x64.exe"
        )

    def _finish_connection(self) -> None:
        """Shared post-connection setup (raw size, screencap, aspect check)."""
        assert self._controller is not None

        self._controller.post_connection().wait()
        self._controller.set_screenshot_use_raw_size(True)
        self._controller.post_screencap().wait()

        actual_w, actual_h = self._controller.resolution

        # ── Validate the screencap is actually usable ──
        # Maa's post_screencap() does NOT raise when the underlying capture
        # unit fails to initialise (e.g. FramePool's D3D11 device creation
        # fails under RDP / sandbox / no-GPU sessions); it merely reports a
        # 0x0 resolution and yields no frame. Without this check the connection
        # is treated as "successful" yet every later screenshot() dies with
        # "Failed to get cached image", and the DXGI/GDI fallback chain in
        # _connect_foreground never runs. Raise so the caller falls back.
        if actual_w <= 0 or actual_h <= 0:
            raise DeviceConnectionError(
                f"screencap reported invalid resolution {actual_w}x{actual_h}"
            )

        # Smoke-test a real capture: a non-zero resolution with a dead capture
        # unit must also be rejected. post_screencap().wait().get() returns
        # None (or raises RuntimeError) when no frame was produced.
        try:
            _smoke = self._controller.post_screencap().wait().get()
        except RuntimeError as exc:
            raise DeviceConnectionError(
                f"screencap smoke-test failed: {exc}"
            ) from exc
        if _smoke is None:
            raise DeviceConnectionError(
                "screencap smoke-test returned no frame"
            )

        self._actual = Resolution(width=actual_w, height=actual_h)

        # Resolve and cache the game viewport once. screenshot() and click()
        # both use this rect, so recognition (operating on the viewport-cropped,
        # normalized canvas) and input stay in the same coordinate frame. For a
        # 16:9 window this is None (whole window); for a 16:10 window running a
        # 16:9 game it is the centered 16:9 region (top/bottom letterbox bars
        # cropped away). Without this, click() would map fractional coords to
        # the full window and land every click shifted / inside the bars.
        dw, dh = self._config.design_resolution
        design_ar = dw / dh
        self._viewport_crop = self._resolve_viewport(actual_w, actual_h, design_ar, img=_smoke)

        if actual_w > 0 and actual_h > 0:
            ratio = actual_w / actual_h
            if abs(ratio - 16 / 9) > 0.02:
                if self._viewport_crop is None:
                    # Window is non-16:9 and NO letterbox bars were detected, so
                    # the game is almost certainly rendering at a non-16:9 aspect
                    # ratio (e.g. a 16:10 game full-bleed on a 16:10 display).
                    # The entire template/coordinate set targets a 16:9 game view
                    # and WILL mis-match. Surface this loudly instead of silently
                    # normalizing and mis-clicking.
                    logger.warning(
                        "Window aspect ratio {:.3f} ({}x{}) is not 16:9 AND no "
                        "letterbox bars were detected. The game appears to render at "
                        "a non-16:9 aspect ratio. All templates/coordinates target a "
                        "16:9 game view and WILL mis-match. Fix: set the game to render "
                        "at 16:9 (e.g. 2560x1440) so it letterboxes on this display.",
                        ratio,
                        actual_w,
                        actual_h,
                    )
                else:
                    # Resolution-agnostic since v0.5.x: a real 16:9 game on a
                    # non-16:9 window letterboxes, we crop the bars and normalize
                    # to the content pack's design_resolution.
                    logger.warning(
                        "Window aspect ratio {:.3f} ({}x{}) is not 16:9; detected "
                        "letterbox bars and will auto-crop + normalize to the design "
                        "canvas ({}x{}).",
                        ratio,
                        actual_w,
                        actual_h,
                        self._config.design_resolution[0],
                        self._config.design_resolution[1],
                    )

        logger.info(
            "Device connected: hwnd={}, resolution={}x{}, screencap={}, mouse={}, keyboard={}",
            self._hwnd, actual_w, actual_h,
            self._config.screencap_method.name if hasattr(self._config.screencap_method, 'name') else self._config.screencap_method,
            self._config.mouse_method.name if hasattr(self._config.mouse_method, 'name') else self._config.mouse_method,
            self._config.keyboard_method.name if hasattr(self._config.keyboard_method, 'name') else self._config.keyboard_method,
        )

    def disconnect(self) -> None:
        """Release the controller and reset all connection state.

        Order matters:

        1. ``post_inactive()`` lets MaaFw clean up its own per-window
           state from its internal worker thread.
        2. ``release_all_held_keys()`` sends ``key_up`` for every recovery
           VK and OS-level ``SendInput`` ``KEYUP`` for modifier keys.
        3. Local state is cleared and the controller reference dropped.

        (``InputGuard.stop()`` is intentionally NOT called — the guard is
        never started; cursor pinning happens inline in click().)

        Best-effort throughout — disconnect must never raise.
        """
        logger.info("Device disconnecting: hwnd={}", self._hwnd)

        # 1. Tell MaaFw to clean up its per-window state (window position,
        #    any pending mouse-lock-follow tracking, etc.) from its own
        #    internal worker thread.
        if self._controller is not None:
            try:
                self._controller.post_inactive().wait()
            except Exception as exc:  # noqa: BLE001
                logger.warning("disconnect: post_inactive failed: {}", exc)

        # 2. Window-level key_up + OS-level modifier release.
        try:
            self.release_all_held_keys()
        except Exception as exc:  # noqa: BLE001
            logger.warning("disconnect: release_all_held_keys failed: {}", exc)

        self._controller = None
        self._hwnd = None
        self._actual = None
        self._viewport_crop = None
        self._screenshot_res = None

    # ------------------------------------------------------------------
    # Device I/O
    # ------------------------------------------------------------------

    def screenshot(self) -> np.ndarray:
        """Capture a screenshot, normalized to the content pack's design canvas.

        Pipeline (resolution / aspect-ratio independent):
            1. Resolve the game viewport in raw pixel space — explicit
               ``viewport`` config, or auto-detected letterbox bars when the
               window aspect ratio differs from ``design_resolution``.
            2. Crop to that viewport.
            3. FIT-resize into ``design_resolution`` (1280x720 default),
               letterbox-padding any residual aspect difference.

        For a 16:9 window this is bit-for-bit the previous behaviour
        (exact resize to 1280x720).  For a non-16:9 window (e.g. a 16:10
        laptop running a 16:9 game) the letterbox bars are cropped away and
        the game content is normalized to the same 1280x720 canvas, so
        templates / OCR / red-dot anchors stay valid.

        Returns:
            BGR ``numpy`` array at ``design_resolution``.

        Raises:
            ScreenshotError: Controller returned ``None`` for the image.
            DeviceConnectionError: Not connected.
        """
        self._ensure_connected()
        assert self._controller is not None

        _start = time.perf_counter()
        img: np.ndarray | None = (
            self._controller.post_screencap().wait().get()
        )
        if img is None:
            raise ScreenshotError("post_screencap returned None")

        raw_h, raw_w = img.shape[:2]
        dw, dh = self._config.design_resolution

        # 1. Resolve the source region (game viewport) in raw pixel space.
        #    Use the rect cached at connect() so screenshots and clicks always
        #    share the same coordinate frame (a 16:10 window must not have
        #    clicks land inside its letterbox bars).
        crop = self._viewport_crop
        if crop is not None:
            x, y, cw, ch = crop
            img = img[y : y + ch, x : x + cw]

        # 2. Normalize to the design canvas: proportional FIT + letterbox pad.
        #    For a 16:9 source this is an exact resize to (dw, dh); for other
        #    aspect ratios the residual is absorbed by neutral padding.
        img = self._fit_to_canvas(img, dw, dh)

        _elapsed_ms = (time.perf_counter() - _start) * 1000
        logger.debug(
            "Screenshot: {:.0f}ms, raw={}x{}, canvas={}x{}",
            _elapsed_ms, raw_w, raw_h, dw, dh,
        )

        self._screenshot_res = Resolution(width=dw, height=dh)
        return img

    def screenshot_raw(self) -> np.ndarray:
        """Capture a screenshot at native window resolution (no scaling).

        Use when pixel-perfect accuracy at actual resolution is required.

        Returns:
            BGR ``numpy`` array at actual window dimensions.

        Raises:
            ScreenshotError: Controller returned ``None`` for the image.
            DeviceConnectionError: Not connected.
        """
        self._ensure_connected()
        assert self._controller is not None

        img: np.ndarray | None = (
            self._controller.post_screencap().wait().get()
        )
        if img is None:
            raise ScreenshotError("post_screencap returned None")
        return img

    # ------------------------------------------------------------------
    # Screenshot normalization helpers (resolution / aspect independence)
    # ------------------------------------------------------------------

    def _resolve_viewport(
        self,
        raw_w: int,
        raw_h: int,
        design_ar: float,
        img: np.ndarray | None = None,
    ) -> tuple[int, int, int, int] | None:
        """Compute the source crop rectangle (raw pixel space) for the game area.

        Priority:
        1. Explicit ``viewport`` (fractional rect) from config — used as-is.
        2. Auto-detect letterbox bars when the window aspect ratio differs
           from the design aspect ratio. The candidate bars are VERIFIED to be
           genuinely dark before cropping — a 16:10 game rendered full-bleed on
           a 16:10 window has no bars, and blindly cropping it to 16:9 would
           slice off real game content and break template matching.
        3. None — use the whole window (16:9 windows, or non-16:9 windows whose
           game fills the frame with no letterbox).
        """
        cfg = self._config
        if cfg.viewport is not None:
            fx, fy, fw, fh = cfg.viewport
            x = int(fx * raw_w)
            y = int(fy * raw_h)
            cw = max(1, int(fw * raw_w))
            ch = max(1, int(fh * raw_h))
            return (x, y, cw, ch)

        raw_ar = raw_w / raw_h
        if cfg.auto_viewport and abs(raw_ar - design_ar) > 0.03 and img is not None:
            detected = self._detect_letterbox_viewport(img, raw_w, raw_h, design_ar)
            if detected is not None:
                return detected
        return None

    @staticmethod
    def _detect_letterbox_viewport(
        img: np.ndarray,
        raw_w: int,
        raw_h: int,
        design_ar: float,
    ) -> tuple[int, int, int, int] | None:
        """Detect and return a letterboxed game viewport, or None if no bars.

        Unlike a purely geometric estimate this VERIFIES the candidate
        letterbox bars are actually dark before cropping. A 16:10 game rendered
        full-bleed on a 16:10 window has no bars; blindly cropping it to 16:9
        would slice off real game content (top/bottom 80px) and break template
        matching. Only crop when the expected bar regions are genuinely
        near-black.
        """
        raw_ar = raw_w / raw_h
        if raw_ar < design_ar:
            # Window narrower than design -> bars on top/bottom.
            game_h = int(round(raw_w / design_ar))
            if game_h <= 0 or game_h >= raw_h:
                return None
            bar = (raw_h - game_h) // 2
            if bar <= 2:
                return None
            top_band = img[0:bar, :, :]
            bot_band = img[raw_h - bar : raw_h, :, :]
            if not DeviceAdapter._is_dark_band(top_band) or not DeviceAdapter._is_dark_band(
                bot_band
            ):
                return None
            y0 = (raw_h - game_h) // 2
            return (0, y0, raw_w, game_h)
        if raw_ar > design_ar:
            # Window wider than design -> bars on left/right.
            game_w = int(round(raw_h * design_ar))
            if game_w <= 0 or game_w >= raw_w:
                return None
            bar = (raw_w - game_w) // 2
            if bar <= 2:
                return None
            left_band = img[:, 0:bar, :]
            right_band = img[:, raw_w - bar : raw_w, :]
            if not DeviceAdapter._is_dark_band(left_band) or not DeviceAdapter._is_dark_band(
                right_band
            ):
                return None
            x0 = (raw_w - game_w) // 2
            return (x0, 0, game_w, raw_h)
        return None

    @staticmethod
    def _is_dark_band(band: np.ndarray) -> bool:
        """True if a strip of pixels is essentially a solid dark (letterbox) bar.

        Pure letterbox bars are ~0 luminance with negligible variance. A strict
        threshold keeps dark-but-real UI edges from being mistaken for bars.
        """
        if band.size == 0:
            return False
        gray = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY) if band.shape[-1] == 3 else band
        mean = float(gray.mean())
        std = float(gray.std())
        return mean < 12.0 and std < 8.0

    @staticmethod
    def _fit_to_canvas(img: np.ndarray, dw: int, dh: int) -> np.ndarray:
        """Resize ``img`` into a ``dw x dh`` canvas, preserving aspect ratio.

        The image is scaled with a FIT strategy (largest that fits) and the
        remaining space is padded with neutral black. For a source whose
        aspect ratio already equals ``dw/dh`` this is an exact resize with no
        padding. Always returns an array of shape ``(dh, dw, 3)``.
        """
        h, w = img.shape[:2]
        if h == dh and w == dw:
            return img
        src_ar = w / h
        dst_ar = dw / dh
        if src_ar > dst_ar:
            new_w = dw
            new_h = max(1, int(round(dw / src_ar)))
        else:
            new_h = dh
            new_w = max(1, int(round(dh * src_ar)))
        resized = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
        canvas = np.zeros((dh, dw, 3), dtype=img.dtype)
        y0 = (dh - new_h) // 2
        x0 = (dw - new_w) // 2
        canvas[y0 : y0 + new_h, x0 : x0 + new_w] = resized
        return canvas

    def _effective_viewport(self) -> tuple[int, int, int, int]:
        """Pixel rect (x, y, w, h) that fractional coords are relative to.

        Equals the cached game viewport when one was detected at connect(),
        otherwise the whole window. screenshot() crops to this same rect, so
        recognition and click() stay in one coordinate frame.
        """
        if self._viewport_crop is not None:
            return self._viewport_crop
        assert self._actual is not None
        return (0, 0, self._actual.width, self._actual.height)

    def click(self, fx: float, fy: float) -> None:
        """Send a mouse click at fractional coordinates.

        ``mouse_method`` is plain ``SendMessage`` (MaaFw doesn't touch the
        cursor).  To keep the cursor at the target across WM_LBUTTONDOWN
        and WM_LBUTTONUP — even if the user is dragging the mouse — we
        ``SetCursorPos(target)`` then ``ClipCursor`` to a 1x1 rectangle
        at the target for the click window.  Windows physically refuses
        to move the cursor outside the clip rect, so the user's hand
        motion is hard-blocked at the OS level — no hook, no Python in
        the input path, no other side-effects.
        """
        self._ensure_connected()
        assert self._controller is not None
        assert self._actual is not None

        # Map the fractional coord into the same pixel rect that screenshot()
        # crops to (the game viewport), NOT the raw window. On a 16:9 window the
        # viewport is the whole window, so this is identical to before; on a
        # 16:10 window it removes the letterbox offset/scale so clicks land on
        # the actual game UI instead of inside the bars or shifted vertically.
        vx, vy, vw, vh = self._effective_viewport()
        ax = int(vx + fx * vw)
        ay = int(vy + fy * vh)
        target_screen = self._client_to_screen(ax, ay)
        orig_cursor = self._get_cursor_pos()

        with self._input_lock:
            clipped = False
            if target_screen is not None:
                self._set_cursor_pos(*target_screen)
                clipped = self._clip_cursor_to(*target_screen)
            try:
                self._controller.post_click(ax, ay).wait()
            finally:
                # Hold the clip longer than the click itself so Unity's
                # WM_LBUTTONUP handler (which reads GetCursorPos in its own
                # render frame) sees a stable cursor at the target. 20ms was
                # too short - at 60fps a frame is ~17ms and a busy game
                # frame can slip past that window, causing the cursor to
                # already be back at orig_cursor when the game finally reads
                # it -> click silently lands at the old position (the "cursor
                # moved but nothing happened" symptom).
                time.sleep(0.08)
                if clipped:
                    self._clip_cursor_release()
                if orig_cursor is not None:
                    self._set_cursor_pos(*orig_cursor)
        logger.debug("click ({:.3f}, {:.3f}) -> actual ({}, {})", fx, fy, ax, ay)

    # ------------------------------------------------------------------
    # ClipCursor helpers
    # ------------------------------------------------------------------

    class _RECT(ctypes.Structure):
        _fields_ = [
            ("left", ctypes.c_long),
            ("top", ctypes.c_long),
            ("right", ctypes.c_long),
            ("bottom", ctypes.c_long),
        ]

    def _clip_cursor_to(self, x: int, y: int) -> bool:
        """Confine the OS cursor to a 1x1 rect at (x, y). Returns True on success."""
        return self._clip_cursor_rect(int(x), int(y), int(x) + 1, int(y) + 1)

    def _clip_cursor_rect(self, left: int, top: int, right: int, bottom: int) -> bool:
        """Confine the OS cursor to the given rect. Returns True on success."""
        self._ensure_thread_dpi_aware()
        try:
            rect = DeviceAdapter._RECT(int(left), int(top), int(right), int(bottom))
            return bool(
                ctypes.windll.user32.ClipCursor(ctypes.byref(rect))
            )
        except (AttributeError, OSError) as exc:
            logger.debug("ClipCursor set failed: {}", exc)
            return False

    def _clip_cursor_release(self) -> None:
        """Release any active cursor clip."""
        try:
            ctypes.windll.user32.ClipCursor(None)
        except (AttributeError, OSError) as exc:
            logger.debug("ClipCursor release failed: {}", exc)

    # ------------------------------------------------------------------
    # Win32 cursor helpers (used by click() to pin cursor on target)
    # ------------------------------------------------------------------

    # DPI awareness context: PER_MONITOR_AWARE_V2 makes ClientToScreen and
    # SetCursorPos work in *physical* pixels — the same coordinate system
    # the (DPI-aware) game window uses.  Python's main thread is usually
    # DPI-unaware, so without this call, ClientToScreen returns virtualized
    # logical coords and SetCursorPos lands the cursor in the wrong screen
    # position under HiDPI display scaling (125%/150% etc).
    _DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4

    @staticmethod
    def _ensure_thread_dpi_aware() -> None:
        """Switch the calling thread to PER_MONITOR_AWARE_V2.

        Best-effort, idempotent at the Windows kernel level (cheap to call
        repeatedly).  DPI awareness is per-thread; we set it inline before
        every ClientToScreen / SetCursorPos so any thread that ends up
        running click() is in the correct coordinate space.
        """
        try:
            ctypes.windll.user32.SetThreadDpiAwarenessContext(
                ctypes.c_void_p(
                    DeviceAdapter._DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
                )
            )
        except (AttributeError, OSError) as exc:
            logger.debug("SetThreadDpiAwarenessContext failed: {}", exc)

    def _client_to_screen(self, ax: int, ay: int) -> tuple[int, int] | None:
        """Translate client-area pixel coords to absolute screen coords."""
        self._ensure_thread_dpi_aware()
        if self._hwnd is None:
            return None
        pt = _wintypes.POINT(int(ax), int(ay))
        try:
            ok = ctypes.windll.user32.ClientToScreen(
                self._hwnd, ctypes.byref(pt),
            )
            if not ok:
                return None
        except (AttributeError, OSError) as exc:
            logger.debug("ClientToScreen failed: {}", exc)
            return None
        return (pt.x, pt.y)

    @staticmethod
    def _get_cursor_pos() -> tuple[int, int] | None:
        DeviceAdapter._ensure_thread_dpi_aware()
        pt = _wintypes.POINT()
        try:
            if ctypes.windll.user32.GetCursorPos(ctypes.byref(pt)):
                return (pt.x, pt.y)
        except (AttributeError, OSError) as exc:
            logger.debug("GetCursorPos failed: {}", exc)
        return None

    @staticmethod
    def _set_cursor_pos(x: int, y: int) -> bool:
        DeviceAdapter._ensure_thread_dpi_aware()
        try:
            return bool(
                ctypes.windll.user32.SetCursorPos(int(x), int(y))
            )
        except (AttributeError, OSError) as exc:
            logger.debug("SetCursorPos failed: {}", exc)
            return False

    def swipe(
        self,
        fx1: float,
        fy1: float,
        fx2: float,
        fy2: float,
        duration: int = 500,
    ) -> None:
        """Perform a pointer swipe between two fractional coordinates.

        Delegates to MaaFw's ``post_swipe``.  With
        ``SendMessageWithCursorPos`` mouse method, MaaFw moves the OS
        cursor along the swipe path itself, so we no longer run our own
        interpolation thread or absorb user input.

        Args:
            fx1: Start X as fraction [0.0, 1.0].
            fy1: Start Y as fraction [0.0, 1.0].
            fx2: End X as fraction [0.0, 1.0].
            fy2: End Y as fraction [0.0, 1.0].
            duration: Swipe duration in milliseconds (default 500).

        Raises:
            DeviceConnectionError: Not connected.
        """
        self._ensure_connected()
        assert self._controller is not None
        assert self._actual is not None

        ax1 = int(fx1 * self._actual.width)
        ay1 = int(fy1 * self._actual.height)
        ax2 = int(fx2 * self._actual.width)
        ay2 = int(fy2 * self._actual.height)
        start_screen = self._client_to_screen(ax1, ay1)
        end_screen = self._client_to_screen(ax2, ay2)
        orig_cursor = self._get_cursor_pos()

        with self._input_lock:
            stop_evt = threading.Event()
            mover: threading.Thread | None = None
            if start_screen is not None and end_screen is not None:
                mover = threading.Thread(
                    target=self._cursor_walk,
                    args=(start_screen, end_screen,
                          duration / 1000.0, stop_evt),
                    name="CursorWalk",
                    daemon=True,
                )
                mover.start()
            try:
                self._controller.post_swipe(ax1, ay1, ax2, ay2, duration).wait()
            finally:
                stop_evt.set()
                if mover is not None:
                    mover.join(timeout=0.5)
                if orig_cursor is not None:
                    self._set_cursor_pos(*orig_cursor)
        logger.debug(
            "swipe ({:.3f},{:.3f})->({:.3f},{:.3f}) duration={}ms -> "
            "pixel ({},{})->({},{})",
            fx1, fy1, fx2, fy2, duration, ax1, ay1, ax2, ay2,
        )

    def _cursor_walk(
        self,
        start: tuple[int, int],
        end: tuple[int, int],
        duration_s: float,
        stop_evt: threading.Event,
    ) -> None:
        """Linearly interpolate the cursor from ``start`` to ``end``.

        Plain ``SetCursorPos`` each step.  The outer ``swipe()`` method
        installs a single ``ClipCursor`` to the swipe-path bounding box
        before spawning this thread, so user mouse motion is kernel-
        constrained to that rect while we drive the path with
        ``SetCursorPos``.
        """
        # Ensure this thread is DPI-aware too.
        self._ensure_thread_dpi_aware()
        x1, y1 = start
        x2, y2 = end
        # 120Hz step rate (≥ display refresh) keeps the path smooth.
        step_dt = 0.008
        t0 = time.perf_counter()
        while not stop_evt.is_set():
            elapsed = time.perf_counter() - t0
            t = elapsed / duration_s if duration_s > 0 else 1.0
            if t >= 1.0:
                self._set_cursor_pos(x2, y2)
                return
            x = int(x1 + (x2 - x1) * t)
            y = int(y1 + (y2 - y1) * t)
            self._set_cursor_pos(x, y)
            if stop_evt.wait(step_dt):
                self._set_cursor_pos(x2, y2)
                return

    def press_key(self, vk_code: int) -> None:
        """Send a single key press (press + release cycle).

        Args:
            vk_code: Virtual-key code (Win32 VK_* constant).

        Raises:
            DeviceConnectionError: Not connected.
        """
        self._ensure_connected()
        assert self._controller is not None

        self._controller.post_press_key(vk_code).wait()
        logger.debug("press_key 0x{:02X}", vk_code)

    def hold_key(self, vk_code: int, duration_s: float) -> None:
        """Hold a key for a given duration using key_down + sleep + key_up.

        Args:
            vk_code: Virtual-key code (Win32 VK_* constant).
            duration_s: How long to hold the key in seconds.

        Raises:
            DeviceConnectionError: Not connected.

        Notes:
            ``key_up`` is sent even if ``time.sleep`` is interrupted (e.g. by
            ``KeyboardInterrupt``) to avoid leaving the game with a key stuck
            in the held-down state.  If the entire process is killed mid-sleep,
            this guard cannot run — :meth:`release_all_held_keys` should be
            called by the parent process after killing the worker.
        """
        self._ensure_connected()
        assert self._controller is not None

        self._controller.post_key_down(vk_code).wait()
        try:
            time.sleep(duration_s)
        finally:
            try:
                self._controller.post_key_up(vk_code).wait()
            except Exception as exc:  # noqa: BLE001 — best-effort release
                logger.warning(
                    "hold_key 0x{:02X}: key_up failed during cleanup: {}",
                    vk_code, exc,
                )
        logger.debug(
            "hold_key 0x{:02X} for {:.2f}s (key_down/key_up)",
            vk_code, duration_s,
        )

    # ------------------------------------------------------------------
    # Recovery / cleanup — release stuck input state
    # ------------------------------------------------------------------

    # Keys that any task / combat script may have left held in the game
    # window.  Sending ``key_up`` for each of these is harmless when the key
    # wasn't held; it costs ~1 SendMessage per key (well under 50ms total).
    _RECOVERY_VK_CODES: tuple[int, ...] = (
        # Movement / camera
        0x57, 0x41, 0x53, 0x44, 0x51, 0x45,            # W A S D Q E
        # Combat
        0x4A, 0x4B, 0x55, 0x49, 0x4F, 0x52,            # J K U I O R
        0x31, 0x32,                                     # 1 2
        # UI / panels
        0x47, 0x48, 0x54,                               # G H T
        # Special
        0x0D, 0x1B, 0x09, 0x20,                         # Enter Esc Tab Space
        # Modifiers (extra-stuck-prone)
        0x10, 0x11, 0x12,                               # Shift Ctrl Alt
        0xA0, 0xA1, 0xA2, 0xA3,                         # L/R Shift, L/R Ctrl
        0x5B, 0x5C,                                     # L/R Win
    )

    def release_all_held_keys(self) -> None:
        """Recover stuck input state — idempotent, safe when nothing is stuck.

        Two layers:

        1. Window-level: send ``WM_KEYUP`` to the game window via
           MaaFw for every VK we ever press as part of automation.
           Harmless to other apps.
        2. OS-level: ``SendInput`` ``KEYUP`` for Ctrl/Shift/Alt/Win.
           The window-level send cannot update the global OS modifier
           state; this layer does.  Required to recover when something
           (e.g. a script that died mid-``hold_key``) left a modifier
           down globally.
        """
        if self._controller is None:
            logger.debug("release_all_held_keys: not connected, skipping")
            return

        for vk in self._RECOVERY_VK_CODES:
            try:
                self._controller.post_key_up(vk).wait()
            except Exception as exc:  # noqa: BLE001 — best-effort cleanup
                logger.debug("release_all_held_keys: 0x{:02X} failed: {}", vk, exc)

        try:
            ctypes.windll.user32.BlockInput(False)
        except Exception as exc:  # noqa: BLE001
            logger.debug("release_all_held_keys: BlockInput(FALSE) failed: {}", exc)

        # OS-level modifier release. The post_key_up calls above only
        # send WM_KEYUP to the game window and cannot clear stuck
        # Ctrl/Shift/Alt/Win in the global OS key state.
        sent = release_modifiers_globally()

        logger.info(
            "release_all_held_keys: window key_up x{} + BlockInput(FALSE) + global modifier release x{}",
            len(self._RECOVERY_VK_CODES), sent,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_connected(self) -> None:
        """Raise :exc:`DeviceConnectionError` if not currently connected."""
        if not self.connected:
            raise DeviceConnectionError("DeviceAdapter is not connected")
