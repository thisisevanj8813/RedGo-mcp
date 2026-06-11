"""CDP attach：连用户已登录的真实 Chrome。

铁律：connect_over_cdp attach，复用 contexts[0]，别新起浏览器、别新建 context
（CDP 低保真连接下新建 context 会出错，且会丢登录态）。
"""

from __future__ import annotations

import asyncio
import logging
import urllib.request

from playwright.async_api import Browser, Page, Playwright, async_playwright

from .errors import RedGoError

log = logging.getLogger("redgo.browser")

LAUNCH_HINT = "先运行 `redgo launch-chrome` 启动带调试端口的 Chrome，并在窗口里登录小红书"


def _reopen_tab_sync(cdp_url: str) -> bool:
    """用户关掉了 Chrome 窗口但进程还在（macOS 常态）时，CDP target 列表为空，
    connect_over_cdp 会报天书错误（Browser context management is not supported）。
    用 CDP HTTP 接口直接开回一个标签页自愈。"""
    try:
        req = urllib.request.Request(
            f"{cdp_url}/json/new?https://www.xiaohongshu.com", method="PUT"
        )
        with urllib.request.urlopen(req, timeout=3):
            return True
    except Exception as e:
        log.warning("自动重开标签页失败：%s", e)
        return False


async def attach_chrome(cdp_url: str) -> tuple[Playwright, Browser, Page]:
    pw = await async_playwright().start()
    browser = None
    for attempt in (1, 2):
        try:
            browser = await pw.chromium.connect_over_cdp(cdp_url)
            if browser.contexts:
                break
            # 连上了但没有 context（窗口被关光）→ 开回标签页重连
            await browser.close()
            browser = None
        except Exception as e:
            if attempt == 2:
                await pw.stop()
                raise RedGoError(
                    "CDP_CONNECT_FAILED",
                    f"连不上 Chrome CDP（{cdp_url}）：{e}",
                    suggested_action=LAUNCH_HINT,
                ) from e
        if attempt == 1:
            log.info("Chrome 窗口可能被关掉了，尝试自动重开标签页…")
            if not await asyncio.to_thread(_reopen_tab_sync, cdp_url):
                break
            await asyncio.sleep(1.0)

    if browser is None or not browser.contexts:
        if browser:
            await browser.close()
        await pw.stop()
        raise RedGoError(
            "NO_BROWSER_CONTEXT",
            "Chrome 里没有可复用的 context（窗口可能被关掉且自动重开失败）",
            suggested_action=LAUNCH_HINT,
        )

    ctx = browser.contexts[0]
    page: Page | None = None
    for pg in ctx.pages:
        if "xiaohongshu.com" in pg.url:
            page = pg
            break
    if page is None:
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
    return pw, browser, page
