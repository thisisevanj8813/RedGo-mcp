"""RateGuard —— 请求节奏与用量闸门。

为账号安全提供三道默认保护，组合使用：
1. **用量上限**：每日请求数有硬上限，达到上限返回明确错误（不静默、不继续）。
   计数持久化到本地文件，跨进程重启沿用同一天的累计值。
2. **随机节奏**：请求间隔随机化，不使用固定 sleep。
3. **运行时段**：可配置的静默时段内不发请求。

配合 deploy.py 的环境检查，构成开箱即用的账号保护。

默认值都可用环境变量调整：
  REDGO_DAILY_QUOTA（默认 100，调高会告警）
  REDGO_QUIET_START / REDGO_QUIET_END（默认 1 / 7）
  REDGO_STATE_PATH（默认 ~/.redgo/state.json）
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .errors import RedGoError
from .ext import DefaultPacing, PacingStrategy

log = logging.getLogger("redgo.guard")


def _default_state_path() -> Path:
    return Path(os.environ.get("REDGO_STATE_PATH", "~/.redgo/state.json")).expanduser()


@dataclass
class GuardConfig:
    # 请求间隔：随机化（非固定值），中位数 ~15s，取值区间 [8, 40] 秒
    min_interval: float = 8.0
    max_interval: float = 40.0
    median_interval: float = 15.0
    sigma: float = 0.45
    # 偶发长停顿：1-3 分钟
    long_pause_prob: float = 0.07
    long_pause_min: float = 60.0
    long_pause_max: float = 180.0
    # 每日请求数硬上限
    daily_quota: int = 100
    # 静默时段：[quiet_start, quiet_end) 不发请求
    quiet_start: int = 1
    quiet_end: int = 7
    state_path: Path = field(default_factory=_default_state_path)

    @classmethod
    def from_env(cls) -> "GuardConfig":
        cfg = cls()
        quota = os.environ.get("REDGO_DAILY_QUOTA")
        if quota:
            cfg.daily_quota = int(quota)
            if cfg.daily_quota > 100:
                log.warning(
                    "REDGO_DAILY_QUOTA=%s 超过默认上限 100/天，请谨慎使用、自担风险",
                    quota,
                )
        if os.environ.get("REDGO_QUIET_START"):
            cfg.quiet_start = int(os.environ["REDGO_QUIET_START"])
        if os.environ.get("REDGO_QUIET_END"):
            cfg.quiet_end = int(os.environ["REDGO_QUIET_END"])
        return cfg


class RateGuard:
    """单会话锁 + 随机间隔 + 静默窗 + 持久化日配额。

    now_fn / rng 可注入，便于单测（不打真实请求就能验全部逻辑）。
    """

    def __init__(
        self,
        config: GuardConfig | None = None,
        *,
        now_fn=None,
        rng: random.Random | None = None,
        pacing: PacingStrategy | None = None,
    ):
        self.cfg = config or GuardConfig.from_env()
        self._now = now_fn or datetime.now
        self._rng = rng or random.Random()
        # 节奏策略可被扩展替换（ext.py）；用量上限/静默时段/锁在本类闸门里，扩展不可绕过
        self._pacing = pacing or DefaultPacing(self.cfg, self._rng)
        self._lock = asyncio.Lock()
        self._last_at: float = 0.0

    # ---- 间隔 ----

    def draw_interval(self) -> float:
        """返回下一次请求前的等待秒数（随机化、非固定值，默认区间见配置）。"""
        return self._pacing.next_delay()

    # ---- 持久化状态 ----

    def _load_state(self) -> dict:
        try:
            return json.loads(self.cfg.state_path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save_state(self, state: dict) -> None:
        path = self.cfg.state_path
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False))
        os.replace(tmp, path)

    def _today_state(self, now: datetime) -> dict:
        state = self._load_state()
        today = now.strftime("%Y-%m-%d")
        if state.get("date") != today:
            state = {"date": today, "count": 0,
                     "session_hashes": state.get("session_hashes", [])}
        state.setdefault("count", 0)
        state.setdefault("session_hashes", [])
        return state

    def note_session_hash(self, h: str) -> int:
        """记录登录会话标识（跨天累计去重），返回累计的不同会话数。供 deploy 检查使用。"""
        state = self._today_state(self._now())
        if h and h not in state["session_hashes"]:
            state["session_hashes"].append(h)
            self._save_state(state)
        return len(state["session_hashes"])

    def quota_used_today(self) -> int:
        return self._today_state(self._now())["count"]

    # ---- 闸门 ----

    def _check_window_and_quota(self, now: datetime) -> dict:
        c = self.cfg
        if c.quiet_start <= now.hour < c.quiet_end:
            raise RedGoError(
                "QUIET_HOURS",
                f"当前处于静默时段（{c.quiet_start}-{c.quiet_end} 点不发请求）",
                retryable=True,
                is_risk_control=True,
                suggested_action=f"等到 {c.quiet_end:02d}:00 之后再请求",
            )
        state = self._today_state(now)
        if state["count"] >= c.daily_quota:
            raise RedGoError(
                "QUOTA_EXCEEDED",
                f"今日配额已用尽（{state['count']}/{c.daily_quota}，硬上限）",
                retryable=False,
                is_risk_control=True,
                suggested_action="今天的请求额度已用完，明天再来。这是账号保护默认值，请勿绕过。",
            )
        return state

    @asynccontextmanager
    async def session(self):
        """包住一次完整的浏览器操作：静默窗/配额检查 → 随机等待 → 操作 → 计数落盘。

        锁覆盖全程：同账号同时刻只有一个活跃会话（也防并发抢 page）。
        检查在等待之前做——被拒时 agent 立刻拿到明确错误，不白等。
        """
        async with self._lock:
            now = self._now()
            state = self._check_window_and_quota(now)
            wait = self.draw_interval()
            elapsed = time.monotonic() - self._last_at
            if self._last_at and elapsed < wait:
                pause = wait - elapsed
                log.info("RateGuard: 等待 %.1fs（今日 %d/%d）",
                         pause, state["count"] + 1, self.cfg.daily_quota)
                await asyncio.sleep(pause)
            try:
                yield
            finally:
                # 重新读最新状态再 +1，避免覆盖其他进程的计数
                latest = self._today_state(self._now())
                latest["count"] += 1
                self._save_state(latest)
                self._last_at = time.monotonic()
