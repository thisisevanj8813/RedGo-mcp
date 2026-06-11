"""RedGo CLI。

  redgo launch-chrome   启动带 CDP 调试端口的真实 Chrome（独立 profile）
  redgo status          看 CDP / 登录态 / 今日配额
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

DEFAULT_PORT = 9222
DEFAULT_PROFILE = "~/.redgo/chrome-profile"
MAC_CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def cdp_version(port: int, timeout: float = 2.0) -> dict | None:
    try:
        with urllib.request.urlopen(f"http://localhost:{port}/json/version", timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _find_chrome(explicit: str | None) -> str | None:
    for cand in (explicit, os.environ.get("REDGO_CHROME_PATH"), MAC_CHROME):
        if cand and Path(cand).exists():
            return cand
    return None


def cmd_launch_chrome(args: argparse.Namespace) -> int:
    port = args.port
    if cdp_version(port):
        print(f"✅ localhost:{port} 已有可用的 CDP 实例，直接复用，无需重复启动。")
        return 0
    if _port_in_use(port):
        print(f"❌ 端口 {port} 被其他进程占用且不响应 CDP。换端口重试：", file=sys.stderr)
        print(f"   redgo launch-chrome --port {port + 1}", file=sys.stderr)
        print(f"   （MCP 侧对应设 REDGO_CDP_URL=http://localhost:{port + 1}）", file=sys.stderr)
        return 1

    chrome = _find_chrome(args.chrome_path)
    if not chrome:
        print(f"❌ 找不到 Chrome。装 Chrome，或用 --chrome-path / REDGO_CHROME_PATH 指定路径。",
              file=sys.stderr)
        return 1

    profile = Path(args.profile).expanduser()
    profile.mkdir(parents=True, exist_ok=True)
    print(f"🚀 启动 Chrome（CDP 端口 {port}，profile: {profile}）")
    subprocess.Popen(
        [
            chrome,
            f"--remote-debugging-port={port}",
            f"--user-data-dir={profile}",
            f"--remote-allow-origins=http://localhost:{port}",
            "--no-first-run",
            "--no-default-browser-check",
            "https://www.xiaohongshu.com",
        ],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(30):
        if cdp_version(port):
            print("✅ Chrome 已就绪。首次使用：在打开的窗口里登录小红书，登录完成后保持窗口开着。")
            return 0
        time.sleep(0.5)
    print("❌ Chrome 启动后 15 秒内 CDP 未就绪，到窗口里看看出了什么。", file=sys.stderr)
    return 1


def cmd_status(args: argparse.Namespace) -> int:
    port = args.port
    ver = cdp_version(port)
    if not ver:
        print(f"CDP     ❌ localhost:{port} 不可达（先跑 redgo launch-chrome）")
        return 1
    ua = ver.get("User-Agent", "")
    headless = "（⚠️ headless！）" if "headless" in ua.lower() else ""
    print(f"CDP     ✅ {ver.get('Browser', '?')} @ localhost:{port} {headless}")

    # 登录态：读 cookie，零小红书请求
    try:
        import asyncio

        from playwright.async_api import async_playwright

        async def check() -> bool:
            pw = await async_playwright().start()
            try:
                browser = await pw.chromium.connect_over_cdp(f"http://localhost:{port}")
                if not browser.contexts:
                    return False
                cookies = await browser.contexts[0].cookies("https://www.xiaohongshu.com")
                await browser.close()
                return any(c["name"] == "web_session" and c["value"] for c in cookies)
            finally:
                await pw.stop()

        logged_in = asyncio.run(check())
        print("登录态  " + ("✅ web_session 在" if logged_in
                            else "❌ 未登录（到 Chrome 窗口登录小红书）"))
    except Exception as e:
        print(f"登录态  ⚠️ 检查失败：{e}")

    # 配额：读持久化账本
    from .guard import GuardConfig, RateGuard

    guard = RateGuard(GuardConfig.from_env())
    used = guard.quota_used_today()
    print(f"配额    今日 {used}/{guard.cfg.daily_quota}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="redgo", description="RedGo 配套命令")
    sub = parser.add_subparsers(dest="command", required=True)

    p_launch = sub.add_parser("launch-chrome", help="启动带 CDP 调试端口的真实 Chrome（独立 profile）")
    p_launch.add_argument("--port", type=int, default=int(os.environ.get("REDGO_CDP_PORT", DEFAULT_PORT)))
    p_launch.add_argument("--profile", default=os.environ.get("REDGO_PROFILE_DIR", DEFAULT_PROFILE))
    p_launch.add_argument("--chrome-path", default=None)
    p_launch.set_defaults(func=cmd_launch_chrome)

    p_status = sub.add_parser("status", help="看 CDP / 登录态 / 今日配额")
    p_status.add_argument("--port", type=int, default=int(os.environ.get("REDGO_CDP_PORT", DEFAULT_PORT)))
    p_status.set_defaults(func=cmd_status)

    args = parser.parse_args()
    sys.exit(args.func(args))
