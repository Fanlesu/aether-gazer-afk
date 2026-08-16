"""Shared game-device bootstrap.

Both the GUI subprocess worker (``ui/worker.py``) and the headless scheduler
runner (``runtime/headless.py``) need to bring the game device up before they
can run a pipeline: resolve the game executable, make sure the process is
running (launching it if not), then connect a ``DeviceAdapter``. This module
is the single home for that bring-up sequence so the two entry points can't
drift apart.

``game_was_launched`` tells the caller whether *we* started the game. When the
game was already running the caller usually skips the "navigate to hub" step;
when we launched it cold the caller needs to reach the hub first.
"""
from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from anime_game_afk.games.content_pack import get_content_pack
from anime_game_afk.runtime.logger import get_logger

if TYPE_CHECKING:
    from anime_game_afk.config.user_config import UserConfig
    from anime_game_afk.core.device import DeviceAdapter


class BootstrapError(RuntimeError):
    """Raised when the game cannot be located, launched, or connected."""


def _game_process_running() -> bool:
    """Return True if the AetherGazer process is present in the task list."""
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq AetherGazer.exe", "/NH"],
            capture_output=True, text=True, timeout=5, creationflags=flags,
        )
        return "AetherGazer.exe" in result.stdout
    except Exception:
        return False


def _status(
    status_cb: Callable[[str], None] | None,
    msg: str,
    logger,
) -> None:
    """Emit a human-readable status update via ``status_cb`` or the logger."""
    if status_cb is not None:
        status_cb(msg)
    else:
        logger.info(msg)


def bootstrap_device(
    user_cfg: UserConfig,
    *,
    game_id: str = "aether_gazer",
    logger=None,
    status_cb: Callable[[str], None] | None = None,
) -> tuple[DeviceAdapter, bool]:
    """Locate, launch if needed, and connect to the game.

    Args:
        user_cfg: Loaded user configuration (exe path, launch timeout, ...).
        game_id: Game identifier used for config lookups.
        logger: Logger used for status lines when ``status_cb`` is ``None``.
        status_cb: Optional callable ``(msg: str) -> None`` for status updates
            (the worker uses this to push JSON lines to its parent GUI).

    Returns:
        ``(device, game_was_launched)`` — a connected ``DeviceAdapter`` and a
        flag that is ``True`` only when this call started the game.

    Raises:
        BootstrapError: If the exe can't be found, the launch times out, or the
            device fails to connect. Callers translate this into their own
            failure reporting.
    """
    log = logger or get_logger("bootstrap")

    # --- Resolve game exe (with auto-discovery fallback) -------------------
    pack = get_content_pack(game_id)
    window_title = user_cfg.window_title(game_id) or pack.window_title
    exe_path = user_cfg.game_exe_path(game_id)
    if not exe_path or not Path(exe_path).exists():
        found = pack.find_game(search_drives=user_cfg.search_drives())
        game_exe = found.get("game_exe")
        launcher = found.get("launcher")
        if game_exe:
            user_cfg.set_game_exe_path(game_id, game_exe)
            if launcher:
                user_cfg.set_launcher_path(game_id, launcher)
            user_cfg.save()
            exe_path = game_exe

    # --- Ensure the game process is up --------------------------------------
    game_was_launched = False
    _status(status_cb, "正在查找游戏窗口...", log)
    if not _game_process_running():
        _status(status_cb, "游戏未运行，正在启动...", log)
        if not exe_path:
            raise BootstrapError("找不到游戏，请在设置中指定游戏路径")
        from anime_game_afk.core.game_launcher import GameLauncher

        launcher = GameLauncher(
            exe_path=exe_path,
            window_title=window_title,
            process_name=Path(exe_path).name,
        )
        timeout = user_cfg.launch_timeout(game_id)
        if not launcher.ensure_running(timeout=timeout):
            raise BootstrapError(f"启动游戏超时 ({timeout}s)")
        game_was_launched = True

    # --- Connect to the game window -----------------------------------------
    _status(status_cb, "正在连接游戏...", log)
    from anime_game_afk.core.device import DeviceAdapter

    device_config = pack.config.to_device_config(game_exe_path=exe_path or "")
    device = DeviceAdapter(config=device_config)
    try:
        device.connect()
    except Exception as exc:  # noqa: BLE001
        raise BootstrapError(f"连接失败: {exc}")
    if not device.connected:
        raise BootstrapError("无法连接到游戏窗口")
    return device, game_was_launched
