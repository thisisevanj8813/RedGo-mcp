"""运行环境检查（启动时执行一次）。

检查当前运行环境是否适合使用，不满足条件时拒绝启动并给出提示，
作为账号保护的一部分。规则：
- headless 浏览器   → 拒绝启动
- 不适合的网络环境   → 拒绝启动，可用 REDGO_ALLOW_DATACENTER_IP=1 显式放行（自担风险）
- 同设备多个登录会话 → 警告（重新登录也会触发，存在误报，故不拒绝）
- IP 查询失败        → 警告后放行（网络问题不应阻断正常使用）
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import urllib.request

from playwright.async_api import BrowserContext, Page

from .errors import RedGoError
from .guard import RateGuard

log = logging.getLogger("redgo.deploy")

# 只请求判定所需字段；ip-api 免费层走 http
_IP_API = "http://ip-api.com/json/?fields=status,country,hosting,proxy,query"


def is_headless_ua(ua: str) -> bool:
    return "headless" in (ua or "").lower()


def classify_ip(info: dict) -> str | None:
    """ip-api 响应 → 类别（hosting/proxy），None 表示普通住宅 IP。"""
    if not info or info.get("status") != "success":
        return None
    if info.get("hosting"):
        return "hosting"
    if info.get("proxy"):
        return "proxy"
    return None


def _fetch_ip_info_sync(timeout: float) -> dict | None:
    try:
        with urllib.request.urlopen(_IP_API, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        log.warning("IP 检查查询失败（%s），跳过该项", e)
        return None


async def run_deploy_checks(page: Page, context: BrowserContext, guard: RateGuard) -> None:
    """启动时的运行环境检查。不满足硬条件抛 RedGoError 拒绝启动，软条件打警告。"""
    # 1) headless：读现有页面的 UA，无网络请求
    ua = await page.evaluate("() => navigator.userAgent")
    if is_headless_ua(ua):
        raise RedGoError(
            "DEPLOY_HEADLESS",
            "检测到 headless 浏览器，不支持此运行方式",
            is_risk_control=True,
            suggested_action="用 scripts/launch_chrome.sh 启动有头的真实 Chrome",
        )

    # 2) 不适合的网络环境（hosting/proxy）
    info = await asyncio.to_thread(_fetch_ip_info_sync, 3.0)
    kind = classify_ip(info) if info else None
    if kind:
        if os.environ.get("REDGO_ALLOW_DATACENTER_IP") == "1":
            log.warning("出口 IP 被判定为 %s（%s），已由 REDGO_ALLOW_DATACENTER_IP=1 "
                        "放行——风险自担", kind, info.get("query", "?"))
        else:
            raise RedGoError(
                "DEPLOY_DATACENTER_IP",
                f"出口 IP（{info.get('query', '?')}）被判定为 {kind}，"
                "不适合此运行方式",
                is_risk_control=True,
                suggested_action="请在自己电脑的住宅网络下运行；确需放行可设 REDGO_ALLOW_DATACENTER_IP=1",
            )

    # 3) 同设备多账号（启发式：登录会话标识跨天累计）
    cookies = await context.cookies("https://www.xiaohongshu.com")
    ws = next((c["value"] for c in cookies if c["name"] == "web_session"), "")
    if ws:
        h = hashlib.sha256(ws.encode()).hexdigest()[:12]
        n = guard.note_session_hash(h)
        if n > 1:
            log.warning(
                "本机已记录 %d 个不同登录会话（可能是同设备多账号，也可能只是重新登录）。"
                "建议一台设备只用一个账号。", n,
            )
