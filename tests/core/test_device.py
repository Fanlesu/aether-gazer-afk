"""Unit tests for DeviceAdapter.

All MaaFramework dependencies are fully mocked — no real game window
or MaaFw installation required to run these tests.
"""
from __future__ import annotations

import ctypes
from typing import Any
from unittest.mock import MagicMock, call, patch

import numpy as np
import pytest

from anime_game_afk.core.errors import (
    DeviceConnectionError,
    ScreenshotError,
    WindowNotFoundError,
)
from anime_game_afk.core.types import DeviceConfig, Resolution
from anime_game_afk.engine.device import DeviceAdapter

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _make_config(
    *,
    window_title: str = "TestWindow",
) -> DeviceConfig:
    """Build a DeviceConfig for testing."""
    return DeviceConfig(
        window_title=window_title,
        screencap_method=4,   # FramePool
        mouse_method=256,     # SendMessageWithCursorPos
        keyboard_method=256,  # SendMessageWithCursorPos
    )


def _fake_window(name: str, hwnd: int = 1, class_name: str = "FakeClass") -> MagicMock:
    """Return a mock desktop-window object."""
    w = MagicMock()
    w.window_name = name
    w.hwnd = ctypes.c_void_p(hwnd)
    w.class_name = class_name
    return w


def _make_controller_mock(
    *,
    resolution: tuple[int, int] = (1600, 900),
    screencap_img: np.ndarray | None = None,
) -> MagicMock:
    """Return a fully-stubbed Win32Controller mock."""
    ctrl = MagicMock()

    # post_connection().wait() chain
    ctrl.post_connection.return_value = MagicMock(
        wait=MagicMock(return_value=None)
    )
    # set_screenshot_use_raw_size is a plain call
    ctrl.set_screenshot_use_raw_size.return_value = None

    # resolution property
    type(ctrl).resolution = property(lambda self: resolution)

    # screencap chain: post_screencap().wait().get()
    if screencap_img is None:
        screencap_img = np.zeros(
            (resolution[1], resolution[0], 3), dtype=np.uint8
        )
    screencap_job = MagicMock()
    screencap_job.wait.return_value = screencap_job
    screencap_job.get.return_value = screencap_img
    ctrl.post_screencap.return_value = screencap_job

    # click / swipe / press_key chains
    action_job = MagicMock()
    action_job.wait.return_value = action_job
    ctrl.post_click.return_value = action_job
    ctrl.post_swipe.return_value = action_job
    ctrl.post_press_key.return_value = action_job

    return ctrl


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_initial_state_not_connected() -> None:
    """A freshly created adapter must not be connected."""
    cfg = _make_config()
    adapter = DeviceAdapter(cfg)
    assert not adapter.connected


def test_config_property() -> None:
    cfg = _make_config()
    adapter = DeviceAdapter(cfg)
    assert adapter.config is cfg


# ---------------------------------------------------------------------------
# find_window
# ---------------------------------------------------------------------------


def test_find_window_success() -> None:
    """find_window must return the HWND when a matching window exists."""
    cfg = _make_config(window_title="TestWindow")
    adapter = DeviceAdapter(cfg)

    windows = [
        _fake_window("OtherApp", hwnd=10),
        _fake_window("TestWindow - Level 1", hwnd=42, class_name="UnityWndClass"),
    ]
    with patch("anime_game_afk.engine.device.Toolkit") as mock_toolkit:
        mock_toolkit.find_desktop_windows.return_value = windows
        hwnd = adapter.find_window()

    # ctypes.c_void_p does not implement __eq__ by value; compare .value
    assert hwnd.value == ctypes.c_void_p(42).value  # type: ignore[union-attr]


def test_find_window_not_found() -> None:
    """find_window must raise WindowNotFoundError when no window matches."""
    cfg = _make_config(window_title="MissingGame")
    adapter = DeviceAdapter(cfg)

    with patch("anime_game_afk.engine.device.Toolkit") as mock_toolkit:
        mock_toolkit.find_desktop_windows.return_value = [
            _fake_window("SomeOtherApp")
        ]
        with pytest.raises(WindowNotFoundError, match="MissingGame"):
            adapter.find_window()


