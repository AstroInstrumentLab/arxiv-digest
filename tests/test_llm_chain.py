"""模型链降级逻辑的确定性测试（不需要真实密钥/网络）。"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import requests  # noqa: E402

from summarize import LLMClient, LLMError  # noqa: E402


class FakeResp:
    def __init__(self, status: int, payload: dict):
        self.status_code = status
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")   # 与真实行为一致


class FakeSession:
    """models: 该端点返回的模型列表；也可传 {host: [models]} 区分不同端点。"""

    def __init__(self, models, fail_models: set[str] | None = None):
        self.models = models
        self.fail_models = fail_models or set()
        self.calls: list[str] = []

    def get(self, url, **kwargs):
        if isinstance(self.models, dict):
            host = url.split("://", 1)[-1].split("/", 1)[0]
            names = self.models.get(host, [])
        else:
            names = self.models
        return FakeResp(200, {"data": [{"id": m} for m in names]})

    def post(self, url, json=None, **kwargs):     # noqa: A002
        model = json["model"]
        self.calls.append(model)
        if model in self.fail_models:
            return FakeResp(404, {})
        return FakeResp(200, {"choices": [{"message": {"content": "{\"ok\": true}"}}]})


def make_cfg(models: list[str]) -> dict:
    return {
        "llm": {
            "probe_timeout": 1,
            "batch": 10,
            "temperature": 0.2,
            "endpoints": [
                {"name": "relay", "base_url": "https://relay.test/v1",
                 "dns_pin": None, "models": models, "key_env": "K1"},
                {"name": "official", "base_url": "https://official.test/v1",
                 "dns_pin": None, "models": ["deepseek-chat"], "key_env": "K2"},
            ],
        }
    }


def test_priority_order():
    c = LLMClient(make_cfg(["gpt-6.1-sol", "deepseek-v4.1-flash"]), {"K1": "x", "K2": "y"})
    c.session = FakeSession(["gpt-6.1-sol", "deepseek-v4.1-flash", "claude-opus-5"])
    c.pick(log=lambda *a: None)
    assert c.endpoint["name"] == "relay"
    assert c.models == ["gpt-6.1-sol", "deepseek-v4.1-flash"], c.models
    assert c.model == "gpt-6.1-sol"


def test_missing_primary_falls_back_to_second_model():
    c = LLMClient(make_cfg(["gpt-6.1-sol", "deepseek-v4.1-flash"]), {"K1": "x", "K2": "y"})
    c.session = FakeSession(["deepseek-v4.1-flash"])
    c.pick(log=lambda *a: None)
    assert c.models == ["deepseek-v4.1-flash"], c.models


def test_all_relay_models_missing_goes_to_official():
    c = LLMClient(make_cfg(["gpt-6.1-sol"]), {"K1": "x", "K2": "y"})
    c.session = FakeSession({"relay.test": ["something-else"],
                             "official.test": ["deepseek-chat"]})
    c.pick(log=lambda *a: None)
    assert c.endpoint["name"] == "official", c.endpoint
    assert c.models == ["deepseek-chat"]


def test_runtime_degrade_to_second_model():
    s = FakeSession(["gpt-6.1-sol", "deepseek-v4.1-flash"], fail_models={"gpt-6.1-sol"})
    c = LLMClient(make_cfg(["gpt-6.1-sol", "deepseek-v4.1-flash"]), {"K1": "x", "K2": "y"})
    c.session = s
    c.pick(log=lambda *a: None)
    out = c.chat_json("s", "u", log=lambda *a: None)
    assert out == {"ok": True}
    assert c.model == "deepseek-v4.1-flash", c.model
    assert s.calls == ["gpt-6.1-sol", "gpt-6.1-sol", "deepseek-v4.1-flash"], s.calls


def test_no_key_skips_endpoint():
    c = LLMClient(make_cfg(["gpt-6.1-sol"]), {"K2": "y"})
    c.session = FakeSession(["gpt-6.1-sol", "deepseek-chat"])
    c.pick(log=lambda *a: None)
    assert c.endpoint["name"] == "official"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"[OK]   {t.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"[FAIL] {t.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} 通过")
    raise SystemExit(1 if failed else 0)