"""扩展接口层（开源核心 / 可选扩展 的物理边界）。

切分原则：开源核心 = 基础账号保护 + 四个只读工具；可选扩展 = 在核心之上的
节奏/调度增强。扩展以独立包形式实现本文件的接口，通过 Python entry points
（group="redgo.extensions"）被发现和加载——本仓库不包含任何扩展包代码。

entry point 约定：一个可调用对象 `configure(exts: Extensions) -> None`，
拿到 Extensions 后自行替换字段 / 追加工具注册器。

== 安全不变量（接口设计的底线，重构时别弄丢）==
每日用量上限、单会话锁、静默时段的执行点在 guard.RateGuard 核心闸门里，
**不暴露给任何策略接口**。PacingStrategy 只能决定"等多久"，
不能决定"要不要超过用量上限"——任何扩展都越不过每日上限。
多账号场景走 AccountPolicy 横向扩展，不是纵向提高单号上限。
"""

from __future__ import annotations

import importlib.metadata
import logging
import random
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

log = logging.getLogger("redgo.ext")


@runtime_checkable
class PacingStrategy(Protocol):
    """决定两次操作之间等多久（秒）。只管节奏，管不了配额。"""

    def next_delay(self) -> float: ...


@runtime_checkable
class ActionHooks(Protocol):
    """页面动作前后的钩子（用于自定义动作前后的额外行为）。kind ∈ search/note/comments/profile。"""

    async def before_action(self, page, kind: str) -> None: ...

    async def after_action(self, page, kind: str) -> None: ...


@runtime_checkable
class AccountPolicy(Protocol):
    """会话 → 账号/浏览器端点的路由。开源核心恒为单账号单端点。"""

    def cdp_url(self, default: str) -> str: ...


class DefaultPacing:
    """默认节奏：随机化的请求间隔（非固定值）+ 偶发长停顿，默认参数见 GuardConfig。"""

    def __init__(self, cfg, rng: random.Random):
        self._cfg = cfg
        self._rng = rng

    def next_delay(self) -> float:
        c, rng = self._cfg, self._rng
        if rng.random() < c.long_pause_prob:
            return rng.uniform(c.long_pause_min, c.long_pause_max)
        # 出界重抽而非硬截断：截断会让样本堆积在边界值上，破坏分布形状
        import math

        for _ in range(8):
            v = rng.lognormvariate(math.log(c.median_interval), c.sigma)
            if c.min_interval <= v <= c.max_interval:
                return v
        return rng.uniform(c.min_interval, c.max_interval)


class DefaultActionHooks:
    """默认钩子：动作后随机短暂停顿 0.8-1.8 秒。"""

    async def before_action(self, page, kind: str) -> None:
        return None

    async def after_action(self, page, kind: str) -> None:
        await page.wait_for_timeout(random.randint(800, 1800))


class SingleAccountPolicy:
    def cdp_url(self, default: str) -> str:
        return default


@dataclass
class Extensions:
    pacing: PacingStrategy | None = None  # None → RateGuard 用 DefaultPacing
    hooks: ActionHooks = field(default_factory=DefaultActionHooks)
    account: AccountPolicy = field(default_factory=SingleAccountPolicy)
    # 扩展包可追加 MCP 工具：每个注册器以 (mcp) 为参被调用
    tool_registrars: list[Callable] = field(default_factory=list)


def load_extensions() -> Extensions:
    exts = Extensions()
    try:
        eps = importlib.metadata.entry_points(group="redgo.extensions")
    except Exception:
        return exts
    for ep in eps:
        try:
            configure = ep.load()
            configure(exts)
            log.info("已加载扩展：%s", ep.name)
        except Exception as e:
            log.warning("扩展 %s 加载失败（忽略并使用默认实现）：%s", ep.name, e)
    return exts
