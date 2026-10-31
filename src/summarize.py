"""LLM 摘要层：端点链（中转站 -> 官方）+ 批量 + JSON 校验 + 降级。"""
from __future__ import annotations

import json
import re
import socket
import time
from contextlib import contextmanager

import requests

_ORIG_GETADDRINFO = socket.getaddrinfo


class LLMError(RuntimeError):
    pass


@contextmanager
def dns_pin(host: str | None, ip: str | None):
    """在上下文内把 host 的解析钉到 ip，TLS SNI / 证书校验仍用原域名。"""
    if not host or not ip:
        yield
        return

    def patched(h, *args, **kwargs):
        return _ORIG_GETADDRINFO(ip if h == host else h, *args, **kwargs)

    socket.getaddrinfo = patched
    try:
        yield
    finally:
        socket.getaddrinfo = _ORIG_GETADDRINFO


SYSTEM_PROMPT = """你是射电天文学文献分析助手。读者是 VLBI 天体测量方向的研究生，
研究长周期暂现源，同时关注干涉阵成像与射电望远镜技术。

规则：
1. 只依据给出的标题、摘要、类目判断，禁止补充摘要里没有的事实、数值或动机。
2. 摘要未给出的信息写"摘要未给出"，不得猜测。
3. relation 必须落到以下四条主线之一：长周期/暂现源、VLBI天体测量、干涉阵成像、射电望远镜技术。
   若无法落到任何一条，则 relevant=false。
4. tier 判定（按读者研究方向，不是按论文学术价值）：
   - A：研究对象是具体的暂现源/长周期源（LPT、重复FRB、TDE、AGN耀发等）并给出观测、
        天体测量或成像约束；或提供了读者可直接复用的 VLBI / 干涉成像方法。
   - B：与四条主线相关但属间接支撑（样本统计、校准流程、巡天目录、仪器进展等）。
   - C：纯理论或数值模拟，或仅有背景意义。
5. kind 判定（用于控制理论类占比）：
   - observation：有实测数据（观测、巡天、样本分析）
   - theory：纯理论或数值模拟，无实测数据
   - method：算法、成像/定标/数据处理方法
   - instrument：仪器、硬件、后端、阵列建设
   - review：综述
6. 读者没有天体物理背景。若 kind=theory，必须给出 bg_note：用本科物理能懂的语言写 3-4 句，
   依次说明①这项工作依赖的核心概念②它在回答什么问题③与实际观测/读者能用到的东西有何关系。
   若 kind≠theory，bg_note 置为空字符串。
7. 中文输出，专业术语保留英文原词。
8. 只输出 JSON，不要任何解释性文字。"""

SCHEMA_HINT = """输出 JSON 对象: {"items": [
 {"arxiv_id": "原样返回", "relevant": true/false, "tier": "A|B|C",
  "one_liner": "一句话：做了什么+得到什么",
  "conclusion": "作者结论：这项工作说明了什么",
  "data": "数据与观测：望远镜/频段/时长/样本量",
  "result": "关键结果：具体数值或上限",
  "relation": "与读者方向的关系（写明落到哪条主线）",
  "action": "精读|关注|略过",
  "kind": "observation|theory|method|instrument|review",
  "bg_note": "仅 kind=theory 时填写，否则空字符串",
  "tags": ["不超过3个短语"]}
]}"""


def build_prompt(papers: list[dict], short: bool = False) -> str:
    blocks = []
    for i, p in enumerate(papers, 1):
        blocks.append(
            f"[{i}] arxiv_id: {p['arxiv_id']}\n"
            f"title: {p['title']}\n"
            f"categories: {', '.join(p.get('categories', [])[:4])}\n"
            f"abstract: {p['abstract'][:2200]}"
        )
    if short:
        instr = ("只输出以下字段，键名严格为：arxiv_id（必须原样返回，不可省略）、"
                 "one_liner、result、relation、action；其余字段省略。"
                 "one_liner 必须是一句话，概括做了什么并给出结论，不超过 60 字。")
    else:
        instr = ("输出全部字段。one_liner 为一句话概括（<=60 字）；conclusion 是作者结论，"
                 "result 是具体数值；两者不得重复。")
    return f"{instr}\n\n" + "\n\n".join(blocks) + "\n\n" + SCHEMA_HINT


