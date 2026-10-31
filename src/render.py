"""渲染 HTML / 纯文本 / Markdown。A 级支持全文精读的扩展版式。"""
from __future__ import annotations

import html

TIER_LABEL = {"A": "必读", "B": "关注", "C": "了解"}

CSS = """
body{margin:0;padding:0;background:#f4f5f7;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;}
.wrap{max-width:760px;margin:0 auto;padding:18px 14px 40px;}
.hd{background:#1f2a37;color:#fff;border-radius:10px;padding:18px 20px;}
.hd h1{margin:0 0 6px;font-size:19px;font-weight:600;letter-spacing:.3px;}
.hd .sub{font-size:12px;color:#a8b3c2;}
.stat{margin:14px 0 6px;font-size:13px;color:#3b4654;line-height:1.9;}
.sec{margin:22px 0 8px;font-size:14px;font-weight:600;color:#4b5563;border-left:3px solid #9aa7b8;padding-left:8px;}
.card{background:#fff;border-radius:10px;padding:16px 18px;margin:10px 0;box-shadow:0 1px 2px rgba(16,24,40,.06);}
.tier{display:inline-block;font-size:11px;padding:2px 8px;border-radius:10px;margin-bottom:8px;}
.tA{background:#fee2e2;color:#991b1b;} .tB{background:#fef3c7;color:#92400e;} .tC{background:#e5e7eb;color:#374151;}
.title{font-size:15px;font-weight:600;line-height:1.45;}
.title a{color:#1a202c;text-decoration:none;}
.meta{font-size:11px;color:#8b95a5;margin:6px 0 10px;}
.one{font-size:13.5px;color:#111827;background:#f8fafc;border-left:3px solid #cbd5e1;padding:8px 10px;border-radius:4px;line-height:1.65;}
.kv{width:100%;border-collapse:collapse;margin-top:10px;font-size:12.5px;}
.kv td{vertical-align:top;padding:4px 0;line-height:1.75;}
.kv .k{width:96px;color:#6b7280;padding-right:10px;}
.kv .v{color:#1f2937;}
.sub{margin:12px 0 4px;font-size:12px;font-weight:600;color:#6b7280;}
ul.pts{margin:2px 0 0;padding-left:18px;font-size:12.5px;color:#1f2937;line-height:1.8;}
ul.pts li{margin:2px 0;}
.nums{margin-top:10px;font-size:11.5px;color:#4b5563;background:#f9fafb;border-radius:4px;padding:8px 10px;line-height:1.8;}
.deeptag{display:inline-block;font-size:10.5px;color:#065f46;background:#d1fae5;border-radius:3px;padding:1px 6px;margin-left:6px;}
.act{font-size:11.5px;color:#6b7280;margin-top:10px;padding-top:8px;border-top:1px dashed #e5e7eb;}
.act a{color:#2563eb;text-decoration:none;}
.tag{background:#eef2f7;color:#475569;border-radius:3px;padding:1px 5px;margin-right:4px;font-size:10.5px;}
.clist{background:#fff;border-radius:10px;padding:12px 18px;font-size:12.5px;color:#4b5563;line-height:1.9;}
.clist a{color:#374151;text-decoration:none;}
.fig{margin:14px 0 6px;}
.fig img{max-width:100%;height:auto;border:1px solid #e5e7eb;border-radius:6px;display:block;}
.figcap{font-size:11.5px;color:#6b7280;line-height:1.7;margin-top:6px;}
.figcap b{color:#374151;}.bgcard{background:#fbfbfd;border:1px solid #e8ebf0;border-radius:10px;padding:14px 16px;margin:10px 0;}.bgcard .title{font-size:13.5px;}.bgcard .note{font-size:12.5px;color:#4b5563;line-height:1.8;margin-top:8px;background:#fff;border-left:3px solid #cbd5e1;padding:8px 10px;border-radius:4px;}.ft{margin-top:26px;font-size:11px;color:#9aa5b4;line-height:1.8;text-align:center;}
"""


def _esc(t) -> str:
    return html.escape(str(t or ""))


def _tags(s: dict) -> str:
    return "".join(f"<span class='tag'>{_esc(t)}</span>" for t in (s.get("tags") or [])[:3])


def _ul(items) -> str:
    items = [x for x in (items or []) if x]
    if not items:
        return ""
    return "<ul class='pts'>" + "".join(f"<li>{_esc(x)}</li>" for x in items) + "</ul>"


def _kw_rows(pairs) -> str:
    rows = "".join(f"<tr><td class='k'>{_esc(k)}</td><td class='v'>{_esc(v)}</td></tr>"
                   for k, v in pairs if v)
    return f"<table class='kv'>{rows}</table>" if rows else ""


