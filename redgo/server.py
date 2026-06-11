"""RedGo MCP server：四个只读工具。

数据来源是页面在正常浏览时自身加载的数据，分两类接住：
- 页面会发 API 请求的（搜索/评论/作者笔记）：用 playwright expect_response
  接住对应响应；
- 整页加载不发 API 的（笔记详情）：读 window.__INITIAL_STATE__。
两类都是页面自身已加载的数据，按 URL path 匹配对应响应即可。
"""

from __future__ import annotations

import functools
import os
import urllib.parse
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from mcp.server.fastmcp import Context, FastMCP
from playwright.async_api import Browser, BrowserContext, Page, Response
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from .browser import attach_chrome
from .deploy import run_deploy_checks
from .errors import RedGoError
from .ext import load_extensions
from .guard import RateGuard
from .models import CommentsResult, CreatorNotesResult, NoteDetail, SearchResult
from .parse import (
    comment_from_obj,
    detail_from_note_obj,
    g,
    note_from_posted_item,
    note_from_search_item,
    note_url,
    profile_url,
)

CDP_URL = os.environ.get("REDGO_CDP_URL", "http://localhost:9222")

# 扩展加载（没装扩展包时全部为默认实现，行为与纯开源版完全一致）
_EXTS = load_extensions()

_SEARCH_API = "/api/sns/web/v1/search/notes"
_FEED_API = "/api/sns/web/v1/feed"
_COMMENTS_API = "/api/sns/web/v2/comment/page"
_USER_POSTED_API = "/api/sns/web/v1/user_posted"

# 登录态失效时小红书 web API 返回的业务码
_LOGIN_EXPIRED_CODES = {-100, -101}
# 平台返回的风控类业务码
_RISK_CONTROL_CODES = {
    300011: "当前账号存在异常",
    300012: "网络连接异常",
    300013: "请求被拦截",
}
_LOGIN_REFRESH_HINT = "到 RedGo 启动的 Chrome 窗口里刷新页面并重新登录小红书，然后重试"


@dataclass
class AppCtx:
    browser: Browser
    context: BrowserContext
    page: Page
    guard: RateGuard


@asynccontextmanager
async def lifespan(_server: FastMCP) -> AsyncIterator[AppCtx]:
    pw, browser, page = await attach_chrome(_EXTS.account.cdp_url(CDP_URL))
    guard = RateGuard(pacing=_EXTS.pacing)
    try:
        await run_deploy_checks(page, browser.contexts[0], guard)
    except Exception:
        await browser.close()
        await pw.stop()
        raise
    try:
        yield AppCtx(browser=browser, context=browser.contexts[0], page=page, guard=guard)
    finally:
        await browser.close()  # connect_over_cdp 下 close() 只断开连接，不会杀用户的 Chrome
        await pw.stop()


mcp = FastMCP("redgo", lifespan=lifespan)


def _raise_for_api_error(raw: dict) -> None:
    code = raw.get("code", 0)
    if code in _LOGIN_EXPIRED_CODES:
        raise RedGoError(
            "LOGIN_EXPIRED",
            f"小红书登录态失效（业务码 {code}）",
            retryable=False,
            suggested_action=_LOGIN_REFRESH_HINT,
        )
    if code in _RISK_CONTROL_CODES:
        raise RedGoError(
            "RISK_CONTROL",
            f"小红书风控拦截（{code}：{raw.get('msg') or _RISK_CONTROL_CODES[code]}）",
            retryable=False,
            is_risk_control=True,
            suggested_action="立即停止请求并冷却 30 分钟以上。反复出现说明账号已被标记，今天别再跑",
        )
    if code != 0 or not raw.get("success", True):
        raise RedGoError(
            f"XHS_API_{code}",
            f"小红书 API 返回业务错误：{raw.get('msg') or '未知错误'}",
            retryable=False,
            is_risk_control=True,
            suggested_action="先停止请求。若持续出现，账号可能被风控，需冷却观察",
        )


