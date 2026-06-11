"""结构化错误体系单测：str(err) 即 JSON、业务码映射、登录态校验。全离线。"""

import asyncio
import json

import pytest

from redgo.errors import RedGoError
from redgo.server import _assert_logged_in, _raise_for_api_error


def test_error_str_is_parseable_json():
    e = RedGoError("RISK_CONTROL", "风控拦截", retryable=False,
                      is_risk_control=True, suggested_action="停手冷却")
    parsed = json.loads(str(e))
    assert parsed == {
        "code": "RISK_CONTROL",
        "message": "风控拦截",
        "retryable": False,
        "is_risk_control": True,
        "suggested_action": "停手冷却",
    }
    assert "风控" in str(e)  # ensure_ascii=False，中文不转义


@pytest.mark.parametrize("biz_code,expect_code,expect_risk", [
    (-100, "LOGIN_EXPIRED", False),
    (-101, "LOGIN_EXPIRED", False),
    (300011, "RISK_CONTROL", True),   # 实测撞过：当前账号存在异常
    (300012, "RISK_CONTROL", True),
    (300013, "RISK_CONTROL", True),
    (-510001, "XHS_API_-510001", True),  # 未知业务错误兜底
])
def test_api_error_mapping(biz_code, expect_code, expect_risk):
    with pytest.raises(RedGoError) as ei:
        _raise_for_api_error({"code": biz_code, "success": False, "msg": "x"})
    assert ei.value.code == expect_code
    assert ei.value.is_risk_control == expect_risk
    assert ei.value.suggested_action  # 每个错误必须告诉 agent 下一步干什么


def test_api_success_passes():
    _raise_for_api_error({"code": 0, "success": True, "data": {}})


class FakeContext:
    def __init__(self, cookies):
        self._cookies = cookies

    async def cookies(self, _url):
        return self._cookies


def test_assert_logged_in():
    ok = FakeContext([{"name": "web_session", "value": "abc"}])
    asyncio.run(_assert_logged_in(ok))  # 不抛

    for cookies in ([], [{"name": "web_session", "value": ""}], [{"name": "a1", "value": "x"}]):
        with pytest.raises(RedGoError) as ei:
            asyncio.run(_assert_logged_in(FakeContext(cookies)))
        assert ei.value.code == "LOGIN_EXPIRED"
        assert "刷新" in ei.value.suggested_action or "登录" in ei.value.suggested_action