def _deep_html(d: dict) -> str:
    parts = [_kw_rows([("背景与问题", d.get("background")),
                       ("数据与方法", d.get("method")),
                       ("结论与论证", d.get("conclusion")),
                       ("局限", d.get("limitations")),
                       ("与你研究的关系", d.get("relation"))])]
    if d.get("results"):
        parts.append("<div class='sub'>关键结果</div>" + _ul(d["results"]))
    if d.get("questions"):
        parts.append("<div class='sub'>值得追问</div>" + _ul(d["questions"]))
    if d.get("key_numbers"):
        parts.append("<div class='nums'>" + "<br>".join(_esc(x) for x in d["key_numbers"][:6]) + "</div>")
    return "".join(parts)


def _figures_html(p: dict) -> str:
    figs = p.get("figures") or []
    if not figs:
        return ""
    import figures as figmod
    out = []
    for fg in figs:
        c = figmod.cid(p["arxiv_id"], fg["n"])
        why = f" — <b>{_esc(fg.get('why'))}</b>" if fg.get("why") else ""
        out.append(f"<div class='fig'><img src='cid:{c}' alt='Figure {fg['n']}'>"
                   f"<div class='figcap'>图{fg['n']}：{_esc(fg.get('caption', '')[:300])}{why}</div></div>")
    return "".join(out)


def _card(p: dict, full: bool = True) -> str:
    s = p.get("summary") or {}
    d = p.get("deep") or {}
    tier = (p.get("tier") or s.get("tier") or "C").upper()[:1]
    deep_tag = ("<span class='deeptag'>全文精读</span>"
                if d else "")

    if d:
        body = _deep_html(d)
    else:
        pairs = [("结论", s.get("conclusion"))]
        if full:
            pairs.append(("数据与观测", s.get("data")))
        pairs.append(("关键结果", s.get("result")))
        pairs.append(("与你方向的关系", s.get("relation")))
        body = _kw_rows(pairs)

    return (
        "<div class='card'>"
        f"<div class='tier t{tier}'>{tier} · {TIER_LABEL.get(tier, tier)}</div>{deep_tag}"
        f"<div class='title'><a href='{_esc(p.get('abs_url'))}'>{_esc(p.get('title'))}</a></div>"
        f"<div class='meta'>{_esc(p.get('arxiv_id'))} · {_esc((p.get('published') or '')[:10])}"
        f" · {_esc(p.get('primary_category'))} {_tags(s)}</div>"
        f"<div class='one'>{_esc(s.get('one_liner'))}</div>"
        + body
        + _figures_html(p)
        + "<div class='act'>建议：" + _esc(s.get("action")) +
        f" · <a href='{_esc(p.get('abs_url'))}'>abs</a> · <a href='{_esc(p.get('pdf_url'))}'>pdf</a></div>"
        "</div>"
    )


def _bg_card(p: dict) -> str:
    s = p.get("summary") or {}
    note = s.get("bg_note") or ""
    return ("<div class='bgcard'>"
            f"<div class='title'><a href='{_esc(p.get('abs_url'))}'>{_esc(p.get('title'))}</a></div>"
            f"<div class='meta'>{_esc(p.get('arxiv_id'))} · {_esc((p.get('published') or '')[:10])}"
            f" · {_esc(p.get('primary_category'))} {_tags(s)}</div>"
            f"<div class='one'>{_esc(s.get('one_liner'))}</div>"
            + (f"<div class='note'>{_esc(note)}</div>" if note else "")
            + "</div>")


