# engine/

Game-agnostic automation engine — the heart of the framework, independent of any specific game.

## Files

| File | Purpose |
|------|---------|
| `device.py` | `DeviceAdapter` — screenshot, click, press_key, hold_key, swipe. The single point of contact with MaaFramework (`Win32Controller` + `Toolkit`). |
| `game_launcher.py` | Launch / locate the game executable and wait for the main window. |
| `workflow_engine.py` | `WorkflowEngine` — generic, data-driven task-level execution engine. Parses a plan of `PlanStep` / `PlanGroup` / `PlanItem` nodes and runs them with injected `resolve_condition` / `action_executor` callbacks. Game-agnostic. |
| `__init__.py` | Public API surface — re-exports `WorkflowEngine`, `PlanStep`, `PlanGroup`, `PlanItem`, `TaskParams`, `TaskMeta`. |

## Relationship to other layers

- `engine/device.py` wraps MaaFramework (Layer 0) — the only place that touches MaaFw controllers.
- `engine/workflow_engine.py` is consumed by game-specific `processes/` (Layer 7) via injected callbacks; it knows nothing about AetherGazer.
- Game-specific recognition (OpenCV / RapidOCR) and action orchestration live in the game packages, not here.

## Design notes

The engine is intentionally generic so the same code can drive multiple games. Game-specific steps and navigation are supplied through **content packs** (see `games/content_pack.py`), which register a `build_registry` + `default_pipeline_id`; the engine simply executes whatever plan the active content pack describes.
