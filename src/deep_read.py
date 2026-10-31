"""全文精读：抓 arXiv HTML（兜底 PDF）-> 抽取正文与图 -> 并行结构化深读。"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed

import figures as figmod

DEEP_PROMPT = """你在为一位 VLBI 天体测量方向的研究生精读论文，他研究长周期暂现源，
关注干涉阵成像与射电望远镜技术，但没有天体物理专业背景。下面是论文全文（已去标签）及图表清单。

要求：
1. 只依据全文内容，不得引入外部知识补充事实；全文没写的写"文中未说明"。
2. 数值必须原样保留单位与误差；不确定就不写。
3. 重点提取：观测设置、数据处理链、误差来源与量级、结论的适用范围。
4. "与你研究的关系"要具体到可操作层面（可借鉴的方法、可复用的样本、可追问的问题）。
5. 术语首次出现时用括号给一句白话解释，避免堆砌行话。
6. 图表：仅当某张图对理解核心结果不可替代时才选中（最多 2 张），并说明它支持了哪个结论。
7. 中文输出，术语保留英文原词。只输出 JSON。"""

DEEP_FIELDS = """{
 "background": "研究背景与要解决的问题（3-5句，含必要的白话解释）",
 "method": "观测/数据与方法：望远镜、频段、时间跨度、样本量、定标与成像流程（3-6句）",
 "results": ["关键结果，每条一个要点，含数值与误差"],
 "conclusion": "作者结论与论证链（3-5句）",
 "limitations": "局限、假设与作者承认的注意事项（2-4句）",
 "relation": "与读者研究的关系：可借鉴的方法/可复用的数据/可追问的问题（3-5句）",
 "questions": ["值得追问的2-3个问题"],
 "key_numbers": ["最重要的3-6个数值，格式：物理量 = 数值 ± 误差 (条件)"],
 "key_figures": [{"n": 图号, "why": "这张图支撑了哪条结论"}]
}"""

MARKERS = (" References ", " Bibliography ", " Appendix ", " Acknowledgements ")


def _strip(html: str) -> str:
    html = re.sub(r"<(script|style|nav|header|footer)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    m = re.search(r"<article[^>]*>(.*?)</article>", html, flags=re.S | re.I)
    body = m.group(1) if m else html
    body = re.sub(r"<math[^>]*>.*?</math>", " ", body, flags=re.S | re.I)
    body = re.sub(r"<[^>]+>", " ", body)
    body = (body.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<")
                .replace("&gt;", ">").replace("&quot;", '"'))
    return re.sub(r"\s+", " ", body).strip()


def condense(text: str, max_chars: int) -> str:
    """超长时：先砍参考文献/附录，再保留「开头 + 结尾」，避免只读到引言。"""
    if len(text) <= max_chars:
        return text
    floor = int(len(text) * 0.30)
    cut = len(text)
    for mk in MARKERS:
        pos = text.find(mk, floor)
        if pos > 0:
            cut = min(cut, pos)
    body = text[:cut]
    if len(body) <= max_chars:
        return body
    head = int(max_chars * 0.62)
    tail = max_chars - head - 30
    return body[:head] + " …（中间省略）… " + body[-tail:]


def fetch_fulltext(session, arxiv_id: str, sources=("arxiv_html", "pdf")):
    """返回 (正文, 来源, 原始html, 页面URL)。页面URL用于解析图片相对路径。"""
    if "arxiv_html" in sources:
        try:
            r = session.get(f"https://arxiv.org/html/{arxiv_id}", timeout=45)
            if r.status_code == 200:
                text = _strip(r.text)
                if len(text) > 8000:
                    return text, "html", r.text, r.url
        except Exception:      # noqa: BLE001
            pass
    if "pdf" in sources:
        try:
            r = session.get(f"https://arxiv.org/pdf/{arxiv_id}", timeout=120)
            if r.status_code == 200 and r.content[:4] == b"%PDF":
                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as fh:
                    fh.write(r.content)
                    path = fh.name
                try:
                    out = subprocess.run(["pdftotext", "-q", "-layout", path, "-"],
                                         capture_output=True, timeout=120)
                    text = re.sub(r"\s+", " ", out.stdout.decode("utf-8", "ignore"))
                    if len(text) > 8000:
                        return text, "pdf", "", ""
                finally:
                    os.unlink(path)
        except Exception:      # noqa: BLE001
            pass
    return "", "", "", ""


def summarize_deep(client, paper: dict, text: str, figs: list[dict],
                   max_chars: int = 35000, log=print) -> dict | None:
    body = condense(text, max_chars)
    figlist = "\n".join(f"[图{f['n']}] {f['caption'][:300]}" for f in figs[:10]) or "（无可提取图表）"
    user = (f"标题: {paper['title']}\narXiv: {paper['arxiv_id']}\n\n"
            f"图表清单:\n{figlist}\n\n全文:\n{body}\n\n"
            f"输出 JSON 对象，字段如下：\n{DEEP_FIELDS}")
    try:
        data = client.chat_json(DEEP_PROMPT, user, log=log)
    except Exception as exc:      # noqa: BLE001
        log(f"[深读] {paper['arxiv_id']} 失败: {type(exc).__name__}")
        return None
    if not isinstance(data, dict) or not data.get("results"):
        return None
    return data


def _one(paper: dict, cfg: dict, base: dict, log):
    """单篇处理：抓全文 -> 抽图 -> LLM 深读 -> 下载入选图片。"""
    from fetch_arxiv import build_session
    from summarize import LLMClient

    dcfg = cfg.get("deep_read", {})
    session = build_session(cfg)
    text, src, raw, page_url = fetch_fulltext(
        session, paper["arxiv_id"], tuple(dcfg.get("sources", ["arxiv_html"])))
    if not text:
        log(f"[深读] {paper['arxiv_id']} 无全文，跳过")
        return paper["arxiv_id"], None, []

    figs = figmod.extract_figures(raw, page_url) if (raw and page_url) else []
    log(f"[深读] {paper['arxiv_id']} 全文 {len(text)} 字符（{src}），图 {len(figs)} 张")

    client = LLMClient(cfg, base["credentials"])
    client.endpoint = base["endpoint"]
    client.key = base["key"]
    client.models = list(base["models"])
    client.model = client.models[0]

    deep = summarize_deep(client, paper, text, figs, int(dcfg.get("max_chars", 35000)), log=log)
    if not deep:
        return paper["arxiv_id"], None, []
    deep["_source"] = src
    deep["_chars"] = len(text)
    deep["_model"] = client.model

    imgs = []
    fcfg = dcfg.get("figures", {}) or {}
    if fcfg.get("enabled") and figs:
        imgs = figmod.download(session, figs, deep.get("key_figures") or [],
                               int(fcfg.get("max_bytes", 2_000_000)), log=log)
        if imgs:
            log(f"[配图] {paper['arxiv_id']} 选中 {len(imgs)} 张")
    return paper["arxiv_id"], deep, imgs


def run(client, papers: list[dict], cfg: dict, log=print) -> None:
    """对 A/B 级（排除理论类）做全文精读，支持并行。"""
    dcfg = cfg.get("deep_read", {})
    if not dcfg.get("enabled"):
        return
    trigger = dcfg.get("trigger", "tier_A")
    if trigger == "tier_AB":
        tiers = {"A", "B"}
    elif trigger == "all":
        tiers = {"A", "B", "C"}
    else:
        tiers = {"A"}
    targets = [p for p in papers
               if p.get("tier") in tiers and (p.get("summary") or {}).get("kind") != "theory"]
    targets = targets[: int(dcfg.get("max_papers", 7))]
    if not targets:
        return

    base = {"credentials": client.credentials, "endpoint": client.endpoint,
            "key": client.key, "models": list(client.models)}
    workers = max(1, int(dcfg.get("parallel", 3)))
    results: dict[str, tuple] = {}

    if workers == 1:
        for p in targets:
            aid, deep, imgs = _one(p, cfg, base, log)
            results[aid] = (deep, imgs)
    else:
        log(f"[深读] 并行 {workers} 线程处理 {len(targets)} 篇")
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = {ex.submit(_one, p, cfg, base, log): p["arxiv_id"] for p in targets}
            for fut in as_completed(futures):
                try:
                    aid, deep, imgs = fut.result()
                    results[aid] = (deep, imgs)
                except Exception as exc:      # noqa: BLE001
                    log(f"[深读] 线程异常 {type(exc).__name__}: {exc}")

    for p in targets:
        deep, imgs = results.get(p["arxiv_id"], (None, []))
        if deep:
            p["deep"] = deep
        if imgs:
            p["figures"] = imgs