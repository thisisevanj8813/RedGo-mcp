"""字段解析层。

同一份数据有两个可能来源，键名风格不同，统一在这里兼容：
- API 响应：snake_case，如 interact_info.liked_count
- SSR 状态（window.__INITIAL_STATE__ 兜底）：camelCase，如 interactInfo.likedCount
"""

from __future__ import annotations

import urllib.parse

from .models import (
    Comment,
    Note,
    NoteDetail,
    normalize_count,
    normalize_timestamp,
)


def _camel(snake: str) -> str:
    head, *rest = snake.split("_")
    return head + "".join(w.capitalize() for w in rest)


def g(d: dict, snake: str, default=None):
    """按 snake_case 取值，取不到时退 camelCase。"""
    if not isinstance(d, dict):
        return default
    if snake in d:
        return d[snake]
    return d.get(_camel(snake), default)


def note_url(note_id: str, xsec_token: str, source: str = "pc_search") -> str:
    if not (note_id and xsec_token):
        return ""
    return (
        f"https://www.xiaohongshu.com/explore/{note_id}"
        f"?xsec_token={urllib.parse.quote(xsec_token)}&xsec_source={source}"
    )


def profile_url(user_id: str, xsec_token: str) -> str:
    return (
        f"https://www.xiaohongshu.com/user/profile/{user_id}"
        f"?xsec_token={urllib.parse.quote(xsec_token)}&xsec_source=pc_note"
    )


def note_from_search_item(item: dict) -> Note | None:
    """搜索结果 item（API snake_case）→ Note。非笔记类卡片返回 None。"""
    if g(item, "model_type") != "note":
        return None
    card = g(item, "note_card", {}) or {}
    user = g(card, "user", {}) or {}
    nid = item.get("id", "")
    token = g(item, "xsec_token", "") or ""
    return Note(
        note_id=nid,
        xsec_token=token,
        title=g(card, "display_title", "") or "",
        note_type=g(card, "type", "normal") or "normal",
        author_id=g(user, "user_id", "") or "",
        author_nickname=g(user, "nickname") or g(user, "nick_name") or "",
        liked_count=normalize_count(g(g(card, "interact_info", {}) or {}, "liked_count")),
        url=note_url(nid, token),
    )


def note_from_posted_item(item: dict) -> Note:
    """user_posted API 的 notes item / 个人页 SSR 的笔记卡 → Note。"""
    # API 直接平铺；SSR 兜底时卡片包在 note_card 里
    card = g(item, "note_card") or item
    user = g(card, "user", {}) or {}
    nid = g(item, "note_id") or item.get("id", "") or g(card, "note_id") or ""
    token = g(item, "xsec_token", "") or g(card, "xsec_token", "") or ""
    return Note(
        note_id=nid,
        xsec_token=token,
        title=g(card, "display_title", "") or "",
        note_type=g(card, "type", "normal") or "normal",
        author_id=g(user, "user_id", "") or "",
        author_nickname=g(user, "nickname") or g(user, "nick_name") or "",
        liked_count=normalize_count(g(g(card, "interact_info", {}) or {}, "liked_count")),
        url=note_url(nid, token, source="pc_user"),
    )


def _video_url(note: dict) -> str:
    media = g(g(note, "video", {}) or {}, "media", {}) or {}
    stream = g(media, "stream", {}) or {}
    h264 = stream.get("h264") or []
    if h264 and isinstance(h264, list):
        return g(h264[0], "master_url", "") or ""
    return ""


def detail_from_note_obj(note: dict, note_id: str, xsec_token: str) -> NoteDetail:
    """笔记详情对象（feed API 的 items[0].note_card 或 SSR noteDetailMap[id].note）→ NoteDetail。"""
    user = g(note, "user", {}) or {}
    interact = g(note, "interact_info", {}) or {}
    images = [
        u for u in (g(img, "url_default", "") for img in (g(note, "image_list") or []))
        if u
    ]
    tags = [t for t in (g(tag, "name", "") for tag in (g(note, "tag_list") or [])) if t]
    return NoteDetail(
        note_id=note_id,
        xsec_token=xsec_token,
        title=g(note, "title", "") or "",
        desc=g(note, "desc", "") or "",
        note_type=g(note, "type", "normal") or "normal",
        author_id=g(user, "user_id", "") or "",
        author_nickname=g(user, "nickname") or g(user, "nick_name") or "",
        liked_count=normalize_count(g(interact, "liked_count")),
        collected_count=normalize_count(g(interact, "collected_count")),
        comment_count=normalize_count(g(interact, "comment_count")),
        share_count=normalize_count(g(interact, "share_count")),
        published_at=normalize_timestamp(g(note, "time")),
        ip_location=g(note, "ip_location", "") or "",
        tags=tags,
        image_urls=images,
        video_url=_video_url(note),
        url=note_url(note_id, xsec_token),
    )


def comment_from_obj(c: dict) -> Comment:
    """评论对象（comment/page API 或 SSR comments.list）→ Comment。"""
    user = g(c, "user_info", {}) or {}
    return Comment(
        comment_id=c.get("id", ""),
        content=g(c, "content", "") or "",
        author_id=g(user, "user_id", "") or "",
        author_nickname=g(user, "nickname") or g(user, "nick_name") or "",
        liked_count=normalize_count(g(c, "like_count")),
        sub_comment_count=normalize_count(g(c, "sub_comment_count")),
        published_at=normalize_timestamp(g(c, "create_time")),
        ip_location=g(c, "ip_location", "") or "",
    )