class LLMClient:
    def __init__(self, cfg: dict, credentials: dict):
        self.cfg = cfg
        self.credentials = credentials
        self.session = requests.Session()
        self.session.trust_env = False          # 忽略系统代理，避免 127.0.0.1:7897 干扰
        self.endpoint: dict | None = None
        self.key: str | None = None
        self.model: str | None = None
        self.models: list[str] = []
        self.calls = 0

    # ---------- 端点选择 ----------
    @staticmethod
    def _wanted(ep: dict) -> list[str]:
        """端点期望的模型优先级列表；兼容旧的单个 model 字段。"""
        if ep.get("models"):
            return [m for m in ep["models"] if m]
        m = ep.get("model")
        return [m] if m and m != "TO_CONFIRM" else []

    def _probe(self, ep: dict, key: str) -> tuple[bool, str, list[str]]:
        base = ep["base_url"].rstrip("/")
        timeout = float(self.cfg["llm"].get("probe_timeout", 4))
        try:
            with dns_pin(ep.get("host") or _host(base), ep.get("dns_pin")):
                r = self.session.get(f"{base}/models", timeout=timeout,
                                     headers={"Authorization": f"Bearer {key}"})
        except requests.RequestException as exc:
            return False, type(exc).__name__, []
        if r.status_code != 200:
            return False, f"HTTP {r.status_code}", []
        try:
            names = [m.get("id") for m in r.json().get("data", []) if m.get("id")]
        except Exception:
            names = []

        wanted = self._wanted(ep)
        if names:
            queue = [m for m in wanted if m in names]
            if not queue and wanted:
                return False, f"模型不可用({', '.join(wanted)})", []
            if not queue:
                queue = names[:1]
        else:
            queue = wanted or ["default"]
        missing = [m for m in wanted if m not in names]
        detail = " -> ".join(queue) + (f"  (缺失: {', '.join(missing)})" if missing else "")
        return True, detail, queue

    def pick(self, log=print) -> None:
        tried = []
        for ep in self.cfg["llm"]["endpoints"]:
            key = self.credentials.get(ep.get("key_env", ""))
            if not key:
                tried.append(f"{ep['name']}(无key)")
                continue
            ok, detail, queue = self._probe(ep, key)
            if ok and queue:
                self.endpoint, self.key = ep, key
                self.models = list(queue)
                self.model = self.models[0]
                log(f"[LLM] 端点={ep['name']} 模型链={ ' -> '.join(self.models) }")
                return
            tried.append(f"{ep['name']}({detail})")
        raise LLMError("LLM 端点全部不可用: " + "; ".join(tried))

    # ---------- 调用 ----------
    def chat_json(self, system: str, user: str, log=print) -> dict:
        if not self.endpoint:
            raise LLMError("尚未选择端点，先调用 pick()")
        base = self.endpoint["base_url"].rstrip("/")
        models = list(self.models) or [self.model]
        last = "unknown"
        for model in models:
            payload = {
                "model": model,
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": user}],
                "temperature": float(self.cfg["llm"].get("temperature", 0.2)),
                "response_format": {"type": "json_object"},
            }
            for attempt in range(2):
                try:
                    self.calls += 1
                    with dns_pin(self.endpoint.get("host") or _host(base), self.endpoint.get("dns_pin")):
                        r = self.session.post(f"{base}/chat/completions", json=payload, timeout=180,
                                              headers={"Authorization": f"Bearer {self.key}"})
                    if r.status_code == 400 and "response_format" in payload:
                        payload.pop("response_format", None)   # 部分中转不支持，去掉重试
                        last = f"{model}: HTTP 400 (response_format)"
                        continue
                    r.raise_for_status()
                    content = r.json()["choices"][0]["message"]["content"]
                    if model != self.model:
                        log(f"[LLM] 降级到 {model}")
                    self.model = model
                    return json.loads(content)
                except (requests.RequestException, KeyError, IndexError, json.JSONDecodeError) as exc:
                    last = f"{model}: {type(exc).__name__}: {exc}"
                    time.sleep(2 + attempt * 2)
        raise LLMError(f"LLM 调用失败: {last}")

    # ---------- 摘要 ----------
    def summarize(self, papers: list[dict], short: bool = False, log=print) -> dict[str, dict]:
        batch = int(self.cfg["llm"].get("batch", 10))
        out: dict[str, dict] = {}
        for i in range(0, len(papers), batch):
            chunk = papers[i:i + batch]
            log(f"[LLM] 批次 {i // batch + 1}/{(len(papers) + batch - 1) // batch}: {len(chunk)} 篇")
            try:
                data = self.chat_json(SYSTEM_PROMPT, build_prompt(chunk, short=short))
                items = data.get("items", []) if isinstance(data, dict) else []
            except LLMError as exc:
                log(f"[LLM] 批次失败，逐篇重试: {exc}")
                items = []
                for p in chunk:
                    try:
                        single = self.chat_json(SYSTEM_PROMPT, build_prompt([p], short=short))
                        items.extend(single.get("items", []))
                    except LLMError as exc2:
                        log(f"[LLM] {p['arxiv_id']} 失败: {exc2}")
            known = {p["arxiv_id"] for p in chunk}
            for idx, item in enumerate(items):
                aid = str(item.get("arxiv_id", "") or "").strip()
                if aid:
                    aid = aid.split("/")[-1]
                    aid = re.sub(r"v\d+$", "", aid)
                if aid in known:
                    out[aid] = item
                elif len(chunk) == 1:
                    out[chunk[0]["arxiv_id"]] = item          # 单篇：直接对应
                elif len(items) == len(chunk):
                    out[chunk[idx]["arxiv_id"]] = item        # 数量相等：按顺序对应
                else:
                    log(f"[LLM] 无法归属的返回项: arxiv_id={aid or '(空)'}")
        return out


def _host(url: str) -> str:
    return url.split("://", 1)[-1].split("/", 1)[0]