"""Tests for the shared game-device bootstrap (runtime/bootstrap.py).

These exercise ``bootstrap_device`` with fully mocked device/game deps so the
bring-up logic can be verified without a live game. They mirror the pattern
used by the worker and headless entry points that now delegate to it.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from anime_game_afk.runtime.bootstrap import (
    BootstrapError,
    bootstrap_device,
    _game_process_running,
)


def _user_cfg(exe_path: str | None) -> MagicMock:
    cfg = MagicMock()
    cfg.game_exe_path.return_value = exe_path
    cfg.window_title.return_value = "AetherGazer"
    cfg.search_drives.return_value = []
    cfg.launch_timeout.return_value = 30
    cfg.set_game_exe_path.return_value = None
    cfg.set_launcher_path.return_value = None
    cfg.save.return_value = None
    return cfg


def _patch_deps(m_find, m_launcher_cls, m_dev_cls, m_conf, *, connected=True):
    dev = MagicMock()
    dev.connected = connected
    m_dev_cls.return_value = dev
    m_conf.to_device_config.return_value = "devcfg"
    launcher = MagicMock()
    launcher.ensure_running.return_value = True
    m_launcher_cls.return_value = launcher
    m_find.return_value = {}
    return dev, launcher


def test_launch_when_not_running_sets_flag():
    cfg = _user_cfg("C:/game/AetherGazer.exe")
    with patch(
        "anime_game_afk.runtime.bootstrap._game_process_running",
        return_value=False,
    ), patch("anime_game_afk.core.game_finder.find_aether_gazer") as m_find, \
         patch("anime_game_afk.core.game_launcher.GameLauncher") as m_launcher, \
         patch("anime_game_afk.core.device.DeviceAdapter") as m_dev, \
         patch(
             "anime_game_afk.games.aether_gazer.config.AETHER_GAZER_CONFIG"
         ) as m_conf:
        _patch_deps(m_find, m_launcher, m_dev, m_conf)
        device, launched = bootstrap_device(cfg)
    assert launched is True
    m_launcher.return_value.ensure_running.assert_called_once()
    m_dev.return_value.connect.assert_called_once()
    assert device is not None


def test_skip_launch_when_already_running():
    cfg = _user_cfg("C:/game/AetherGazer.exe")
    with patch(
        "anime_game_afk.runtime.bootstrap._game_process_running",
        return_value=True,
    ), patch("anime_game_afk.core.game_finder.find_aether_gazer") as m_find, \
         patch("anime_game_afk.core.game_launcher.GameLauncher") as m_launcher, \
         patch("anime_game_afk.core.device.DeviceAdapter") as m_dev, \
         patch(
             "anime_game_afk.games.aether_gazer.config.AETHER_GAZER_CONFIG"
         ) as m_conf:
        _patch_deps(m_find, m_launcher, m_dev, m_conf)
        _, launched = bootstrap_device(cfg)
    assert launched is False
    m_launcher.assert_not_called()


def test_connect_failure_raises():
    cfg = _user_cfg("C:/game/AetherGazer.exe")
    with patch(
        "anime_game_afk.runtime.bootstrap._game_process_running",
        return_value=False,
    ), patch("anime_game_afk.core.game_finder.find_aether_gazer") as m_find, \
         patch("anime_game_afk.core.game_launcher.GameLauncher") as m_launcher, \
         patch("anime_game_afk.core.device.DeviceAdapter") as m_dev, \
         patch(
             "anime_game_afk.games.aether_gazer.config.AETHER_GAZER_CONFIG"
         ) as m_conf:
        # Device reports not connected after connect()
        _patch_deps(m_find, m_launcher, m_dev, m_conf, connected=False)
        try:
            bootstrap_device(cfg)
            assert False, "expected BootstrapError"
        except BootstrapError as exc:
            assert "无法连接" in str(exc)


def test_missing_exe_raises():
    cfg = _user_cfg(None)
    with patch(
        "anime_game_afk.runtime.bootstrap._game_process_running",
        return_value=False,
    ), patch(
        "anime_game_afk.core.game_finder.find_aether_gazer"
    ) as m_find, patch("anime_game_afk.core.game_launcher.GameLauncher"), \
         patch("anime_game_afk.core.device.DeviceAdapter"), \
         patch("anime_game_afk.games.aether_gazer.config.AETHER_GAZER_CONFIG"):
        # No exe on disk and auto-discovery finds nothing.
        m_find.return_value = {}
        try:
            bootstrap_device(cfg)
            assert False, "expected BootstrapError"
        except BootstrapError as exc:
            assert "找不到游戏" in str(exc)


def test_game_process_running_helper():
    # When tasklist lookup blows up we must not raise — just report False.
    with patch(
        "anime_game_afk.runtime.bootstrap.subprocess.run",
        side_effect=Exception("boom"),
    ):
        assert _game_process_running() is False