async def _json_or_raise(resp: Response) -> dict:
    if resp.status != 200:
        body = (await resp.text())[:300]
        if resp.status in (403, 406, 461):
            raise RedGoError(
                "RISK_CONTROL",
                f"API 返回 HTTP {resp.status}（请求被平台拦截），响应体：{body!r}",
                retryable=False,
                is_risk_control=True,
                suggested_action="立即停止请求并冷却。若反复出现，账号可能已被标记",
            )
        raise RedGoError(
            "HTTP_ERROR",
            f"API 返回 HTTP {resp.status}，响应体：{body!r}",
            retryable=resp.status >= 500,
            is_risk_control=False,
            suggested_action="5xx 可稍后重试一次；持续出现就停下检查 Chrome 窗口页面状态",
        )
    raw = await resp.json()
    _raise_for_api_error(raw)
    return raw


async def _assert_logged_in(context: BrowserContext) -> None:
    """行前轻量登录态校验：读本地 cookie，零网络请求。

    铁律：登录态失效返回明确错误，绝不静默返回空数据（血的教训：假数据当真）。
    """
    cookies = await context.cookies("https://www.xiaohongshu.com")
    if not any(c["name"] == "web_session" and c["value"] for c in cookies):
        raise RedGoError(
            "LOGIN_EXPIRED",
            "未检测到登录态（web_session cookie 缺失）",
            retryable=False,
            suggested_action=_LOGIN_REFRESH_HINT,
        )


async def _login_wall_visible(p: Page) -> bool:
    return await p.evaluate(
        """() => !!document.querySelector(
             '.login-container, [class*="login-modal"], .qrcode-img, [class*="login-box"]')"""
    )


async def _raise_capture_timeout(p: Page, code: str, what: str) -> None:
    """拦截窗空等时给出精确诊断：先看是不是登录墙，不是再报捕获超时。"""
    if await _login_wall_visible(p):
        raise RedGoError(
            "LOGIN_EXPIRED",
            f"{what}——页面跳到了登录墙",
            retryable=False,
            suggested_action=_LOGIN_REFRESH_HINT,
        )
    raise RedGoError(
        "CAPTURE_TIMEOUT",
        f"{what}（20 秒内未捕获，页面无登录墙）",
        retryable=True,
        suggested_action="到 Chrome 窗口看页面状态（验证码/异常提示）；可重试一次，再失败就停",
    )


def _structured_errors(fn):
    """兜底：未归类异常也转成结构化错误，agent 永远拿得到 {code,...} 可解析体。"""

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except RedGoError:
            raise
        except Exception as e:
            raise RedGoError(
                "INTERNAL",
                f"{type(e).__name__}: {e}",
                retryable=False,
                suggested_action="检查 Chrome 窗口与 MCP server 日志；问题持续请提 issue",
            ) from e

    return wrapper


async def _goto_and_capture(
    p: Page, url: str, api_path: str, timeout_ms: int = 20_000
) -> Response | None:
    """导航到目标页面，接住页面加载时发出的目标 API 响应。超时返回 None（页面可能走 SSR）。"""
    try:
        async with p.expect_response(
            lambda r: api_path in r.url, timeout=timeout_ms
        ) as resp_info:
            await p.goto(url, wait_until="domcontentloaded")
        return await resp_info.value
    except PlaywrightTimeoutError:
        return None


async def _ensure_fresh_navigation(p: Page, marker: str) -> None:
    """导航到与当前相同的 URL 时页面不会重新加载数据。

    若当前已在目标页（URL 含 marker），先回到发现页再进目标页，
    确保页面重新加载、目标响应能被接住。
    """
    if marker and marker in p.url:
        await p.goto("https://www.xiaohongshu.com/explore", wait_until="domcontentloaded")
        await _EXTS.hooks.after_action(p, "bounce")


def _current_search_keyword(p: Page) -> str:
    """从当前 URL 取搜索关键词（站点有时会双重转义，解两层）。"""
    if "search_result" not in p.url:
        return ""
    qs = urllib.parse.parse_qs(urllib.parse.urlsplit(p.url).query)
    kw = qs.get("keyword", [""])[0]
    return urllib.parse.unquote(urllib.parse.unquote(kw))


async def _read_note_state(p: Page, note_id: str) -> dict | None:
    """SSR 兜底：从 window.__INITIAL_STATE__ 取笔记详情条目（{note, comments}）。"""
    return await p.evaluate(
        """(id) => {
          const entry = window.__INITIAL_STATE__?.note?.noteDetailMap?.[id];
          if (!entry) return null;
          return JSON.parse(JSON.stringify(entry, (k, v) => v === undefined ? null : v));
        }""",
        note_id,
    )


