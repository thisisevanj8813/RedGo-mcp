"""RateGuard 单测：间隔分布、配额持久化、静默窗。全离线，不打任何真实请求。"""

import asyncio
import json
import random
from datetime import datetime
from pathlib import Path

import pytest

from redgo.errors import RedGoError
from redgo.guard import GuardConfig, RateGuard

NOON = datetime(2026, 6, 11, 12, 0, 0)


def make_guard(tmp_path: Path, *, quota=100, now=NOON, seed=42, fast=True) -> RateGuard:
    cfg = GuardConfig(daily_quota=quota, state_path=tmp_path / "state.json")
    if fast:  # 单测不真等：把间隔压到毫秒级，分布形状另测
        cfg.min_interval = 0.001
        cfg.max_interval = 0.002
        cfg.median_interval = 0.0015
        cfg.long_pause_prob = 0.0
    return RateGuard(cfg, now_fn=lambda: now, rng=random.Random(seed))


# ---------- 间隔分布 ----------

def test_interval_distribution():
    g = RateGuard(GuardConfig(), now_fn=lambda: NOON, rng=random.Random(7))
    samples = [g.draw_interval() for _ in range(20_000)]
    base = [s for s in samples if s <= 40.0]
    pauses = [s for s in samples if s > 40.0]

    # 基础抖动严格落在 [8, 40]
    assert all(8.0 <= s <= 40.0 for s in base)
    # 长停顿落在 [60, 180]，占比 ~7%（±2.5%）
    assert all(60.0 <= s <= 180.0 for s in pauses)
    assert 0.045 <= len(pauses) / len(samples) <= 0.095
    # 中位数贴合 15s 锚点
    mid = sorted(base)[len(base) // 2]
    assert 12.0 <= mid <= 19.0
    # 平均间隔 ≥10s ⇒ 平均频率 ≤6 次/分钟
    assert sum(samples) / len(samples) >= 10.0


def test_no_fixed_sleep():
    """间隔不应是固定值：连续抽样不允许出现大量重复值。"""
    g = RateGuard(GuardConfig(), now_fn=lambda: NOON, rng=random.Random(1))
    samples = [g.draw_interval() for _ in range(1000)]
    assert len(set(samples)) > 990
    assert not any(a == b for a, b in zip(samples, samples[1:]))


# ---------- 配额持久化 ----------

def test_quota_blocks_and_survives_restart(tmp_path):
    async def run():
        g = make_guard(tmp_path, quota=3)
        for _ in range(3):
            async with g.session():
                pass
        with pytest.raises(RedGoError) as ei:
            async with g.session():
                pass
        assert ei.value.code == "QUOTA_EXCEEDED"

        # 模拟进程重启：新实例、同一个 state 文件 → 仍然立刻拒
        g2 = make_guard(tmp_path, quota=3)
        with pytest.raises(RedGoError) as ei2:
            async with g2.session():
                pass
        assert ei2.value.code == "QUOTA_EXCEEDED"

        state = json.loads((tmp_path / "state.json").read_text())
        assert state == {"date": "2026-06-11", "count": 3, "session_hashes": []}

    asyncio.run(run())


def test_quota_resets_next_day(tmp_path):
    async def run():
        g = make_guard(tmp_path, quota=1)
        async with g.session():
            pass
        with pytest.raises(RedGoError):
            async with g.session():
                pass
        # 第二天：同一文件，配额归零重计
        g2 = make_guard(tmp_path, quota=1, now=datetime(2026, 6, 12, 12, 0))
        async with g2.session():
            pass
        assert g2.quota_used_today() == 1

    asyncio.run(run())


def test_failed_call_still_counts(tmp_path):
    """操作抛异常也计入配额——请求已经发出，不论成功与否都应计数。"""
    async def run():
        g = make_guard(tmp_path, quota=5)
        with pytest.raises(ValueError):
            async with g.session():
                raise ValueError("浏览器操作失败")
        assert g.quota_used_today() == 1

    asyncio.run(run())


# ---------- 静默窗 ----------

@pytest.mark.parametrize("hour,blocked", [(0, False), (1, True), (3, True), (6, True), (7, False), (23, False)])
def test_quiet_hours(tmp_path, hour, blocked):
    async def run():
        g = make_guard(tmp_path, now=datetime(2026, 6, 11, hour, 30))
        if blocked:
            with pytest.raises(RedGoError) as ei:
                async with g.session():
                    pass
            assert ei.value.code == "QUIET_HOURS"
            assert g.quota_used_today() == 0  # 被拒不计数
        else:
            async with g.session():
                pass

    asyncio.run(run())


# ---------- 会话指纹（deploy 多账号检查的存储侧）----------

def test_session_hash_accumulates_distinct(tmp_path):
    g = make_guard(tmp_path)
    assert g.note_session_hash("aaa") == 1
    assert g.note_session_hash("aaa") == 1  # 同账号重复出现不累计
    assert g.note_session_hash("bbb") == 2  # 第二个账号 → 多账号信号
    assert g.note_session_hash("") == 2     # 空指纹不记
