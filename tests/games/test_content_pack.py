"""Tests for the content-pack registry (games/content_pack.py).

Verifies that the single game-agnostic seam exposes the right game-specific
pieces and that the AetherGazer pack is the only registered one for now.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from anime_game_afk.games.content_pack import (
    available_packs,
    get_content_pack,
)


def test_aether_gazer_pack_is_registered():
    pack = get_content_pack("aether_gazer")
    assert pack.game_id == "aether_gazer"
    assert pack.default_pipeline_id == "daily_routine"
    assert pack.window_title == "AetherGazer"
    assert pack.game_exe_name == "AetherGazer.exe"


def test_default_pack_is_aether_gazer():
    assert get_content_pack().game_id == "aether_gazer"


def test_unknown_game_id_raises():
    with pytest.raises(KeyError):
        get_content_pack("does_not_exist")


def test_only_aether_gazer_registered_for_now():
    assert available_packs() == ["aether_gazer"]


def test_build_registry_exposes_daily_routine():
    pack = get_content_pack("aether_gazer")
    registry = pack.build_registry()
    assert "daily_routine" in registry.available()
    assert "duowei_challenge" in registry.available()
    assert "lizhan_loop" in registry.available()


def test_find_game_routes_to_finder():
    pack = get_content_pack("aether_gazer")
    with patch(
        "anime_game_afk.core.game_finder.find_aether_gazer",
        return_value={"game_exe": "X:/AetherGazer.exe"},
    ) as m_find:
        result = pack.find_game(search_drives=["Z:"])
    m_find.assert_called_once_with(search_drives=["Z:"])
    assert result["game_exe"] == "X:/AetherGazer.exe"