def _require_token(xsec_token: str) -> None:
    if not xsec_token:
        raise RedGoError(
            "MISSING_XSEC_TOKEN",
            "缺少 xsec_token",
            suggested_action="xsec_token 必须取自 search_notes/get_creator_notes 的返回，不可凭空构造",
        )


@mcp.tool()
@_structured_errors
async def search_notes(keyword: str, page: int = 1, ctx: Context = None) -> SearchResult:
    """搜索小红书笔记，返回结构化笔记列表。

    每条结果带 xsec_token——后续查看笔记详情/评论必须透传它，不可凭 note_id 构造。
    """
    if page != 1:
        raise RedGoError(
            "NOT_IMPLEMENTED",
            "v1 阶段2 仅支持第 1 页（翻页靠滚动触发站点请求，后续实现）",
            suggested_action="先用 page=1",
        )
    app: AppCtx = ctx.request_context.lifespan_context
    await _assert_logged_in(app.context)
    async with app.guard.session():
        if _current_search_keyword(app.page) == keyword:
            await _ensure_fresh_navigation(app.page, "search_result")
        search_url = (
            "https://www.xiaohongshu.com/search_result"
            f"?keyword={urllib.parse.quote(keyword)}&source=web_explore_feed"
        )
        await _EXTS.hooks.before_action(app.page, "search")
        resp = await _goto_and_capture(app.page, search_url, _SEARCH_API)
        await _EXTS.hooks.after_action(app.page, "search")
    if resp is None:
        await _raise_capture_timeout(app.page, "CAPTURE_TIMEOUT", "搜索页加载后站点没有发起搜索请求")
    raw = await _json_or_raise(resp)
    items = raw.get("data", {}).get("items", [])
    notes = [n for n in (note_from_search_item(it) for it in items) if n is not None]
    return SearchResult(
        keyword=keyword,
        page=page,
        has_more=raw.get("data", {}).get("has_more", False),
        notes=notes,
    )


@mcp.tool()
@_structured_errors
async def get_note(note_id: str, xsec_token: str, ctx: Context = None) -> NoteDetail:
    """获取单条笔记详情（标题、正文、互动数、图片/视频地址、标签、发布时间）。

    xsec_token 必须用 search_notes 返回的那个，不可凭 note_id 构造。
    """
    _require_token(xsec_token)
    app: AppCtx = ctx.request_context.lifespan_context
    await _assert_logged_in(app.context)
    async with app.guard.session():
        p = app.page
        await _ensure_fresh_navigation(p, note_id)
        # 详情页整页加载通常走 SSR；feed API 拦截留 5 秒短窗兜 SPA 场景
        await _EXTS.hooks.before_action(p, "note")
        resp = await _goto_and_capture(p, note_url(note_id, xsec_token), _FEED_API, 5_000)
        await _EXTS.hooks.after_action(p, "note")
        if resp is not None:
            raw = await _json_or_raise(resp)
            items = raw.get("data", {}).get("items", [])
            if items:
                card = g(items[0], "note_card", {}) or {}
                return detail_from_note_obj(card, note_id, xsec_token)
        entry = await _read_note_state(p, note_id)
    note_obj = (entry or {}).get("note") or {}
    if not note_obj:
        if await _login_wall_visible(app.page):
            raise RedGoError(
                "LOGIN_EXPIRED",
                "笔记页跳到了登录墙",
                retryable=False,
                suggested_action=_LOGIN_REFRESH_HINT,
            )
        raise RedGoError(
            "NOTE_NOT_AVAILABLE",
            "页面上没有这条笔记的数据（feed 未捕获且 SSR 状态为空）",
            retryable=False,
            suggested_action="笔记可能已删除/不可见；确认 xsec_token 来自最近一次搜索结果",
        )
    return detail_from_note_obj(note_obj, note_id, xsec_token)


