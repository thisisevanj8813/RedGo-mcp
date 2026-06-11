"""运行环境检查单测：用假环境验证能拦住不适合的运行方式。全离线。"""

import asyncio
import random
from datetime import datetime
from pathlib import Path

import pytest

import redgo.deploy as deploy
from redgo.errors import RedGoError
from redgo.guard import GuardConfig, RateGuard


def test_headless_ua_detection():
    assert deploy.is_headless_ua("Mozilla/5.0 ... HeadlessChrome/149.0.0.0 Safari/537.36")
    assert deploy.is_headless_ua("Mozilla/5.0 ... Chrome/149.0.0.0 ...") is False
    assert deploy.is_headless_ua("") is False


def test_classify_ip():
    assert deploy.classify_ip({"status": "success", "hosting": True, "proxy": False}) == "hosting"
    assert deploy.classify_ip({"status": "success", "hosting": False, "proxy": True}) == "proxy"
    assert deploy.classify_ip({"status": "success", "hosting": False, "proxy": False}) is None
    assert deploy.classify_ip({"status": "fail"}) is None  # 查询失败不误杀
    assert deploy.classify_ip({}) is None


class FakePage:
    def __init__(self, ua):
        self._ua = ua

    async def evaluate(self, _script):
        return self._ua


class FakeContext:
    def __init__(self, cookies=None):
        self._cookies = cookies or []

    async def cookies(self, _url):
        return self._cookies


def make_guard(tmp_path: Path) -> RateGuard:
    cfg = GuardConfig(state_path=tmp_path / "state.json")
    return RateGuard(cfg, now_fn=lambda: datetime(2026, 6, 11, 12, 0), rng=random.Random(0))


REAL_UA = "Mozilla/5.0 (Macintosh) Chrome/149.0.0.0 Safari/537.36"
HEADLESS_UA = "Mozilla/5.0 (Macintosh) HeadlessChrome/149.0.0.0 Safari/537.36"


def test_refuses_headless(tmp_path, monkeypatch):
    monkeypatch.setattr(deploy, "_fetch_ip_info_sync", lambda t: None)
    with pytest.raises(RedGoError) as ei:
        asyncio.run(deploy.run_deploy_checks(FakePage(HEADLESS_UA), FakeContext(), make_guard(tmp_path)))
    assert ei.value.code == "DEPLOY_HEADLESS"


def test_refuses_datacenter_ip(tmp_path, monkeypatch):
    monkeypatch.setattr(
        deploy, "_fetch_ip_info_sync",
        lambda t: {"status": "success", "hosting": True, "proxy": False, "query": "3.3.3.3"},
    )
    monkeypatch.delenv("REDGO_ALLOW_DATACENTER_IP", raising=False)
    with pytest.raises(RedGoError) as ei:
        asyncio.run(deploy.run_deploy_checks(FakePage(REAL_UA), FakeContext(), make_guard(tmp_path)))
    assert ei.value.code == "DEPLOY_DATACENTER_IP"


def test_datacenter_ip_env_escape_hatch(tmp_path, monkeypatch):
    monkeypatch.setattr(
        deploy, "_fetch_ip_info_sync",
        lambda t: {"status": "success", "hosting": True, "proxy": False, "query": "3.3.3.3"},
    )
    monkeypatch.setenv("REDGO_ALLOW_DATACENTER_IP", "1")
    asyncio.run(deploy.run_deploy_checks(FakePage(REAL_UA), FakeContext(), make_guard(tmp_path)))


def test_ip_lookup_failure_does_not_block(tmp_path, monkeypatch):
    monkeypatch.setattr(deploy, "_fetch_ip_info_sync", lambda t: None)
    asyncio.run(deploy.run_deploy_checks(FakePage(REAL_UA), FakeContext(), make_guard(tmp_path)))


def test_multi_account_warning(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(deploy, "_fetch_ip_info_sync", lambda t: None)
    guard = make_guard(tmp_path)
    ck1 = [{"name": "web_session", "value": "session-A"}]
    ck2 = [{"name": "web_session", "value": "session-B"}]
    with caplog.at_level("WARNING", logger="redgo.deploy"):
        asyncio.run(deploy.run_deploy_checks(FakePage(REAL_UA), FakeContext(ck1), guard))
        assert not any("不同登录会话" in r.message for r in caplog.records)
        asyncio.run(deploy.run_deploy_checks(FakePage(REAL_UA), FakeContext(ck2), guard))
        assert any("不同登录会话" in r.message for r in caplog.records)

    asyncio.run(run_noop())


async def run_noop():
    pass
