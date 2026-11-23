"""Tests for tasks.activity_tasks -- JointDefenseSweep + InvitationRewardClaim.

Mock strategy: patch Op classes (ClickOp, ClickPxOp, PressKeyOp.run) at the
activity_tasks namespace, stub FindTextCheck so the reward-claim gate yields a
deterministic result without running real OCR on the mock (black) screenshot,
and stub JointDefenseSweep._ocr so the reward-collection helper reports that it
reached the 联防协议 detail page (the page just before hub).
"""
import asyncio
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np

from anime_game_afk.games.aether_gazer.checks.base import CheckResult
from anime_game_afk.games.aether_gazer.ops.base import OpResult
from anime_game_afk.games.aether_gazer.tasks.activity_tasks import (
    InvitationRewardClaim,
    JointDefenseSweep,
)
from anime_game_afk.games.aether_gazer.tasks.base import TaskContext


@dataclass
class MockDevice:
    click_log: list = field(default_factory=list)
    key_log: list = field(default_factory=list)
    swipe_log: list = field(default_factory=list)

    def screenshot(self) -> np.ndarray:
        return np.zeros((900, 1600, 3), dtype=np.uint8)

    def click(self, x: int, y: int) -> None:
        self.click_log.append((x, y))

    def press_key(self, vk_code: int) -> None:
        self.key_log.append(vk_code)

    def hold_key(self, vk_code: int, duration_s: float) -> None:
        pass

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration: int = 300) -> None:
        self.swipe_log.append((x1, y1, x2, y2))


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


_ACT = "anime_game_afk.games.aether_gazer.tasks.activity_tasks"
_CLICK = f"{_ACT}.ClickOp"
_CLICKPX = f"{_ACT}.ClickPxOp"
_PRESS_RUN = f"{_ACT}.PressKeyOp.run"
_FIND_TEXT = f"{_ACT}.FindTextCheck"


def _patch_find_text(passed: bool, region: tuple[int, int, int, int] | None = None):
    """Patch FindTextCheck at the activity namespace to force pass/fail.

    When *passed* is True, *region* (x, y, w, h) is wrapped as the OCR hit
    so the reward-claim step can compute and click its center.
    """

    class _FakeText:
        def __init__(self, *args, **kwargs):
            pass

        async def evaluate(self, ctx: TaskContext) -> CheckResult:
            if not passed:
                return CheckResult(passed=False, message="'一键领取' not found")
            x, y, w, h = region or (1400, 760, 100, 40)
            hit = MagicMock()
            hit.region.x = x
            hit.region.y = y
            hit.region.w = w
            hit.region.h = h
            return CheckResult(passed=True, data=hit, message="found '一键领取'")

    return patch(_FIND_TEXT, _FakeText)


def _stub_at_detail_page(task: JointDefenseSweep) -> None:
    """Make _ocr report the 联防协议 detail page reached (前往挑战 visible)."""
    fake_scan = MagicMock()
    fake_scan.result.has = lambda target: target == "前往挑战"
    task._ocr = AsyncMock(return_value=fake_scan)


def _spy_clicks():
    """Return (clicks, SpyOp) recording (x, y) for ClickOp and (px, py) for ClickPxOp."""
    clicks: list = []

    class _SpyOp:
        def __init__(self, *args, **kwargs):
            if "px" in kwargs or "py" in kwargs:
                clicks.append(("px", kwargs.get("px"), kwargs.get("py")))
            else:
                clicks.append(("op", kwargs.get("x"), kwargs.get("y")))

        async def run(self, ctx: TaskContext) -> OpResult:
            return OpResult(success=True)

    return clicks, _SpyOp


# -- JointDefenseSweep -- metadata --

def test_joint_defense_name():
    assert JointDefenseSweep.name == "joint_defense_sweep"


def test_joint_defense_can_run():
    device = MockDevice()
    ctx = TaskContext(device=device)
    assert _run(JointDefenseSweep().can_run(ctx)) is True


# -- JointDefenseSweep -- reward-claim gate (Step 9, 一键领取) --
# The claim is gated on OCR-detecting the "一键领取" button itself (not a
# fragile red-dot badge): button present => claim at the detected location;
# button absent => skip. See _collect_joint_defense_rewards.

