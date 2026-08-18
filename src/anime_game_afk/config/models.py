"""配置数据模型"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from maa.define import MaaWin32InputMethodEnum, MaaWin32ScreencapMethodEnum

from anime_game_afk.core.types import DeviceConfig


@dataclass(frozen=True)
class GameConfig:
    """游戏配置"""

    name: str
    window_title: str
    resource_path: Path
    screencap_method: int = MaaWin32ScreencapMethodEnum.Background
    mouse_method: int = MaaWin32InputMethodEnum.SendMessage
    keyboard_method: int = MaaWin32InputMethodEnum.SendMessage
    # Resolution the screenshot is normalized to (coordinate reference frame
    # for vision). Defaults to 1280x720 (16:9); content packs may override.
    design_resolution: tuple[int, int] = (1280, 720)
    # Optional fractional viewport (fx, fy, fw, fh) of the game area within
    # the window. None = whole window (or auto letterbox detection).
    viewport: tuple[float, float, float, float] | None = None

    def to_device_config(
        self,
        game_exe_path: str = "",
    ) -> DeviceConfig:
        """Convert to a :class:`DeviceConfig` for :class:`DeviceAdapter`.

        Args:
            game_exe_path: Path to game executable (used for auto-launch).
        """
        return DeviceConfig(
            window_title=self.window_title,
            screencap_method=self.screencap_method,
            mouse_method=self.mouse_method,
            keyboard_method=self.keyboard_method,
            game_exe_path=game_exe_path,
            design_resolution=self.design_resolution,
            viewport=self.viewport,
        )