@mcp.tool()
@_structured_errors
async def get_comments(
    note_id: str, xsec_token: str, cursor: str = "", ctx: Context = None
) -> CommentsResult:
    """获取笔记的评论（首页）。xsec_token 必须来自 search_notes 结果。

    v1 已知边界：仅首页评论（深翻需滚动/点击触发站点请求，未实现）。
    """
    if cursor:
        raise RedGoError(
            "NOT_IMPLEMENTED",
            "当前版本仅支持首页评论，cursor 深翻分页未实现",
            suggested_action="先不传 cursor",
        )
    _require_token(xsec_token)
    app: AppCtx = ctx.request_context.lifespan_context
    await _assert_logged_in(app.context)
    async with app.guard.session():
        p = app.page
        await _ensure_fresh_navigation(p, note_id)
        await _EXTS.hooks.before_action(p, "comments")
        resp = await _goto_and_capture(p, note_url(note_id, xsec_token), _COMMENTS_API)
        await _EXTS.hooks.after_action(p, "comments")
        if resp is None:
            # SSR 兜底：评论可能已在初始状态里
            entry = await _read_note_state(p, note_id)
            comments_obj = (entry or {}).get("comments") or {}
            raw_list = comments_obj.get("list") or []
            if not raw_list and not comments_obj:
                await _raise_capture_timeout(p, "CAPTURE_TIMEOUT",
                                             "评论请求未捕获且 SSR 状态里也没有评论数据")
            return CommentsResult(
                note_id=note_id,
                comments=[comment_from_obj(c) for c in raw_list],
                cursor=str(g(comments_obj, "cursor", "") or ""),
                has_more=bool(g(comments_obj, "has_more", False)),
            )
    raw = await _json_or_raise(resp)
    data = raw.get("data", {})
    return CommentsResult(
        note_id=note_id,
        comments=[comment_from_obj(c) for c in data.get("comments", [])],
        cursor=str(data.get("cursor", "") or ""),
        has_more=bool(data.get("has_more", False)),
    )


@mcp.tool()
@_structured_errors
async def get_creator_notes(
    user_id: str, xsec_token: str, cursor: str = "", ctx: Context = None
) -> CreatorNotesResult:
    """获取某个创作者的笔记列表（首屏）。xsec_token 用该作者任一笔记的 token。

    v1 已知边界：仅首屏（深翻需滚动触发站点请求，未实现）。
    """
    if cursor:
        raise RedGoError(
            "NOT_IMPLEMENTED",
            "当前版本仅支持首屏，cursor 深翻分页未实现",
            suggested_action="先不传 cursor",
        )
    _require_token(xsec_token)
    app: AppCtx = ctx.request_context.lifespan_context
    await _assert_logged_in(app.context)
    async with app.guard.session():
        p = app.page
        await _ensure_fresh_navigation(p, user_id)
        await _EXTS.hooks.before_action(p, "profile")
        resp = await _goto_and_capture(p, profile_url(user_id, xsec_token), _USER_POSTED_API)
        await _EXTS.hooks.after_action(p, "profile")
        if resp is None:
            # SSR 兜底：个人页首屏笔记可能已在初始状态里
            state = await p.evaluate(
                """() => {
                  const u = window.__INITIAL_STATE__?.user;
                  if (!u || !u.notes) return null;
                  return JSON.parse(JSON.stringify(u.notes, (k, v) => v === undefined ? null : v));
                }"""
            )
            items = state[0] if (isinstance(state, list) and state and isinstance(state[0], list)) else (state or [])
            if not items:
                await _raise_capture_timeout(p, "CAPTURE_TIMEOUT",
                                             "作者笔记请求未捕获且 SSR 状态里也没有笔记数据")
            return CreatorNotesResult(
                user_id=user_id,
                notes=[note_from_posted_item(it) for it in items],
                cursor="",
                has_more=False,
            )
    raw = await _json_or_raise(resp)
    data = raw.get("data", {})
    return CreatorNotesResult(
        user_id=user_id,
        notes=[note_from_posted_item(it) for it in data.get("notes", [])],
        cursor=str(data.get("cursor", "") or ""),
        has_more=bool(data.get("has_more", False)),
    )


# 扩展包追加的 MCP 工具在此注册（开源版此列表恒为空）
for _registrar in _EXTS.tool_registrars:
    _registrar(mcp)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
