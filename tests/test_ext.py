"""扩展接口层单测：默认实现行为不变、策略可替换、配额闸门扩展碰不到。全离线。"""

import asyncio
import random
from datetime import datetime
from pathlib import Path

import pytest

from redgo.errors import RedGoError
from redgo.ext import DefaultPacing, Extensions, load_extensions
from redgo.guard import GuardConfig, RateGuard

NOON = datetime(2026, 6, 11, 12, 0, 0)


def test_default_pacing_same_distribution_as_v1():
    """重构为策略后分布性质不变：这是开源版'行为零变化'的守护测试。"""
    cfg = GuardConfig()
    pacing = DefaultPacing(cfg, random.Random(7))
    samples = [pacing.next_delay() for _ in range(20_000)]
    base = [s for s in samples if s <= 40.0]
    pauses = [s for s in samples if s > 40.0]
    assert all(8.0 <= s <= 40.0 for s in base)
    assert all(60.0 <= s <= 180.0 for s in pauses)
    assert 0.045 <= len(pauses) / len(samples) <= 0.095
    assert len(set(samples)) == len(samples)


def test_custom_pacing_is_used():
    class FixedFastPacing:  # 测试用；真扩展不许这么写
        def next_delay(self) -> float:
            return 0.001

    g = RateGuard(GuardConfig(state_path=Path("/tmp/_rp_test_unused.json")),
                  now_fn=lambda: NOON, pacing=FixedFastPacing())
    assert g.draw_interval() == 0.001


def test_pacing_cannot_bypass_quota(tmp_path):
    """安全不变量：节奏策略再快也越不过配额闸门。"""

    class GreedyPacing:
        def next_delay(self) -> float:
            return 0.0  # 扩展声称"不用等"

    async def run():
        cfg = GuardConfig(daily_quota=2, state_path=tmp_path / "state.json")
        g = RateGuard(cfg, now_fn=lambda: NOON, pacing=GreedyPacing())
        for _ in range(2):
            async with g.session():
                pass
        with pytest.raises(RedGoError) as ei:
            async with g.session():
                pass
        assert ei.value.code == "QUOTA_EXCEEDED"

    asyncio.run(run())


def test_load_extensions_defaults_when_none_installed():
    exts = load_extensions()
    assert isinstance(exts, Extensions)
    assert exts.pacing is None          # → RateGuard 用 DefaultPacing
    assert exts.tool_registrars == []   # 开源版没有额外工具
    assert exts.account.cdp_url("http://localhost:9222") == "http://localhost:9222"
