# core/

Game-agnostic infrastructure utilities. Shared by all games; no device control, no game logic.

> Note: the device adapter (`device.py`) and game launcher (`game_launcher.py`) were moved to the `engine/` package.

## Files

| File | Purpose |
|------|---------|
| `types.py` | Shared types: Point, Rect, Resolution, DeviceConfig |
| `errors.py` | Exception hierarchy: AutomationError, DeviceError, DeviceConnectionError, etc. |
| `game_finder.py` | Locate the game window / executable |
| `hotkey_listener.py` | Global hotkey registration |
| `input_guard.py` | Serialize / guard input actions |
| `job_object.py` | Windows Job Object for child-process lifecycle management |
| `notifier.py` | Desktop notifications (toast) |
| `virtual_desktop.py` | Isolated virtual desktop for headless runs |

## Key Types

- `DeviceConfig` — window_title, screencap/mouse/keyboard methods, design_resolution
- `DeviceConnectionError` — replaces old `ConnectionError` to avoid shadowing Python builtin

## Layer Rule

This package is game-agnostic infrastructure. It may depend on MaaFramework (Layer 0) and other shared utilities, but never on game-specific code (Layers 4-8) or config that is game-bound.