def render_html(ctx: dict) -> str:
    main, inst, stats = ctx["main"], ctx["instrument"], ctx["stats"]
    a = [p for p in main if (p.get("tier") or "C") == "A"]
    b = [p for p in main if (p.get("tier") or "C") == "B"]
    c = [p for p in main if (p.get("tier") or "C") == "C"]
    n_deep = sum(1 for p in main if p.get("deep"))

    overview = ""
    if a or b:
        top = (a + b)[:2]
        items = "".join(
            f"<div>· <a href='{_esc(p.get('abs_url'))}'>{_esc(p.get('title'))}</a><br>"
            f"<span style='color:#6b7280'>{_esc((p.get('summary') or {}).get('one_liner'))}</span></div>"
            for p in top)
        overview = f"<div class='clist'>{items}</div>"

    parts = [
        "<html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        f"<style>{CSS}</style></head><body><div class='wrap'>",
        f"<div class='hd'><h1>VLBI 文献日报 · {_esc(ctx['date'])}</h1>"
        "<div class='sub'>长周期暂现源 / VLBI 天体测量 / 干涉阵成像 / 射电技术</div></div>",
        f"<div class='stat'>抓取 <b>{stats['fetched']}</b> 篇 → 候选 <b>{stats['candidates']}</b> 篇"
        f" → 入报 <b>{stats['reported']}</b> 篇（A {len(a)} / B {len(b)} / C {len(c)}）"
        f"，其中 <b>{n_deep}</b> 篇做了全文精读"
        f"<br>生成模型：{_esc(ctx.get('model'))} · 数据源：arXiv astro-ph</div>",
    ]
    if overview:
        parts.append("<div class='sec'>今日概览</div>" + overview)
    if a:
        parts.append("<div class='sec'>A · 必读（全文精读）</div>" + "".join(_card(p, full=True) for p in a))
    if b:
        parts.append("<div class='sec'>B · 关注</div>" + "".join(_card(p, full=False) for p in b))
    if c:
        rows = "".join(f"<div>· <a href='{_esc(p.get('abs_url'))}'>{_esc(p.get('title'))}</a></div>" for p in c)
        parts.append("<div class='sec'>C · 了解</div><div class='clist'>" + rows + "</div>")
    if ctx.get("background"):
        parts.append("<div class='sec'>📖 背景补充（非主线，帮助理解）</div>"
                     + "".join(_bg_card(p) for p in ctx["background"]))
    if inst:
        parts.append("<div class='sec'>📡 技术拾遗</div>" + "".join(_card(p, full=False) for p in inst))
    if not main and not inst:
        parts.append("<div class='clist'>今日无新增命中。系统运行正常。</div>")

    m = ctx.get("meta") or {}
    models = " / ".join(m.get("models") or []) or "未调用"
    dur = int(m.get("duration_s", 0))
    parts.append(
        "<div class='ft'>"
        f"<b>数据来源</b>：arXiv {_esc(m.get('categories', 'astro-ph'))}"
        f"（API 召回，时间窗 {m.get('window_hours', 0)} 小时；"
        f"抓取 {stats['fetched']} 篇 / 新论文 {stats['fresh']} 篇 / 入报 {stats['reported']} 篇）<br>"
        f"<b>全文来源</b>：arXiv HTML {m.get('deep_html', 0)} 篇 · PDF {m.get('deep_pdf', 0)} 篇"
        f" · 内嵌插图 {m.get('figures', 0)} 张<br>"
        f"<b>生成模型</b>：{_esc(m.get('endpoint', '未使用'))} · {_esc(models)}"
        f"（API 调用 {m.get('llm_calls', 0)} 次）<br>"
        "<b>栏位说明</b>：A/B 全文精读，C 仅标题，背景补充为理论类白话导读<br>"
        f"<b>运行</b>：{_esc(ctx['date'])} 用时 {dur // 60} 分 {dur % 60} 秒"
        " · 台账 ~/vlbi-digest/data/ledger.sqlite3"
        "</div>")
    parts.append("</div></body></html>")
    return "".join(parts)


def _deep_text(d: dict) -> list[str]:
    out = []
    for key, label in (("background", "背景"), ("method", "数据与方法"),
                       ("conclusion", "结论"), ("limitations", "局限"), ("relation", "与你研究")):
        if d.get(key):
            out.append(f"    {label}：{d[key]}")
    if d.get("results"):
        out.append("    关键结果：")
        out += [f"      - {x}" for x in d["results"]]
    if d.get("questions"):
        out.append("    值得追问：")
        out += [f"      ? {x}" for x in d["questions"]]
    return out