def test_find_window_empty_list() -> None:
    cfg = _make_config(window_title="Game")
    adapter = DeviceAdapter(cfg)

    with patch("anime_game_afk.engine.device.Toolkit") as mock_toolkit:
        mock_toolkit.find_desktop_windows.return_value = []
        with pytest.raises(WindowNotFoundError):
            adapter.find_window()


# ---------------------------------------------------------------------------
# connect / disconnect state transitions
# ---------------------------------------------------------------------------


@pytest.fixture()
def connected_adapter() -> DeviceAdapter:
    """Return a DeviceAdapter that has been successfully connected."""
    cfg = _make_config()
    adapter = DeviceAdapter(cfg)
    ctrl_mock = _make_controller_mock(resolution=(1600, 900))

    with (
        patch("anime_game_afk.engine.device.Toolkit") as mock_toolkit,
        patch(
            "anime_game_afk.engine.device.Win32Controller",
            return_value=ctrl_mock,
        ),
    ):
        mock_toolkit.find_desktop_windows.return_value = [
            _fake_window("TestWindow")
        ]
        adapter.connect()

    # Store the mock for assertion convenience
    adapter._ctrl_mock = ctrl_mock  # type: ignore[attr-defined]
    return adapter


def test_connect_sets_connected_true(connected_adapter: DeviceAdapter) -> None:
    assert connected_adapter.connected


def test_connect_stores_actual_resolution(
    connected_adapter: DeviceAdapter,
) -> None:
    """actual_resolution must be populated from the controller after connect."""
    assert connected_adapter.actual_resolution == Resolution(1600, 900)


def test_disconnect_sets_connected_false(
    connected_adapter: DeviceAdapter,
) -> None:
    connected_adapter.disconnect()
    assert not connected_adapter.connected


def test_disconnect_resets_state(
    connected_adapter: DeviceAdapter,
) -> None:
    """After disconnect, actual_resolution must raise DeviceConnectionError."""
    connected_adapter.disconnect()
    with pytest.raises(DeviceConnectionError):
        _ = connected_adapter.actual_resolution


def test_connect_raises_when_window_missing() -> None:
    cfg = _make_config(window_title="Ghost")
    adapter = DeviceAdapter(cfg)

    with patch("anime_game_afk.engine.device.Toolkit") as mock_toolkit:
        mock_toolkit.find_desktop_windows.return_value = []
        with pytest.raises(WindowNotFoundError):
            adapter.connect()


def test_connect_raises_connection_error_on_controller_failure() -> None:
    cfg = _make_config()
    adapter = DeviceAdapter(cfg)

    with (
        patch("anime_game_afk.engine.device.Toolkit") as mock_toolkit,
        patch(
            "anime_game_afk.engine.device.Win32Controller",
            side_effect=RuntimeError("driver error"),
        ),
    ):
        mock_toolkit.find_desktop_windows.return_value = [
            _fake_window("TestWindow")
        ]
        with pytest.raises(DeviceConnectionError, match="driver error"):
            adapter.connect()


def test_connect_allows_non_16_9_aspect_ratio() -> None:
    """connect() must no longer reject windows that aren't 16:9.

    Since the screenshot pipeline auto-crops letterbox bars and normalizes
    to the design canvas, a non-16:9 window (e.g. 4:3) now connects and its
    screenshot is normalized to design_resolution (1280x720).
    """
    cfg = _make_config()
    adapter = DeviceAdapter(cfg)
    # 4:3 resolution
    ctrl_mock = _make_controller_mock(resolution=(1024, 768))

    with (
        patch("anime_game_afk.engine.device.Toolkit") as mock_toolkit,
        patch(
            "anime_game_afk.engine.device.Win32Controller",
            return_value=ctrl_mock,
        ),
    ):
        mock_toolkit.find_desktop_windows.return_value = [
            _fake_window("TestWindow")
        ]
        adapter.connect()  # must not raise
    assert adapter.connected

    # The 4:3 window is auto-cropped to a 16:9 viewport and normalized to
    # the design canvas (1280x720).
    img = adapter.screenshot()
    assert img.shape == (720, 1280, 3)