def test_joint_defense_claims_rewards_when_button_present():
    """'一键领取' detected -> claim click lands on the OCR'd button center."""
    device = MockDevice()
    ctx = TaskContext(device=device)
    task = JointDefenseSweep()
    _stub_at_detail_page(task)
    clicks, spy = _spy_clicks()
    with (
        patch(_CLICK, spy),
        patch(_CLICKPX, spy),
        patch(_PRESS_RUN, AsyncMock(return_value=OpResult(success=True))),
        _patch_find_text(True, region=(1400, 760, 100, 40)),
    ):
        _run(task._collect_joint_defense_rewards(ctx, None))

    # Center of the mocked OCR rect (1400,760,100,40) -> (1450, 780).
    assert ("px", 1450, 780) in clicks


def test_joint_defense_skips_rewards_when_button_absent():
    """'一键领取' not detected -> claim skipped, but nav still ran."""
    device = MockDevice()
    ctx = TaskContext(device=device)
    task = JointDefenseSweep()
    _stub_at_detail_page(task)
    clicks, spy = _spy_clicks()
    with (
        patch(_CLICK, spy),
        patch(_CLICKPX, spy),
        patch(_PRESS_RUN, AsyncMock(return_value=OpResult(success=True))),
        _patch_find_text(False),
    ):
        _run(task._collect_joint_defense_rewards(ctx, None))

    # No pixel claim click should have happened.
    assert not any(kind == "px" for kind, _, _ in clicks)
    # Back-navigation click (0.022,0.039) still ran to reach the detail page.
    assert ("op", 0.022, 0.039) in clicks


# -- InvitationRewardClaim -------------------------------------------------
# Flow per title: click title → 前往邀约 → 见闻 → 一键领取/领取 → back ×N
# to the activity page; after the last title return to hub. Per-title
# misses are skipped (event may be locked), but a page with NO titles at
# all is a navigation failure.

_TITLES = InvitationRewardClaim._TITLES
_ACTIVITY_PAGE = list(_TITLES)


def _fake_page(texts: list[str]):
    """Build a fake OcrScan-like object answering find/find_all/has."""
    def _item(t: str):
        return SimpleNamespace(
            text=t,
            region=SimpleNamespace(x=100, y=200, w=60, h=24),
        )

    def _find(target: str):
        for t in texts:
            if target in t:
                return _item(t)
        return None

    def _find_all(target: str):
        return [_item(t) for t in texts if target in t]

    result = SimpleNamespace(
        find=_find,
        find_all=_find_all,
        has=lambda t: any(t in x for x in texts),
        items=[_item(t) for t in texts],  # _find_title / H-label iteration
    )
    return SimpleNamespace(
        result=result, image=np.zeros((900, 1600, 3), dtype=np.uint8),
    )


def _stub_ocr_pages(task, pages: list[list[str]]) -> None:
    """Stub task._ocr to pop scripted pages in order."""
    queue = list(pages)

    async def _fake(ctx, *, region=None, ready=None, **kwargs):
        page = queue.pop(0) if queue else []
        return _fake_page(page)

    task._ocr = AsyncMock(side_effect=_fake)


class _FakeWake:
    async def run(self, ctx):
        return OpResult(success=True)


class _FakeReturnOk:
    def __init__(self, *a, **k):
        pass

    async def run(self, ctx):
        return OpResult(success=True)


class _FakeReturnFail:
    def __init__(self, *a, **k):
        pass

    async def run(self, ctx):
        return OpResult(success=False)


class _FakePageCheck:
    def __init__(self, *a, **k):
        pass

    async def evaluate(self, ctx):
        return CheckResult(passed=True)


class _FakePageCheckMiss:
    """OnPageCheck that never matches (never on hub)."""

    def __init__(self, *a, **k):
        pass

    async def evaluate(self, ctx):
        return CheckResult(passed=False)


_NAV_PATCHES = (
    patch(f"{_ACT}.WakeHubUiAction", _FakeWake),
    patch(f"{_ACT}.OnPageCheck", _FakePageCheck),
)


def _success_script() -> list[list[str]]:
    """Pages for a full 5/5 claim run: H search + verify page + 4 per title."""
    pages = [[], ["福利", "前往挑战"]]  # H search + _enter_activity_page verify
    for t in _TITLES:
        pages.append([t])            # title find
        pages.append(["前往邀约"])    # invite button
        pages.append(["见闻"])        # 见闻 tab
        pages.append(["一键领取"])    # claim button
        pages.append(_ACTIVITY_PAGE)  # back-to-activity check
    return pages