def render_text(ctx: dict) -> str:
    main, inst = ctx["main"], ctx["instrument"]
    lines = [f"VLBI 文献日报 · {ctx['date']}",
             f"抓取 {ctx['stats']['fetched']} 篇 → 候选 {ctx['stats']['candidates']} 篇 → 入报 {ctx['stats']['reported']} 篇",
             "-" * 46]
    if not main and not inst:
        lines.append("今日无新增命中。")
    for p in main:
        s = p.get("summary") or {}
        lines += [f"[{(p.get('tier') or 'C')}] {p['title']}",
                  f"    {p['arxiv_id']} · {p['abs_url']}",
                  f"    一句话：{s.get('one_liner', '')}"]
        if p.get("deep"):
            lines += _deep_text(p["deep"])
        else:
            for key, label in (("conclusion", "结论"), ("result", "关键结果"), ("relation", "与你方向")):
                if s.get(key):
                    lines.append(f"    {label}：{s[key]}")
        lines.append("")
    if ctx.get("background"):
        lines.append("📖 背景补充（非主线）")
        for p in ctx["background"]:
            s2 = p.get("summary") or {}
            lines += [f"  · {p['title']}  ({p['arxiv_id']})",
                      f"    {s2.get('one_liner', '')}"]
            if s2.get("bg_note"):
                lines.append(f"    背景：{s2['bg_note']}")
    if inst:
        lines.append("📡 技术拾遗")
        for p in inst:
            s = p.get("summary") or {}
            lines += [f"  · {p['title']}  ({p['arxiv_id']})", f"    {s.get('one_liner', '')}"]
    m = ctx.get("meta") or {}
    dur = int(m.get("duration_s", 0))
    lines += ["", "———— 信息来源 ————",
              f"数据来源：arXiv {m.get('categories', '')}（时间窗 {m.get('window_hours', 0)} 小时）",
              f"全文来源：arXiv HTML {m.get('deep_html', 0)} 篇 · PDF {m.get('deep_pdf', 0)} 篇"
              f" · 插图 {m.get('figures', 0)} 张",
              f"生成模型：{m.get('endpoint', '未使用')}"
              f" · {' / '.join(m.get('models') or []) or '未调用'}"
              f"（API 调用 {m.get('llm_calls', 0)} 次）",
              f"运行：用时 {dur // 60} 分 {dur % 60} 秒"]
    return "\n".join(lines)


def render_markdown(ctx: dict) -> str:
    main, inst = ctx["main"], ctx["instrument"]
    out = [f"# VLBI 文献日报 · {ctx['date']}", "",
           f"- 抓取：{ctx['stats']['fetched']} 篇",
           f"- 候选：{ctx['stats']['candidates']} 篇",
           f"- 入报：{ctx['stats']['reported']} 篇",
           f"- 模型：{ctx.get('model')}", ""]
    for p in main:
        s = p.get("summary") or {}
        d = p.get("deep") or {}
        tag = "（全文精读）" if d else ""
        out += [f"## [{p.get('tier','C')}] {p['title']}{tag}", "",
                f"- arXiv: [{p['arxiv_id']}]({p['abs_url']}) · {p['published'][:10]} · {p.get('primary_category','')}",
                f"- **一句话**：{s.get('one_liner','')}"]
        if d:
            out += [f"- **背景与问题**：{d.get('background','')}",
                    f"- **数据与方法**：{d.get('method','')}",
                    f"- **结论与论证**：{d.get('conclusion','')}",
                    f"- **局限**：{d.get('limitations','')}",
                    f"- **与你研究的关系**：{d.get('relation','')}"]
            if d.get("results"):
                out.append("- **关键结果**：")
                out += [f"  - {x}" for x in d["results"]]
            if d.get("questions"):
                out.append("- **值得追问**：")
                out += [f"  - {x}" for x in d["questions"]]
            if d.get("key_numbers"):
                out.append("- **关键数值**：" + "；".join(d["key_numbers"][:6]))
        else:
            out += [f"- **结论**：{s.get('conclusion','')}",
                    f"- **数据与观测**：{s.get('data','')}",
                    f"- **关键结果**：{s.get('result','')}",
                    f"- **与你方向的关系**：{s.get('relation','')}"]
        out += [f"- **建议**：{s.get('action','')}", ""]
    if ctx.get("background"):
        out += ["## 📖 背景补充（非主线）", ""]
        for p in ctx["background"]:
            s2 = p.get("summary") or {}
            out += [f"- **{p['title']}** ({p['arxiv_id']}) — {s2.get('one_liner', '')}",
                    f"  - 背景：{s2.get('bg_note', '')}"]
        out.append("")
    if inst:
        out += ["## 📡 技术拾遗", ""]
        for p in inst:
            s = p.get("summary") or {}
            out += [f"- **{p['title']}** ({p['arxiv_id']}) — {s.get('one_liner','')}"]
    m = ctx.get("meta") or {}
    dur = int(m.get("duration_s", 0))
    out += ["", "---", "", "### 信息来源", "",
            f"- 数据来源：arXiv {m.get('categories', '')}（时间窗 {m.get('window_hours', 0)} 小时）",
            f"- 全文来源：arXiv HTML {m.get('deep_html', 0)} 篇 · PDF {m.get('deep_pdf', 0)} 篇"
            f" · 插图 {m.get('figures', 0)} 张",
            f"- 生成模型：{m.get('endpoint', '未使用')}"
            f" · {' / '.join(m.get('models') or []) or '未调用'}"
            f"（API 调用 {m.get('llm_calls', 0)} 次）",
            f"- 运行：用时 {dur // 60} 分 {dur % 60} 秒"]
    return "\n".join(out)