def test_connect_falls_back_when_preferred_screencap_reports_zero_resolution() -> None:
    """A 0x0 resolution from the preferred screencap method (e.g. FramePool
    failing its D3D11 device creation under RDP / sandbox / no-GPU sessions)
    must trigger the DXGI/GDI fallback chain instead of being accepted as a
    "successful" connection.

    Regression for the bug where ``_finish_connection`` never validated the
    captured resolution, so a dead FramePool produced ``resolution=0x0``, every
    later ``screenshot()`` died with "Failed to get cached image", and the
    fallback chain never ran.
    """
    from maa.define import MaaWin32ScreencapMethodEnum

    cfg = DeviceConfig(
        window_title="TestWindow",
        screencap_method=MaaWin32ScreencapMethodEnum.FramePool,
        mouse_method=256,
        keyboard_method=256,
    )
    adapter = DeviceAdapter(cfg)

    def factory(
        hwnd=None,
        screencap_method=None,
        mouse_method=None,
        keyboard_method=None,
        **kwargs: Any,
    ) -> MagicMock:
        # FramePool → dead (0x0, simulates D3D11 failure); any other method →
        # working (1920x1080).
        if screencap_method == MaaWin32ScreencapMethodEnum.FramePool:
            return _make_controller_mock(resolution=(0, 0))
        return _make_controller_mock(resolution=(1920, 1080))

    with (
        patch("anime_game_afk.engine.device.Toolkit") as mock_toolkit,
        patch(
            "anime_game_afk.engine.device.Win32Controller",
            side_effect=factory,
        ) as mock_ctrl,
    ):
        mock_toolkit.find_desktop_windows.return_value = [
            _fake_window("TestWindow")
        ]
        adapter.connect()

    assert adapter.connected
    assert adapter.actual_resolution == Resolution(1920, 1080)
    # Fallback chain must have been exercised: preferred tried first, then a
    # working method. (Before the fix only the preferred was tried and 0x0 was
    # wrongly accepted as success.)
    assert mock_ctrl.call_count >= 2


def test_connect_raises_when_all_screencap_methods_report_zero_resolution() -> None:
    """Regression: a 0x0 resolution must NOT be accepted as a successful
    connection. If every method in the fallback chain reports 0x0, connect()
    must raise DeviceConnectionError and exhaust the whole chain.
    """
    cfg = DeviceConfig(
        window_title="TestWindow",
        screencap_method=4,
        mouse_method=256,
        keyboard_method=256,
    )
    adapter = DeviceAdapter(cfg)

    with (
        patch("anime_game_afk.engine.device.Toolkit") as mock_toolkit,
        patch(
            "anime_game_afk.engine.device.Win32Controller",
            return_value=_make_controller_mock(resolution=(0, 0)),
        ) as mock_ctrl,
    ):
        mock_toolkit.find_desktop_windows.return_value = [
            _fake_window("TestWindow")
        ]
        with pytest.raises(DeviceConnectionError):
            adapter.connect()

    # Every method in the fallback chain must have been attempted (before the
    # fix only the preferred was tried, then silently "succeeded" with 0x0).
    assert mock_ctrl.call_count >= 2


