"""pydantic 模型 + 字段归一化。

tool 直接返回 BaseModel → FastMCP 自动生成 output schema 并填 structuredContent。
铁律：数字归一化（"1.2万" → 12000）、不准 JSON 字符串塞 text。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, Field

_UNIT_MULTIPLIERS = {"万": 10_000, "亿": 100_000_000}
_CST = timezone(timedelta(hours=8))  # 小红书时间按北京时间标注
# 小红书在数值为 0 时会用占位文案代替数字
_PLACEHOLDER_WORDS = {"赞", "收藏", "评论", "分享", "点赞"}


def normalize_count(raw: object) -> int:
    """把小红书的展示型计数归一成 int："1.2万" → 12000、"10万+" → 100000、"赞"/"" → 0。"""
    if raw is None:
        return 0
    if isinstance(raw, (int, float)):
        return int(raw)
    s = str(raw).strip().replace(",", "")
    if not s or s in _PLACEHOLDER_WORDS:
        return 0
    s = s.rstrip("+")
    multiplier = 1
    if s and s[-1] in _UNIT_MULTIPLIERS:
        multiplier = _UNIT_MULTIPLIERS[s[-1]]
        s = s[:-1]
    try:
        return int(float(s) * multiplier)
    except ValueError:
        return 0


def normalize_timestamp(raw: object) -> str:
    """毫秒（或秒）级时间戳 → ISO 8601（+08:00）。无效输入返回空串。"""
    try:
        ms = int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return ""
    if ms <= 0:
        return ""
    if ms < 10**12:  # 秒级兜底
        ms *= 1000
    return datetime.fromtimestamp(ms / 1000, tz=_CST).isoformat(timespec="seconds")


class Note(BaseModel):
    """搜索结果里的一条笔记（列表卡片粒度）。"""

    note_id: str
    xsec_token: str = Field(
        description="下游 get_note/get_comments 必需的令牌，只能来自本搜索结果，不可凭 note_id 构造"
    )
    title: str = ""
    note_type: str = Field(default="normal", description="normal=图文，video=视频")
    author_id: str = ""
    author_nickname: str = ""
    liked_count: int = Field(default=0, description="点赞数，已归一化为整数")
    url: str = Field(default="", description="可直接打开的笔记网页链接（已带 xsec_token）")


class SearchResult(BaseModel):
    keyword: str
    page: int
    has_more: bool = False
    notes: list[Note]


class NoteDetail(BaseModel):
    """单条笔记的完整详情。"""

    note_id: str
    xsec_token: str
    title: str = ""
    desc: str = Field(default="", description="正文文本")
    note_type: str = "normal"
    author_id: str = ""
    author_nickname: str = ""
    liked_count: int = 0
    collected_count: int = 0
    comment_count: int = 0
    share_count: int = 0
    published_at: str = Field(default="", description="发布时间，ISO 8601（+08:00）")
    ip_location: str = ""
    tags: list[str] = []
    image_urls: list[str] = []
    video_url: str = Field(default="", description="视频类笔记的播放地址，图文笔记为空")
    url: str = ""


class Comment(BaseModel):
    comment_id: str
    content: str = ""
    author_id: str = ""
    author_nickname: str = ""
    liked_count: int = 0
    sub_comment_count: int = Field(default=0, description="楼中楼回复数")
    published_at: str = ""
    ip_location: str = ""


class CommentsResult(BaseModel):
    note_id: str
    comments: list[Comment]
    cursor: str = Field(default="", description="下一页游标（v1 深翻未实现，仅透传）")
    has_more: bool = False


class CreatorNotesResult(BaseModel):
    user_id: str
    notes: list[Note]
    cursor: str = ""
    has_more: bool = False