def _run_inv_execute(task, ctx, *, return_ok=True):
    """Run InvitationRewardClaim.execute under the standard nav/Op patches.

    Returns (result, clicks)."""
    import contextlib
    clicks, spy = _spy_clicks()
    patches = [
        *_NAV_PATCHES,
        patch(f"{_ACT}.ReturnToHubAction", _FakeReturnOk if return_ok else _FakeReturnFail),
        patch(f"{_ACT}.ClickOp", spy),
        patch(f"{_ACT}.ClickPxOp", spy),
        patch(_PRESS_RUN, AsyncMock(return_value=OpResult(success=True))),
        patch(f"{_ACT}.SleepOp.run", AsyncMock(return_value=OpResult(success=True))),
    ]
    with contextlib.ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        result = _run(task.execute(ctx))
    return result, clicks


def test_invitation_metadata():
    assert InvitationRewardClaim.name == "invitation_reward_claim"
    assert InvitationRewardClaim.safe is True
    device = MockDevice()
    assert _run(InvitationRewardClaim().can_run(TaskContext(device=device))) is True


def test_invitation_execute_claims_all_titles():
    """Happy path: all 5 titles claimed, no back-presses needed."""
    device = MockDevice()
    ctx = TaskContext(device=device)
    task = InvitationRewardClaim()
    _stub_ocr_pages(task, _success_script())
    result, clicks = _run_inv_execute(task, ctx)

    assert result.status == "success"
    assert result.data == {"claimed": 5, "skipped": 0}
    # 5 titles × 4 clicks (title/前往邀约/见闻/claim), all pixel clicks
    px = [c for c in clicks if c[0] == "px"]
    assert len(px) == 20
    # Activity page re-verified immediately → no back-press clicks
    assert ("op", 0.022, 0.039) not in clicks


def test_invitation_execute_skips_missing_invite_button():
    """Title found but 前往邀约 absent → title skipped, run continues."""
    device = MockDevice()
    ctx = TaskContext(device=device)
    task = InvitationRewardClaim()
    pages = [[], ["福利"]]
    # First title: title page OK but no 前往邀约 anywhere
    pages.append(["夜宴之邀"])
    pages.append([])                # invite-button check (no 前往邀约)
    pages.append(_ACTIVITY_PAGE)    # back check (already on activity)
    # Remaining 4 titles: full success
    for t in _TITLES[1:]:
        pages.append([t])
        pages.append(["前往邀约"])
        pages.append(["见闻"])
        pages.append(["领取"])
        pages.append(_ACTIVITY_PAGE)
    _stub_ocr_pages(task, pages)
    result, clicks = _run_inv_execute(task, ctx)

    assert result.status == "success"
    assert result.data == {"claimed": 4, "skipped": 1}


def test_invitation_execute_prefers_one_key_claim():
    """'一键领取' present → clicked instead of plain '领取'."""
    device = MockDevice()
    ctx = TaskContext(device=device)
    task = InvitationRewardClaim()
    pages = [[], ["福利"]]
    pages.append(["夜宴之邀"])
    pages.append(["前往邀约"])
    pages.append(["见闻"])
    pages.append(["一键领取", "领取"])  # both visible
    pages.append(_ACTIVITY_PAGE)
    # remaining titles missing entirely → skipped (miss + 2 scroll rescans)
    for _ in _TITLES[1:]:
        pages.extend([[], [], []])
        pages.append(_ACTIVITY_PAGE)
    _stub_ocr_pages(task, pages)
    result, clicks = _run_inv_execute(task, ctx)

    assert result.status == "success"
    assert result.data == {"claimed": 1, "skipped": 4}
    # 一键领取 preferred: the claim click targeted the 一键领取 page
    px = [c for c in clicks if c[0] == "px"]
    assert len(px) == 1 * 4


def test_invitation_execute_fails_when_no_title_found():
    """Activity page reachable but zero titles → failed (wrong page)."""
    device = MockDevice()
    ctx = TaskContext(device=device)
    task = InvitationRewardClaim()
    pages = [[], ["福利"]]
    for _ in _TITLES:
        pages.extend([[], [], []])  # title miss + 2 scroll rescans
        pages.append(_ACTIVITY_PAGE)  # back check OK
    _stub_ocr_pages(task, pages)
    result, _clicks = _run_inv_execute(task, ctx)

    assert result.status == "failed"
    assert "No invitation title" in result.message