def test_screenshot_normalizes_16_10_window_with_letterbox() -> None:
    """A 2560x1600 (16:10) window running a 16:9 game normalizes to 1280x720.

    The window carries black letterbox bars top/bottom; the game viewport is
    the centered 16:9 region. After auto-crop + normalize, the output must be
    the design canvas and the game content must survive at the expected place.
    """
    raw_w, raw_h = 2560, 1600
    img = np.zeros((raw_h, raw_w, 3), dtype=np.uint8)
    game_h = int(raw_w / (1280 / 720))  # 1440
    y0 = (raw_h - game_h) // 2            # 80
    img[y0 : y0 + game_h, :, :] = 128     # grey game region
    mx, my = raw_w // 2, y0 + game_h // 2  # (1280, 800) — game center
    img[my - 30 : my + 30, mx - 30 : mx + 30, :] = 255  # white marker

    cfg = _make_config()
    adapter = DeviceAdapter(cfg)
    ctrl_mock = _make_controller_mock(
        resolution=(raw_w, raw_h), screencap_img=img
    )
    with (
        patch("anime_game_afk.engine.device.Toolkit") as mock_toolkit,
        patch(
            "anime_game_afk.engine.device.Win32Controller",
            return_value=ctrl_mock,
        ),
    ):
        mock_toolkit.find_desktop_windows.return_value = [
            _fake_window("TestWindow")
        ]
        adapter.connect()
        out = adapter.screenshot()

    assert out.shape == (720, 1280, 3)
    # White marker must land near the centre of the normalized canvas.
    marker_patch = out[350:370, 630:650]
    assert marker_patch.mean() > 200


def test_click_maps_through_viewport_crop_for_16_10_window() -> None:
    """Regression: on a 16:10 window running a 16:9 game, click(fx, fy) must
    map fractional coords into the cropped 16:9 game viewport, not the full
    window.

    Without this, clicks land inside the top/bottom letterbox bars or are
    vertically shifted, so popup-dismiss / navigation clicks miss and the tool
    loops clicking the same (wrong) spot — exactly the "keeps clicking the
    login-page position" symptom at 2560x1600.

    Builds a 2560x1600 capture with black letterbox bars (top/bottom 80px) so
    auto_viewport detects the centered 16:9 viewport (0, 80, 2560, 1440).
    """
    raw_w, raw_h = 2560, 1600
    img = np.zeros((raw_h, raw_w, 3), dtype=np.uint8)
    game_h = int(raw_w / (1280 / 720))  # 1440
    y0 = (raw_h - game_h) // 2            # 80
    img[y0 : y0 + game_h, :, :] = 128     # grey game region (bars stay black)

    cfg = _make_config()
    adapter = DeviceAdapter(cfg)
    ctrl_mock = _make_controller_mock(
        resolution=(raw_w, raw_h), screencap_img=img
    )
    with (
        patch("anime_game_afk.engine.device.Toolkit") as mock_toolkit,
        patch(
            "anime_game_afk.engine.device.Win32Controller",
            return_value=ctrl_mock,
        ),
    ):
        mock_toolkit.find_desktop_windows.return_value = [
            _fake_window("TestWindow")
        ]
        adapter.connect()

    # Fractional coords are relative to the cropped viewport (0, 80, 2560, 1440).
    adapter.click(0.0, 0.0)
    adapter.click(1.0, 1.0)
    adapter.click(0.5, 0.5)
    calls = ctrl_mock.post_click.call_args_list
    assert calls[0] == call(0, 80)        # viewport top-left
    assert calls[1] == call(2560, 1520)   # viewport bottom-right
    assert calls[2] == call(1280, 800)    # viewport center


