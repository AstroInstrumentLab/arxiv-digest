"""凭据与连通性预检：不发信、不改台账、不打印密钥。"""
from __future__ import annotations

import os
import smtplib
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import load  # noqa: E402
import secrets as creds  # noqa: E402
from summarize import LLMClient, LLMError  # noqa: E402

OK, BAD = "✅", "❌"


def main() -> int:
    cfg = load()
    print(f"凭据来源: {creds.describe()}")
    try:
        data = creds.load()
    except creds.CredentialError as exc:
        print(f"{BAD} {exc}")
        return 1

    for key in ("SMTP_USER", "MAIL_TO"):
        print(f"{OK} {key} = {data.get(key)}")
    print(f"{OK} SMTP_PASS = {creds.mask(data.get('SMTP_PASS',''))}")
    print(f"{OK} LLM_KEY_RELAY = {creds.mask(data.get('LLM_KEY_RELAY',''))}")
    print(f"{OK} LLM_KEY_DEEPSEEK = {creds.mask(data.get('LLM_KEY_DEEPSEEK',''))}")

    print("\n-- SMTP 登录测试 --")
    try:
        with smtplib.SMTP_SSL(cfg["mail"]["smtp"], int(cfg["mail"]["port"]), timeout=20) as s:
            s.login(data["SMTP_USER"], data["SMTP_PASS"])
            print(f"{OK} 登录成功 {cfg['mail']['smtp']}:{cfg['mail']['port']}")
    except Exception as exc:      # noqa: BLE001
        print(f"{BAD} SMTP 登录失败: {type(exc).__name__}: {exc}")

    print("\n-- LLM 端点探测 --")
    client = LLMClient(cfg, data)
    try:
        client.pick()
        print(f"{OK} 选用端点 {client.endpoint['name']} model={client.model}")
    except LLMError as exc:
        print(f"{BAD} {exc}")
        return 1

    print("\n-- 端到端小样（1 篇，消耗极少 token）--")
    sample = [{
        "arxiv_id": "0000.00000", "title": "Probing a long-period radio transient with VLBI astrometry",
        "abstract": ("We report phase-referenced VLBI observations of a long-period radio transient with the EVN. "
                     "The source shows a 18.18 min period and a proper motion upper limit of 5 mas/yr."),
        "categories": ["astro-ph.HE"], "primary_category": "astro-ph.HE",
    }]
    try:
        out = client.summarize(sample, short=True)
        item = out.get("0000.00000", {})
        print(f"{OK} 返回字段: {', '.join(k for k in item if item[k])[:120]}")
        print(f"    一句话: {item.get('one_liner','(空)')}")
    except LLMError as exc:
        print(f"{BAD} 摘要调用失败: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())