def test_invitation_execute_fails_when_hub_unreachable():
    """ReturnToHubAction fails → failed with the hub reason."""
    device = MockDevice()
    ctx = TaskContext(device=device)
    task = InvitationRewardClaim()
    with (
        patch(f"{_ACT}.WakeHubUiAction", _FakeWake),
        patch(f"{_ACT}.ReturnToHubAction", _FakeReturnFail),
    ):
        result = _run(task.execute(ctx))

    assert result.status == "failed"
    assert result.message == "Cannot return to hub"


def test_invitation_back_navigation_presses_back():
    """Deep page → settle re-check also misses → press back → verified."""
    device = MockDevice()
    ctx = TaskContext(device=device)
    task = InvitationRewardClaim()
    # check miss → hub miss → settle recheck miss → press → check hit
    pages = [["见闻"], ["见闻"], _ACTIVITY_PAGE]
    _stub_ocr_pages(task, pages)
    clicks, spy = _spy_clicks()
    with (
        patch(f"{_ACT}.OnPageCheck", _FakePageCheckMiss),
        patch(f"{_ACT}.SleepOp.run", AsyncMock(return_value=OpResult(success=True))),
        patch(f"{_ACT}.ClickOp", spy),
        patch(f"{_ACT}.ClickPxOp", spy),
        patch(_PRESS_RUN, AsyncMock(return_value=OpResult(success=True))),
    ):
        ok = _run(task._back_to_activity_page(ctx, None))

    assert ok is True
    assert ("op", 0.022, 0.039) in clicks


def test_invitation_back_navigation_gives_up():
    """No markers and never on hub after all back-presses → False."""
    device = MockDevice()
    ctx = TaskContext(device=device)
    task = InvitationRewardClaim()
    # Each loop iteration consumes check + settle recheck; plus final check.
    pages = [["见闻"]] * (InvitationRewardClaim._MAX_BACKS * 2 + 1)
    _stub_ocr_pages(task, pages)
    clicks, spy = _spy_clicks()
    with (
        patch(f"{_ACT}.OnPageCheck", _FakePageCheckMiss),
        patch(f"{_ACT}.SleepOp.run", AsyncMock(return_value=OpResult(success=True))),
        patch(f"{_ACT}.ClickOp", spy),
        patch(f"{_ACT}.ClickPxOp", spy),
        patch(_PRESS_RUN, AsyncMock(return_value=OpResult(success=True))),
    ):
        ok = _run(task._back_to_activity_page(ctx, None))

    assert ok is False
    back_presses = [c for c in clicks if c == ("op", 0.022, 0.039)]
    assert len(back_presses) == InvitationRewardClaim._MAX_BACKS


def test_invitation_back_overshoot_to_hub_recovers():
    """Pressed past the activity page into the hub → re-enter, no more backs.

    Field failure 2026-11-23: a transition-frame OCR miss after a back
    press triggered one extra press, landing on the hub; the old loop
    then kept pressing back (a no-op there) and failed. The hub-recovery
    guard must re-enter via the H shortcut instead.
    """
    device = MockDevice()
    ctx = TaskContext(device=device)
    task = InvitationRewardClaim()
    # check miss → hub check PASSES → _enter_activity_page (H search +
    # keyword verify) → recheck hit
    pages = [["见闻"], [], ["福利"], _ACTIVITY_PAGE]
    _stub_ocr_pages(task, pages)
    clicks, spy = _spy_clicks()
    with (
        patch(f"{_ACT}.OnPageCheck", _FakePageCheck),
        patch(f"{_ACT}.SleepOp.run", AsyncMock(return_value=OpResult(success=True))),
        patch(f"{_ACT}.ClickOp", spy),
        patch(f"{_ACT}.ClickPxOp", spy),
        patch(f"{_ACT}.ReturnToHubAction", _FakeReturnOk),
        patch(_PRESS_RUN, AsyncMock(return_value=OpResult(success=True))),
    ):
        ok = _run(task._back_to_activity_page(ctx, None))

    assert ok is True
    # No blind back presses after the overshoot…
    assert ("op", 0.022, 0.039) not in clicks
    # …instead the H-fallback re-entered the activity page.
    assert ("op", 0.858, 0.211) in clicks