def test_auto_viewport_skips_crop_when_game_full_bleed_no_bars() -> None:
    """Regression: a 2560x1600 window whose game fills the frame with NO
    letterbox bars must NOT be blind-cropped to 16:9.

    A 16:10 game rendered full-bleed on a 16:10 display has no bars. The old
    geometry-only heuristic cropped (0, 80, 2560, 1440), slicing off real game
    content (top/bottom 80px) and breaking template matching — the root cause
    of "keeps clicking the login-page position" at 2560x1600 with no bars.
    Now we verify the bars are actually dark; with none present we keep the
    whole window and warn instead of mis-cropping.
    """
    raw_w, raw_h = 2560, 1600
    img = np.full((raw_h, raw_w, 3), 128, dtype=np.uint8)  # full-bleed, no bars

    cfg = _make_config()
    adapter = DeviceAdapter(cfg)
    ctrl_mock = _make_controller_mock(resolution=(raw_w, raw_h), screencap_img=img)
    with (
        patch("anime_game_afk.engine.device.Toolkit") as mock_toolkit,
        patch("anime_game_afk.engine.device.Win32Controller", return_value=ctrl_mock),
    ):
        mock_toolkit.find_desktop_windows.return_value = [_fake_window("TestWindow")]
        adapter.connect()

    # No viewport crop — whole window is the game (no bars to remove).
    assert adapter._viewport_crop is None
    # click() maps into the whole window, not a 16:9 sub-rect.
    adapter.click(0.0, 0.0)
    adapter.click(1.0, 1.0)
    calls = ctrl_mock.post_click.call_args_list
    assert calls[0] == call(0, 0)
    assert calls[1] == call(2560, 1600)


# ---------------------------------------------------------------------------
# Coordinate scaling
# ---------------------------------------------------------------------------


def test_click_fractional_coords() -> None:
    """click(fx, fy) must convert fractional coords to actual pixels."""
    cfg = _make_config()
    adapter = DeviceAdapter(cfg)
    ctrl_mock = _make_controller_mock(resolution=(1600, 900))

    with (
        patch("anime_game_afk.engine.device.Toolkit") as mock_toolkit,
        patch(
            "anime_game_afk.engine.device.Win32Controller",
            return_value=ctrl_mock,
        ),
    ):
        mock_toolkit.find_desktop_windows.return_value = [
            _fake_window("TestWindow")
        ]
        adapter.connect()
        adapter.click(0.25, 0.5)

    # 0.25 * 1600 = 400, 0.5 * 900 = 450
    ctrl_mock.post_click.assert_called_once_with(400, 450)


def test_click_center() -> None:
    """click(0.5, 0.5) must map to the center of the actual resolution."""
    cfg = _make_config()
    adapter = DeviceAdapter(cfg)
    ctrl_mock = _make_controller_mock(resolution=(1920, 1080))

    with (
        patch("anime_game_afk.engine.device.Toolkit") as mock_toolkit,
        patch(
            "anime_game_afk.engine.device.Win32Controller",
            return_value=ctrl_mock,
        ),
    ):
        mock_toolkit.find_desktop_windows.return_value = [
            _fake_window("TestWindow")
        ]
        adapter.connect()
        adapter.click(0.5, 0.5)

    # 0.5 * 1920 = 960, 0.5 * 1080 = 540
    ctrl_mock.post_click.assert_called_once_with(960, 540)


def test_swipe_fractional_coords() -> None:
    """Swipe endpoints must be converted from fractional to actual pixels."""
    cfg = _make_config()
    adapter = DeviceAdapter(cfg)
    ctrl_mock = _make_controller_mock(resolution=(1600, 900))

    with (
        patch("anime_game_afk.engine.device.Toolkit") as mock_toolkit,
        patch(
            "anime_game_afk.engine.device.Win32Controller",
            return_value=ctrl_mock,
        ),
    ):
        mock_toolkit.find_desktop_windows.return_value = [
            _fake_window("TestWindow")
        ]
        adapter.connect()
        adapter.swipe(0.0, 0.0, 0.5, 0.25, duration=300)

    # 0*1600=0, 0*900=0, 0.5*1600=800, 0.25*900=225
    ctrl_mock.post_swipe.assert_called_once_with(0, 0, 800, 225, 300)


# ---------------------------------------------------------------------------
# Screenshot
# ---------------------------------------------------------------------------


