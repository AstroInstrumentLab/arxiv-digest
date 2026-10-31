"""规则打分（无 LLM 成本）。

分数结构（上限 90）:
  主题 0-30 + 方法 0-30 + 设备 0-15 + 标题加成 0-5 + 时效 0-5 + 完备性 0-5 - 负向 0-20
"""
from __future__ import annotations

import re

_WORD_RE_CACHE: dict[tuple[str, bool], re.Pattern] = {}


def _word_re(word: str, case_sensitive: bool) -> re.Pattern:
    key = (word, case_sensitive)
    pat = _WORD_RE_CACHE.get(key)
    if pat is None:
        flags = 0 if case_sensitive else re.IGNORECASE
        pat = re.compile(r"(?<![A-Za-z0-9])" + re.escape(word) + r"(?![A-Za-z0-9])", flags)
        _WORD_RE_CACHE[key] = pat
    return pat


def _hit_phrase(text: str, keyword: str, case_sensitive: bool = False) -> bool:
    """keyword 支持用 | 分隔同义词；含空格/连字符/斜杠的按子串匹配，否则按整词匹配。"""
    hay = text if case_sensitive else text.lower()
    for variant in keyword.split("|"):
        variant = variant.strip()
        if not variant:
            continue
        needle = variant if case_sensitive else variant.lower()
        if " " in needle or "-" in needle or "/" in needle:
            if needle in hay:
                return True
        elif _word_re(needle, case_sensitive).search(text):
            return True
    return False


def _hits(text: str, keywords: list[str], case_sensitive: bool = False) -> set[str]:
    return {k.split("|")[0] for k in keywords if _hit_phrase(text, k, case_sensitive)}


def score_paper(paper: dict, cfg: dict) -> dict:
    kw = cfg["keywords"]
    w = cfg["weights"]
    title = paper.get("title", "")
    abstract = paper.get("abstract", "")
    body = f"{title}\n{abstract}"

    src = _hits(body, kw.get("source", []))
    ast_core = _hits(body, kw.get("astrometry_core", kw.get("astrometry", [])))
    ast_gen = _hits(body, kw.get("astrometry_generic", []))
    img_core = _hits(body, kw.get("imaging_core", kw.get("imaging", [])))
    img_gen = _hits(body, kw.get("imaging_generic", []))
    ast = ast_core | ast_gen
    img = img_core | img_gen
    # 设备名大小写敏感：避免 FAST 命中 "fast radio burst"、SKA 命中其他缩写
    fac = _hits(body, kw.get("facility", []), case_sensitive=True)
    neg = _hits(body, kw.get("negative", []))
    inst = _hits(body, kw.get("instrument", []))
    inst_core = _hits(body, kw.get("instrument_core", []))
    inst_ctx = _hits(body, kw.get("instrument_context", []))
    theo = _hits(body, kw.get("theory", []))

    priority = set(kw.get("facility_priority", []))
    s_source = min(len(src) * int(w["source_per_hit"]), int(w["source_cap"]))
    # 核心词全权重、泛化词半权重：压低 Gaia 视差 / 光学干涉这类同词不同域
    s_method = min(
        len(ast_core) * int(w.get("astrometry_core_hit", 12))
        + len(ast_gen) * int(w.get("astrometry_generic_hit", 6))
        + len(img_core) * int(w.get("imaging_core_hit", 10))
        + len(img_gen) * int(w.get("imaging_generic_hit", 5)),
        int(w["method_cap"]),
    )
    s_facility = min(
        sum(int(w["facility_priority_hit"]) if f in priority else int(w["facility_per_hit"]) for f in fac),
        int(w["facility_cap"]),
    )
    s_title = int(w["title_bonus"]) if _hits(title, kw.get("source", [])) else 0
    # 交叉加成：既谈源又谈方法（天体测量/成像）才是你的核心方向
    s_cross = int(w.get("cross_bonus", 0)) if (src and (ast or img)) else 0
    s_fresh = int(w["timeliness"]) if int(paper.get("version", 1)) == 1 else 2
    length = len(abstract)
    s_complete = int(w["completeness"]) if length >= 400 else (3 if length >= 200 else 0)
    s_negative = -min(len(neg) * 10, 20) if (not fac and not ast and not img) else 0

    # 理论/模拟类降权：命中 >=2 个理论词即扣分，不因提到 VLBI 而免疫
    s_theory = -int(w.get("theory_penalty", 10)) if len(theo) >= 2 else 0
    total = max(0, s_source + s_method + s_facility + s_title + s_cross
                + s_fresh + s_complete + s_negative + s_theory)

    # 技术通道：必须落在射电语境（射电词或射电阵列），且 >=2 个技术词或 1 个核心技术词
    radio_ctx = bool(inst_ctx) or bool(fac)
    instrument_ok = radio_ctx and (len(inst) >= 2 or bool(inst_core))
    inst_score = min(len(inst) * 10 + (10 if inst_core else 0), 60) if instrument_ok else 0

    return {
        "score": total,
        "instrument_score": inst_score,
        "breakdown": {
            "source": s_source, "method": s_method, "facility": s_facility,
            "title": s_title, "cross": s_cross, "fresh": s_fresh, "complete": s_complete,
            "negative": s_negative, "theory": s_theory,
        },
        "hits": {
            "source": sorted(src), "astrometry": sorted(ast), "imaging": sorted(img),
            "facility": sorted(fac), "instrument": sorted(inst), "negative": sorted(neg),
            "theory": sorted(theo),
        },
    }


def rank(records: list[dict], cfg: dict) -> tuple[list[dict], list[dict]]:
    """返回 (主榜候选, 技术拾遗候选)，已按分数降序并应用阈值与配额。"""
    scored = []
    for rec in records:
        merged = dict(rec)
        merged.update(score_paper(rec, cfg))
        scored.append(merged)

    main_th = int(cfg["threshold"]["main"])
    inst_th = int(cfg["threshold"]["instrument"])
    main = sorted([r for r in scored if r["score"] >= main_th],
                  key=lambda r: (-r["score"], r["published"]))
    inst = sorted([r for r in scored if r["instrument_score"] >= inst_th],
                  key=lambda r: (-r["instrument_score"], r["published"]))
    return main[: int(cfg["quota"]["main"])], inst[: int(cfg["quota"]["instrument"])]