def test_invitation_back_settle_recheck_avoids_extra_press():
    """Post-press transition-frame miss → settle recheck hits, no extra press.

    The field overshoot: after back press #1 reached the activity page,
    the verification OCR ran mid-transition and missed the markers, so
    the old loop pressed back AGAIN (activity → hub). The settle recheck
    must confirm the page before allowing a second press.
    """
    device = MockDevice()
    ctx = TaskContext(device=device)
    task = InvitationRewardClaim()
    # i=0: check miss → hub miss → settle miss → press #1
    # i=1: check miss (transition frame) → hub miss → settle recheck HIT
    pages = [["见闻"], ["见闻"], ["见闻"], _ACTIVITY_PAGE]
    _stub_ocr_pages(task, pages)
    clicks, spy = _spy_clicks()
    with (
        patch(f"{_ACT}.OnPageCheck", _FakePageCheckMiss),
        patch(f"{_ACT}.SleepOp.run", AsyncMock(return_value=OpResult(success=True))),
        patch(f"{_ACT}.ClickOp", spy),
        patch(f"{_ACT}.ClickPxOp", spy),
        patch(_PRESS_RUN, AsyncMock(return_value=OpResult(success=True))),
    ):
        ok = _run(task._back_to_activity_page(ctx, None))

    assert ok is True
    # Exactly one back press — the settle recheck prevented press #2.
    back_presses = [c for c in clicks if c == ("op", 0.022, 0.039)]
    assert len(back_presses) == 1


def test_on_activity_page_requires_two_titles_in_left_column():
    """Regression (field 2026-11-23): one title on screen is NOT enough.

    The invite sub-page's header shows the event title itself, so the old
    "any title/keyword on screen" check false-positived one back-press
    short of the activity page; the remaining titles then all read as
    "not in left column". Only the real activity page shows >=2 titles
    inside the LEFT COLUMN region — require that.
    """
    device = MockDevice()
    ctx = TaskContext(device=device)
    task = InvitationRewardClaim()

    # Invite sub-page: header title + button, left column empty → not it.
    _stub_ocr_pages(task, [["观星手记", "前往邀约"]])
    assert _run(task._on_activity_page(ctx)) is False

    # Single title in the left column is still not enough (defensive).
    _stub_ocr_pages(task, [["夜宴之邀"]])
    assert _run(task._on_activity_page(ctx)) is False

    # Real activity page: the list shows the titles → verified.
    _stub_ocr_pages(task, [_ACTIVITY_PAGE])
    assert _run(task._on_activity_page(ctx)) is True


def test_find_title_matches_split_and_misread_items():
    """Regression (field 2026-11-23): 咫尺身畔 never matched exactly.

    RapidOCR can split a title into separate items or misread a char,
    so exact find() misses forever while neighbours match. The bigram
    fallback must recover the hit (titles are unique in the left
    column, so a 2-char overlap is unambiguous).
    """
    # Split into two OCR items → exact find fails, bigram recovers.
    split = _fake_page(["咫尺", "身畔"]).result
    assert InvitationRewardClaim._find_title(split, "咫尺身畔") is not None
    # Misread char ("身胖" instead of "身畔") → bigram 咫尺 still hits.
    misread = _fake_page(["咫尺身胖"]).result
    assert InvitationRewardClaim._find_title(misread, "咫尺身畔") is not None
    # Exact hit still preferred/works.
    exact = _fake_page(["咫尺身畔"]).result
    assert InvitationRewardClaim._find_title(exact, "咫尺身畔") is not None
    # No overlap at all → None (no false positive).
    other = _fake_page(["月色予梦", "奇响派对"]).result
    assert InvitationRewardClaim._find_title(other, "咫尺身畔") is None


def test_claim_one_scrolls_when_title_missing():
    """Title not found → scroll the left column and rescan, then click.

    Field 2026-11-23: 咫尺身畔 skipped after 3 static OCR misses; the
    list may be auto-scrolled by a previous selection, so a static
    retry alone can never see it.
    """
    device = MockDevice()
    ctx = TaskContext(device=device)
    task = InvitationRewardClaim()
    pages = [
        [],               # initial scan + retries → miss
        ["咫尺身畔"],      # post-scroll rescan → hit
        ["前往邀约"],
        ["见闻"],
        ["一键领取"],
    ]
    _stub_ocr_pages(task, pages)
    swipes: list = []

    class _SpySwipe:
        def __init__(self, *a, **kw):
            swipes.append(kw)

        async def run(self, ctx):
            return OpResult(success=True)

    clicks, spy = _spy_clicks()
    with (
        patch(f"{_ACT}.SwipeOp", _SpySwipe),
        patch(_CLICKPX, spy),
        patch(_PRESS_RUN, AsyncMock(return_value=OpResult(success=True))),
    ):
        ok, found = _run(task._claim_one(ctx, "咫尺身畔", None))

    assert (ok, found) == (True, True)
    assert len(swipes) >= 1
    assert ("px", 130, 212) in clicks  # title row center from OCR stub