def test_screenshot_scales_down_to_max_height() -> None:
    """screenshot() must scale down proportionally when height > MAX_HEIGHT (720)."""
    actual_w, actual_h = 3200, 1800  # taller than 720

    actual_img = np.zeros((actual_h, actual_w, 3), dtype=np.uint8)
    cfg = _make_config()
    adapter = DeviceAdapter(cfg)
    ctrl_mock = _make_controller_mock(
        resolution=(actual_w, actual_h), screencap_img=actual_img
    )

    with (
        patch("anime_game_afk.engine.device.Toolkit") as mock_toolkit,
        patch(
            "anime_game_afk.engine.device.Win32Controller",
            return_value=ctrl_mock,
        ),
    ):
        mock_toolkit.find_desktop_windows.return_value = [
            _fake_window("TestWindow")
        ]
        adapter.connect()
        img = adapter.screenshot()

    # scale = 720 / 1800 = 0.4, new_w = int(3200 * 0.4) = 1280
    assert img.shape == (720, 1280, 3)


def test_screenshot_no_resize_when_height_within_max() -> None:
    """screenshot() must NOT resize when height ≤ MAX_HEIGHT (720)."""
    img_data = np.ones((720, 1280, 3), dtype=np.uint8) * 127
    cfg = _make_config()
    adapter = DeviceAdapter(cfg)
    ctrl_mock = _make_controller_mock(
        resolution=(1280, 720), screencap_img=img_data
    )

    with (
        patch("anime_game_afk.engine.device.Toolkit") as mock_toolkit,
        patch(
            "anime_game_afk.engine.device.Win32Controller",
            return_value=ctrl_mock,
        ),
    ):
        mock_toolkit.find_desktop_windows.return_value = [
            _fake_window("TestWindow")
        ]
        adapter.connect()
        img = adapter.screenshot()

    assert img.shape == (720, 1280, 3)
    # Pixel values must be preserved (no resize distortion)
    np.testing.assert_array_equal(img, img_data)


def test_screenshot_raw_returns_actual_resolution_image() -> None:
    """screenshot_raw() must return the image without resizing."""
    actual_w, actual_h = 3200, 1800
    actual_img = np.zeros((actual_h, actual_w, 3), dtype=np.uint8)
    cfg = _make_config()
    adapter = DeviceAdapter(cfg)
    ctrl_mock = _make_controller_mock(
        resolution=(actual_w, actual_h), screencap_img=actual_img
    )

    with (
        patch("anime_game_afk.engine.device.Toolkit") as mock_toolkit,
        patch(
            "anime_game_afk.engine.device.Win32Controller",
            return_value=ctrl_mock,
        ),
    ):
        mock_toolkit.find_desktop_windows.return_value = [
            _fake_window("TestWindow")
        ]
        adapter.connect()
        img = adapter.screenshot_raw()

    assert img.shape == (actual_h, actual_w, 3)


def test_screenshot_raises_when_get_returns_none() -> None:
    cfg = _make_config()
    adapter = DeviceAdapter(cfg)
    ctrl_mock = _make_controller_mock()

    with (
        patch("anime_game_afk.engine.device.Toolkit") as mock_toolkit,
        patch(
            "anime_game_afk.engine.device.Win32Controller",
            return_value=ctrl_mock,
        ),
    ):
        mock_toolkit.find_desktop_windows.return_value = [
            _fake_window("TestWindow")
        ]
        # connect() succeeds with a valid screencap (the default mock image).
        adapter.connect()

    # Now swap in a None-returning screencap so screenshot() must raise.
    screencap_job = MagicMock()
    screencap_job.wait.return_value = screencap_job
    screencap_job.get.return_value = None
    ctrl_mock.post_screencap.return_value = screencap_job

    with pytest.raises(ScreenshotError):
        adapter.screenshot()


# ---------------------------------------------------------------------------
# press_key / hold_key
# ---------------------------------------------------------------------------


def test_press_key_delegation(connected_adapter: DeviceAdapter) -> None:
    """press_key must forward the vk_code to the controller."""
    connected_adapter.press_key(0x0D)  # VK_RETURN
    connected_adapter._ctrl_mock.post_press_key.assert_called_once_with(0x0D)  # type: ignore[attr-defined]


