"""parse/models：发布时间角标解析 + 搜索结果字段映射。"""

from datetime import datetime, timedelta, timezone

from redgo.models import normalize_publish_date
from redgo.parse import note_from_search_item, publish_date_from_card

_CST = timezone(timedelta(hours=8))
# 固定"现在"，让相对时间断言可复现
NOW = datetime(2026, 6, 11, 10, 0, tzinfo=_CST)


class TestNormalizePublishDate:
    def test_relative_days(self):
        assert normalize_publish_date("3天前", now=NOW) == "2026-06-08"
        assert normalize_publish_date("1天前", now=NOW) == "2026-06-10"

    def test_fixed_words(self):
        assert normalize_publish_date("刚刚", now=NOW) == "2026-06-11"
        assert normalize_publish_date("今天", now=NOW) == "2026-06-11"
        assert normalize_publish_date("昨天", now=NOW) == "2026-06-10"
        assert normalize_publish_date("前天", now=NOW) == "2026-06-09"

    def test_relative_hours_minutes(self):
        assert normalize_publish_date("2小时前", now=NOW) == "2026-06-11"
        assert normalize_publish_date("30分钟前", now=NOW) == "2026-06-11"
        # 跨午夜：10 点往回 11 小时是昨天
        assert normalize_publish_date("11小时前", now=NOW) == "2026-06-10"

    def test_month_day_this_year(self):
        assert normalize_publish_date("03-22", now=NOW) == "2026-03-22"

    def test_month_day_rolls_to_last_year(self):
        assert normalize_publish_date("12-30", now=NOW) == "2025-12-30"

    def test_full_date_passthrough(self):
        assert normalize_publish_date("2024-12-01", now=NOW) == "2024-12-01"

    def test_unrecognized_returns_empty(self):
        assert normalize_publish_date("广告", now=NOW) == ""
        assert normalize_publish_date("", now=NOW) == ""
        assert normalize_publish_date(None, now=NOW) == ""
        assert normalize_publish_date("13-45", now=NOW) == ""
        assert normalize_publish_date("2024-13-45", now=NOW) == ""


def _search_item(corner_tags=None):
    return {
        "model_type": "note",
        "id": "65a1000000000000000000aa",
        "xsec_token": "ABtok",
        "note_card": {
            "display_title": "测试笔记",
            "type": "normal",
            "user": {"user_id": "u1", "nickname": "小明"},
            "interact_info": {"liked_count": "1.2万"},
            **({"corner_tag_info": corner_tags} if corner_tags is not None else {}),
        },
    }


class TestSearchItemPublishedAt:
    def test_carries_publish_time_tag(self):
        note = note_from_search_item(
            _search_item([{"type": "publish_time", "text": "2024-12-01"}])
        )
        assert note.published_at == "2024-12-01"
        assert note.liked_count == 12000

    def test_no_corner_tag_is_empty(self):
        assert note_from_search_item(_search_item()).published_at == ""

    def test_ignores_other_tag_types(self):
        note = note_from_search_item(
            _search_item([{"type": "location", "text": "深圳"}])
        )
        assert note.published_at == ""

    def test_camel_case_ssr_card(self):
        # SSR 兜底是 camelCase 键名
        card = {"cornerTagInfo": [{"type": "publish_time", "text": "2024-12-01"}]}
        assert publish_date_from_card(card) == "2024-12-01"
