"""arXiv 召回：按时间窗抓取 astro-ph 全量并解析 Atom。

设计要点:
- 一次查询覆盖全部类目 (cat:A OR cat:B ...)，避免多类目重复返回；
- 分页 + 3 s 间隔，遵守 arXiv API 使用规范；
- 解析失败或该查询为空时，退化到逐类目查询。
"""
from __future__ import annotations

import datetime as dt
import time
import xml.etree.ElementTree as ET

import requests

ATOM = "{http://www.w3.org/2005/Atom}"
ARX = "{http://arxiv.org/schemas/atom}"


def build_session(cfg: dict) -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": cfg["arxiv"]["user_agent"],
        "Accept": "application/atom+xml",
    })
    return s


def _request(session: requests.Session, cfg: dict, params: dict) -> str:
    interval = float(cfg["arxiv"]["request_interval"])
    retries = int(cfg["arxiv"]["retries"])
    last = "unknown"
    for attempt in range(retries):
        try:
            resp = session.get(cfg["arxiv"]["api"], params=params, timeout=60)
            if resp.status_code == 200:
                time.sleep(interval)
                return resp.text
            last = f"HTTP {resp.status_code}"
            if resp.status_code in (429, 500, 502, 503, 504):
                time.sleep(max(interval, 3.0) * (2 ** attempt))
                continue
            resp.raise_for_status()
        except requests.RequestException as exc:
            last = repr(exc)
            time.sleep(max(interval, 3.0) * (2 ** attempt))
    raise RuntimeError(f"arXiv 请求失败 ({last})")


def _parse_ts(text: str) -> dt.datetime:
    return dt.datetime.strptime(text.strip(), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)


def _clean(text: str | None) -> str:
    return " ".join((text or "").split())


def parse_atom(xml_text: str) -> list[dict]:
    """把 Atom 响应解析成记录列表。"""
    root = ET.fromstring(xml_text)
    records: list[dict] = []
    for entry in root.findall(ATOM + "entry"):
        raw_id = (entry.findtext(ATOM + "id") or "").strip()
        if "/abs/" not in raw_id:
            continue
        tail = raw_id.split("/abs/", 1)[1]
        version = 1
        if "v" in tail:
            base, _, ver = tail.rpartition("v")
            if ver.isdigit():
                tail, version = base, int(ver)

        published = entry.findtext(ATOM + "published")
        updated = entry.findtext(ATOM + "updated")
        if not published:
            continue

        primary = entry.find(ARX + "primary_category")
        records.append({
            "arxiv_id": tail,
            "version": version,
            "title": _clean(entry.findtext(ATOM + "title")),
            "abstract": _clean(entry.findtext(ATOM + "summary")),
            "authors": [_clean(a.findtext(ATOM + "name")) for a in entry.findall(ATOM + "author")],
            "primary_category": primary.get("term") if primary is not None else "",
            "categories": [c.get("term") for c in entry.findall(ATOM + "category")],
            "published": _parse_ts(published).isoformat(),
            "updated": _parse_ts(updated).isoformat() if updated else _parse_ts(published).isoformat(),
            "comment": _clean(entry.findtext(ARX + "comment")),
            "journal_ref": _clean(entry.findtext(ARX + "journal_ref")),
            "doi": _clean(entry.findtext(ARX + "doi")),
            "abs_url": f"https://arxiv.org/abs/{tail}",
            "pdf_url": f"https://arxiv.org/pdf/{tail}",
        })
    return records


def _query_string(cfg: dict, start: dt.datetime, end: dt.datetime, categories: list[str]) -> str:
    cats = " OR ".join(f"cat:{c}" for c in categories)
    if len(categories) > 1:
        cats = f"({cats})"
    span = f"submittedDate:[{start:%Y%m%d%H%M} TO {end:%Y%m%d%H%M}]"
    return f"{cats} AND {span}"


def _fetch_one(session, cfg, query, start, log=print) -> list[dict]:
    page = int(cfg["arxiv"]["page_size"])
    max_pages = int(cfg["arxiv"]["max_pages"])
    out: list[dict] = []
    for page_no in range(max_pages):
        offset = page_no * page
        params = {
            "search_query": query,
            "start": offset,
            "max_results": page,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
        xml_text = _request(session, cfg, params)
        batch = parse_atom(xml_text)
        if not batch:
            break
        out.extend(batch)
        oldest = min(dt.datetime.fromisoformat(r["published"]) for r in batch)
        log(f"  page {page_no + 1}: +{len(batch)} (累计 {len(out)}), 最旧 {oldest:%Y-%m-%d %H:%M}Z")
        if len(batch) < page or oldest < start:
            break
    return out


def fetch_window(cfg: dict, start: dt.datetime, end: dt.datetime, log=print) -> list[dict]:
    """抓取时间窗内的全部 astro-ph 论文，按 arXiv ID 去重（保留最高版本）。"""
    session = build_session(cfg)
    categories = list(cfg["arxiv"]["categories"])
    query = _query_string(cfg, start, end, categories)
    log(f"查询: {query}")
    try:
        records = _fetch_one(session, cfg, query, start, log)
    except Exception as exc:  # 组合查询失败 -> 逐类目兜底
        log(f"合并查询失败 ({exc})，改为逐类目抓取")
        records = []
        for cat in categories:
            q = _query_string(cfg, start, end, [cat])
            try:
                records.extend(_fetch_one(session, cfg, q, start, log))
            except Exception as exc2:
                log(f"  类目 {cat} 失败: {exc2}")

    best: dict[str, dict] = {}
    for rec in records:
        cur = best.get(rec["arxiv_id"])
        if cur is None or rec["version"] > cur["version"]:
            best[rec["arxiv_id"]] = rec

    out = sorted(best.values(), key=lambda r: r["published"], reverse=True)
    inside = [r for r in out if dt.datetime.fromisoformat(r["published"]) >= start]
    log(f"抓取 {len(out)} 条，时间窗内 {len(inside)} 条")
    return inside