"""Content-pack registry — the single seam between the game-agnostic
engine/runtime/UI and the game-specific adapters.

A :class:`ContentPack` aggregates everything that is specific to one
supported game: its device config, its process-registry builder, its
game finder, and its default pipeline id.  Every entry point (GUI,
worker subprocess, headless runner, CLI launcher, scheduler) resolves a
pack via :func:`get_content_pack` instead of importing game modules
directly.  Adding a second game later means registering one more pack —
no edits to the generic layers.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from anime_game_afk.config.models import GameConfig
from anime_game_afk.games.aether_gazer.config import AETHER_GAZER_CONFIG

if TYPE_CHECKING:
    from anime_game_afk.games.aether_gazer.orchestrator.pipeline import (
        ProcessRegistry,
    )


@dataclass(frozen=True)
class ContentPack:
    """All game-specific knowledge for one supported game.

    The generic engine/runtime/UI layers never import a game module
    directly; they go through a pack obtained from :func:`get_content_pack`
    and call the bundled callbacks.  This keeps those layers open for a
    second game while the AetherGazer specifics stay in one place.
    """

    game_id: str
    window_title: str
    game_exe_name: str
    config: GameConfig
    default_pipeline_id: str
    build_registry: Callable[[], ProcessRegistry]
    find_game: Callable[..., dict[str, str | None]]


def _aether_gazer_find(**kwargs) -> dict[str, str | None]:
    """Route to the (possibly test-patched) module-level game finder.

    We re-fetch ``find_aether_gazer`` from its module at call time so that
    ``patch("anime_game_afk.core.game_finder.find_aether_gazer")`` in tests
    still takes effect after the call site moved behind the pack seam.
    """
    from anime_game_afk.core import game_finder

    return game_finder.find_aether_gazer(**kwargs)


_REGISTERED: dict[str, ContentPack] = {}


def _register_default_packs() -> None:
    # Imported lazily to avoid a circular import at module load time:
    # ``games/__init__.py`` (and transitively the engine package) pulls in
    # this module, while ``registry`` -> ``daily_routine`` -> the engine would
    # otherwise form a cycle back into this module.
    from anime_game_afk.games.aether_gazer.registry import build_registry

    _REGISTERED["aether_gazer"] = ContentPack(
        game_id="aether_gazer",
        window_title=AETHER_GAZER_CONFIG.window_title,
        game_exe_name="AetherGazer.exe",
        config=AETHER_GAZER_CONFIG,
        default_pipeline_id="daily_routine",
        build_registry=build_registry,
        find_game=_aether_gazer_find,
    )


def get_content_pack(game_id: str = "aether_gazer") -> ContentPack:
    """Return the registered content pack for ``game_id`` (default aether_gazer)."""
    if not _REGISTERED:
        _register_default_packs()
    pack = _REGISTERED.get(game_id)
    if pack is None:
        raise KeyError(f"Unknown game_id: {game_id!r}")
    return pack


def available_packs() -> list[str]:
    """Return the list of registered game ids."""
    if not _REGISTERED:
        _register_default_packs()
    return list(_REGISTERED)