def test_hold_key_uses_keydown_keyup(
    connected_adapter: DeviceAdapter,
) -> None:
    """hold_key sends a single key_down, sleeps, then sends key_up."""
    with patch("anime_game_afk.engine.device.time") as mock_time:
        mock_time.sleep = MagicMock()
        connected_adapter.hold_key(0x57, 0.3)  # VK_W, 0.3s

    ctrl = connected_adapter._ctrl_mock  # type: ignore[attr-defined]
    ctrl.post_key_down.assert_called_once_with(0x57)
    ctrl.post_key_up.assert_called_once_with(0x57)
    mock_time.sleep.assert_called_once_with(0.3)


def test_hold_key_sends_keyup_even_on_sleep_exception(
    connected_adapter: DeviceAdapter,
) -> None:
    """If time.sleep raises, key_up must still be sent (try/finally guarantee)."""
    with patch("anime_game_afk.engine.device.time") as mock_time:
        mock_time.sleep = MagicMock(side_effect=KeyboardInterrupt())
        with pytest.raises(KeyboardInterrupt):
            connected_adapter.hold_key(0x57, 0.3)

    ctrl = connected_adapter._ctrl_mock  # type: ignore[attr-defined]
    ctrl.post_key_down.assert_called_once_with(0x57)
    ctrl.post_key_up.assert_called_once_with(0x57)


def test_release_all_held_keys_sends_keyup_for_recovery_set(
    connected_adapter: DeviceAdapter,
) -> None:
    """release_all_held_keys sends key_up for every key in _RECOVERY_VK_CODES."""
    connected_adapter.release_all_held_keys()
    ctrl = connected_adapter._ctrl_mock  # type: ignore[attr-defined]
    actual_keys = [c.args[0] for c in ctrl.post_key_up.call_args_list]
    assert actual_keys == list(DeviceAdapter._RECOVERY_VK_CODES)


def test_release_all_held_keys_no_controller_is_safe() -> None:
    """release_all_held_keys is a no-op when not connected (no exception)."""
    from maa.define import (
        MaaWin32InputMethodEnum,
        MaaWin32ScreencapMethodEnum,
    )

    from anime_game_afk.config.models import GameConfig
    cfg = GameConfig(
        name="X",
        window_title="X",
        resource_path=__file__,
        screencap_method=MaaWin32ScreencapMethodEnum.FramePool,
        mouse_method=MaaWin32InputMethodEnum.SendMessage,
        keyboard_method=MaaWin32InputMethodEnum.SendMessage,
    )
    adapter = DeviceAdapter(cfg.to_device_config())
    # Should not raise
    adapter.release_all_held_keys()


def test_disconnect_calls_release_all_held_keys(
    connected_adapter: DeviceAdapter,
) -> None:
    """disconnect must release any held keys before tearing down the controller."""
    ctrl = connected_adapter._ctrl_mock  # type: ignore[attr-defined]
    connected_adapter.disconnect()
    # Should have sent at least key_up for every recovery key.
    assert ctrl.post_key_up.call_count >= len(DeviceAdapter._RECOVERY_VK_CODES)


# ---------------------------------------------------------------------------
# _ensure_connected guard
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method_call",
    [
        lambda d: d.screenshot(),
        lambda d: d.screenshot_raw(),
        lambda d: d.click(0, 0),
        lambda d: d.swipe(0, 0, 1, 1),
        lambda d: d.press_key(0),
        lambda d: d.hold_key(0, 0.1),
    ],
)
def test_operations_raise_when_not_connected(
    method_call: Any,
) -> None:
    """All I/O methods must raise DeviceConnectionError when not connected."""
    cfg = _make_config()
    adapter = DeviceAdapter(cfg)
    with pytest.raises(DeviceConnectionError):
        method_call(adapter)