def test_claim_one_skips_after_scroll_miss():
    """Title absent even after both scroll rescans → clean skip."""
    device = MockDevice()
    ctx = TaskContext(device=device)
    task = InvitationRewardClaim()
    _stub_ocr_pages(task, [[], [], []])  # initial + 2 post-scroll scans
    swipes: list = []

    class _SpySwipe:
        def __init__(self, *a, **kw):
            swipes.append(kw)

        async def run(self, ctx):
            return OpResult(success=True)

    clicks, spy = _spy_clicks()
    with (
        patch(f"{_ACT}.SwipeOp", _SpySwipe),
        patch(_CLICKPX, spy),
    ):
        ok, found = _run(task._claim_one(ctx, "咫尺身畔", None))

    assert (ok, found) == (False, False)
    assert len(swipes) == 2  # both directions tried
    assert not any(kind == "px" for kind, _, _ in clicks)


def test_ocr_accepts_retries_kwarg():
    """Regression (field crash 2026-11-23): _ocr() must forward `retries`.

    The worker crashed with "_ActivityPageNav._ocr() got an unexpected
    keyword argument 'retries'" — the wrapper lacked the parameter the
    back-navigation passes. Tests stub task._ocr wholesale, so only this
    direct call against the real wrapper catches a signature mismatch.
    """
    device = MockDevice()
    ctx = TaskContext(device=device)
    task = InvitationRewardClaim()
    with patch(f"{_ACT}.ocr_scan_with_retry", AsyncMock()) as mock_retry:
        _run(task._ocr(ctx, retries=0))

    assert mock_retry.await_args.kwargs["retries"] == 0
    # Default (no kwarg) falls back to the class retry count.
    with patch(f"{_ACT}.ocr_scan_with_retry", AsyncMock()) as mock_retry:
        _run(task._ocr(ctx))
    assert mock_retry.await_args.kwargs["retries"] == \
        InvitationRewardClaim._OCR_RETRIES


def test_claimable_excludes_already_claimed():
    """'已领取' contains '领取' — must never be picked as the claim button."""
    claimed = SimpleNamespace(
        text="已领取", region=SimpleNamespace(x=1, y=2, w=3, h=4),
    )
    claimable = SimpleNamespace(
        text="领取", region=SimpleNamespace(x=5, y=6, w=7, h=8),
    )
    one_key = SimpleNamespace(
        text="一键领取", region=SimpleNamespace(x=9, y=9, w=9, h=9),
    )

    def _ocr_with(*items):
        return SimpleNamespace(
            find=lambda t: next(
                (i for i in items if t in i.text), None,
            ),
            find_all=lambda t: [i for i in items if t in i.text],
        )

    # Only 已领取 on the page → nothing claimable.
    assert InvitationRewardClaim._claimable(_ocr_with(claimed)) is None
    # 已领取 first, plain 领取 later → pick the claimable one.
    assert InvitationRewardClaim._claimable(
        _ocr_with(claimed, claimable)
    ) is claimable
    # 一键领取 preferred over everything.
    assert InvitationRewardClaim._claimable(
        _ocr_with(claimed, claimable, one_key)
    ) is one_key


def test_invitation_execute_already_claimed_is_success():
    """Title found but only '已领取' visible → skipped, run still succeeds.

    The old all-skipped failure check counted this as "no title found"
    and failed the task; only zero titles FOUND is a navigation failure.
    """
    device = MockDevice()
    ctx = TaskContext(device=device)
    task = InvitationRewardClaim()
    pages = [[], ["福利"]]  # H search + activity-page verify
    # First title: full path, but the claim page shows only 已领取
    pages.append(["夜宴之邀"])
    pages.append(["前往邀约"])
    pages.append(["见闻"])
    pages.append(["已领取"])
    pages.append(_ACTIVITY_PAGE)  # back check
    # Remaining titles missing entirely → skipped (miss + 2 scroll rescans)
    for _ in _TITLES[1:]:
        pages.extend([[], [], []])
        pages.append(_ACTIVITY_PAGE)
    _stub_ocr_pages(task, pages)
    result, clicks = _run_inv_execute(task, ctx)

    assert result.status == "success"
    assert result.data == {"claimed": 0, "skipped": 5}
    # No claim click was made (已领取 must not be clicked — field bug).
    claim_clicks = [c for c in clicks if c == ("px", 1194, 257)]
    assert claim_clicks == []
