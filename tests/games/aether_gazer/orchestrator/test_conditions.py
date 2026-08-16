"""Tests for the L2 condition resolver (orchestrator.conditions).

Mocks the red-dot check and OCR so no real vision/screenshot is needed;
the focus is the dispatch logic (type routing, all/any/not combinators,
value comparison, unknown-type fallback).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import numpy as np

from anime_game_afk.games.aether_gazer.orchestrator.conditions import (
    resolve_condition,
)
from anime_game_afk.games.aether_gazer.processes.base import ProcessContext


class _MockDevice:
    def screenshot(self) -> np.ndarray:
        return np.zeros((900, 1600, 3), dtype=np.uint8)


def _ctx(**state) -> ProcessContext:
    ctx = ProcessContext(device=_MockDevice(), config={})
    ctx.state.update(state)
    return ctx


async def test_reddot_condition_passes() -> None:
    fake = AsyncMock(return_value=type("R", (), {"passed": True})())
    with patch(
        "anime_game_afk.games.aether_gazer.orchestrator.conditions.RedDotCheck"
    ) as m_cls:
        m_cls.return_value.evaluate = fake
        ok = await resolve_condition(
            {"type": "reddot", "key": "mail"}, _ctx()
        )
    assert ok is True
    m_cls.assert_called_once()
    # key resolved to RED_DOTS["mail"] coords (fx, fy passed positionally)
    args, kwargs = m_cls.call_args
    assert len(args) == 2  # (fx, fy)
    assert kwargs.get("label") == "mail"


async def test_reddot_condition_fails() -> None:
    fake = AsyncMock(return_value=type("R", (), {"passed": False})())
    with patch(
        "anime_game_afk.games.aether_gazer.orchestrator.conditions.RedDotCheck"
    ) as m_cls:
        m_cls.return_value.evaluate = fake
        ok = await resolve_condition(
            {"type": "reddot", "fx": 0.5, "fy": 0.5}, _ctx()
        )
    assert ok is False


async def test_ocr_condition_present() -> None:
    with patch(
        "anime_game_afk.games.aether_gazer.orchestrator.conditions.ocr_find"
    ) as m_ocr:
        m_ocr.return_value = type("T", (), {})()  # truthy found
        ok = await resolve_condition(
            {"type": "ocr", "text": "情报", "region": [0.1, 0.1, 0.3, 0.2]},
            _ctx(),
        )
    assert ok is True
    m_ocr.assert_called_once()


async def test_ocr_condition_absent() -> None:
    with patch(
        "anime_game_afk.games.aether_gazer.orchestrator.conditions.ocr_find"
    ) as m_ocr:
        m_ocr.return_value = None
        ok = await resolve_condition(
            {"type": "ocr", "text": "不存在"}, _ctx()
        )
    assert ok is False


async def test_value_condition_compares_state() -> None:
    assert await resolve_condition(
        {"type": "value", "key": "stamina", "op": ">", "value": 100},
        _ctx(stamina=120),
    ) is True
    assert await resolve_condition(
        {"type": "value", "key": "stamina", "op": ">", "value": 100},
        _ctx(stamina=80),
    ) is False


async def test_value_condition_missing_key_false() -> None:
    assert await resolve_condition(
        {"type": "value", "key": "nonexistent", "op": "==", "value": 1},
        _ctx(),
    ) is False


async def test_combinators_all_any_not() -> None:
    # all: both true -> True
    assert await resolve_condition(
        {"type": "all", "conds": [{"type": "always"}, {"type": "always"}]},
        _ctx(),
    ) is True
    # any: one true -> True
    assert await resolve_condition(
        {"type": "any", "conds": [{"type": "never"}, {"type": "always"}]},
        _ctx(),
    ) is True
    # not: invert
    assert await resolve_condition(
        {"type": "not", "cond": {"type": "never"}}, _ctx()
    ) is True


async def test_unknown_type_resolves_truthy() -> None:
    # Unknown condition types must not block a run.
    assert await resolve_condition({"type": "frobnicate"}, _ctx()) is True
