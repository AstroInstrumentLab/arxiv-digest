"""从 arXiv HTML 抽取图与图注，并下载入选图片。"""
from __future__ import annotations

import re
from urllib.parse import urljoin

FIG_RE = re.compile(r"<figure[^>]*>(.*?)</figure>", re.S | re.I)
IMG_RE = re.compile(r"<img[^>]+src=\"([^\"]+)\"", re.I)
CAP_RE = re.compile(r"<figcaption[^>]*>(.*?)</figcaption>", re.S | re.I)


def _clean(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s)
    s = (s.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<")
          .replace("&gt;", ">").replace("&quot;", '"'))
    return re.sub(r"\s+", " ", s).strip()


def extract_figures(html: str, base_url: str, limit: int = 10) -> list[dict]:
    """返回 [{n, url, caption}]，按出现顺序编号。"""
    out = []
    for block in FIG_RE.findall(html or ""):
        m = IMG_RE.search(block)
        if not m:
            continue
        cap = CAP_RE.search(block)
        caption = _clean(cap.group(1)) if cap else ""
        if len(caption) < 20:            # 跳过装饰性图片
            continue
        out.append({"n": len(out) + 1, "url": urljoin(base_url, m.group(1)), "caption": caption})
        if len(out) >= limit:
            break
    return out


def cid(arxiv_id: str, n: int) -> str:
    """邮件内嵌图片的 Content-ID，渲染与发送两侧必须一致。"""
    return f"fig_{arxiv_id.replace('.', '')}_{n}@vlbi-digest"

def download(session, figures: list[dict], picked: list[dict], max_bytes: int = 2_000_000,
             log=print) -> list[dict]:
    """按 LLM 的选择下载图片，返回带 data/mime/cid 的列表。"""
    by_n = {f["n"]: f for f in figures}
    out = []
    for item in picked or []:
        try:
            n = int(item.get("n"))
        except (TypeError, ValueError):
            continue
        fig = by_n.get(n)
        if not fig:
            continue
        try:
            r = session.get(fig["url"], timeout=60)
            ctype = r.headers.get("Content-Type", "").split(";")[0].strip().lower()
            if r.status_code != 200 or not ctype.startswith("image/"):
                log(f"[配图] 图{n} 跳过（HTTP {r.status_code}, {ctype or 'no-type'}）")
                continue
            if len(r.content) > max_bytes:
                log(f"[配图] 图{n} 跳过（{len(r.content)/1e6:.1f} MB 过大）")
                continue
            if len(r.content) < 3000:     # 占位图/极小图
                continue
            out.append({"n": n, "why": item.get("why", ""), "caption": fig["caption"],
                        "data": r.content, "mime": ctype})
        except Exception as exc:          # noqa: BLE001
            log(f"[配图] 图{n} 下载失败: {type(exc).__name__}")
    return out