"""入口：召回 -> 打分 -> 摘要 -> 渲染 -> 邮件 -> 台账。"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import load, resolve_window  # noqa: E402
from fetch_arxiv import fetch_window  # noqa: E402
from ledger import Ledger  # noqa: E402
from mailer import send  # noqa: E402
from render import render_html, render_markdown, render_text  # noqa: E402
from score import rank, score_paper  # noqa: E402
import secrets as creds  # noqa: E402
from summarize import LLMClient, LLMError  # noqa: E402

APP_HOME = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TIER_ORDER = {"A": 0, "B": 1, "C": 2}


def histogram(scores: list[int], step: int = 10) -> str:
    if not scores:
        return "  (无数据)"
    hi = (max(scores) // step + 1) * step
    lines = []
    for edge in range(0, hi, step):
        n = sum(1 for s in scores if edge <= s < edge + step)
        lines.append(f"  {edge:>3}-{edge + step - 1:<3} {n:>4} {'#' * min(n, 60)}")
    return "\n".join(lines)


def enrich(papers: list[dict], client: LLMClient | None, short: bool, log=print) -> list[dict]:
    """给候选挂上 summary，并剔除 LLM 判定为不相关的。"""
    if not client or not papers:
        return papers
    result = client.summarize(papers, short=short, log=log)
    out = []
    for p in papers:
        item = result.get(p["arxiv_id"])
        if not item:
            p["summary"] = {"one_liner": "（摘要生成失败，仅标题）", "tier": "C"}
            p["tier"] = "C"
            out.append(p)
            continue
        if item.get("relevant") is False:
            log(f"[LLM] 剔除不相关: {p['arxiv_id']}")
            continue
        p["summary"] = item
        p["tier"] = (item.get("tier") or "C").upper()[:1]
        out.append(p)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="VLBI 文献日报")
    ap.add_argument("--config", default=None)
    ap.add_argument("--hours", type=float, default=None)
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--no-ledger", action="store_true")
    ap.add_argument("--no-llm", action="store_true", help="跳过摘要（调试）")
    ap.add_argument("--no-mail", action="store_true", help="不发邮件（调试）")
    ap.add_argument("--dry-run", action="store_true", help="不写台账、不发邮件，产物落 output/")
    ap.add_argument("--json-out", default=None)
    ap.add_argument("--replay-hours", type=float, default=None,
                    help="复盘模式：忽略台账、强制回看 N 小时、主题加[测试]")
    args = ap.parse_args()

    cfg = load(args.config)
    started = dt.datetime.now(dt.timezone.utc)
    today = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%Y-%m-%d")

    replay = args.replay_hours is not None
    use_ledger = not (args.no_ledger or args.dry_run or replay)
    ledger = Ledger(os.path.join(APP_HOME, "data", "ledger.sqlite3")) if use_ledger else None

    last = ledger.last_success() if ledger else None
    start, end = resolve_window(cfg, last, hours=args.replay_hours or args.hours)
    print(f"[窗口] {start:%Y-%m-%d %H:%M}Z -> {end:%Y-%m-%d %H:%M}Z")

    print("[召回] 抓取 arXiv ...")
    records = fetch_window(cfg, start, end)

    known = ledger.known_ids() if ledger else set()
    fresh = records if replay else [r for r in records if r["arxiv_id"] not in known]
    print(f"[去重] 抓取 {len(records)} 条，新论文 {len(fresh)} 条")

    main_list, inst_list = rank(fresh, cfg)
    main_ids = {r["arxiv_id"] for r in main_list}
    inst_list = [r for r in inst_list if r["arxiv_id"] not in main_ids]
    print(f"[打分] 主榜 {len(main_list)} 篇 / 技术拾遗 {len(inst_list)} 篇")
    print("[分布] 全量得分直方图:")
    print(histogram([score_paper(r, cfg)["score"] for r in fresh]))

    # ---- 摘要 ----
    client = None
    endpoint_name = "未使用"
    if not args.no_llm and (main_list or inst_list):
        try:
            credentials = creds.load()
            client = LLMClient(cfg, credentials)
            client.pick()
            endpoint_name = f"{client.endpoint.get('label') or client.endpoint['name']} / {client.model}"
        except (creds.CredentialError, LLMError) as exc:
            print(f"[LLM] 不可用，降级为仅标题: {exc}")
            client = None

    main_list = enrich(main_list, client, short=False)

    # 理论/模拟类不占主线版面：移入「背景补充」栏目，最多 quota.background 篇
    max_bg = int(cfg["quota"].get("background", 2))
    theory = sorted([p for p in main_list if (p.get("summary") or {}).get("kind") == "theory"],
                    key=lambda x: -x.get("score", 0))
    background = theory[:max_bg]
    bg_ids = {p["arxiv_id"] for p in background}
    main_list = [p for p in main_list if p["arxiv_id"] not in bg_ids]
    if background:
        print(f"[分流] 理论/模拟类 {len(theory)} 篇，{len(background)} 篇进入背景补充")
    inst_list = enrich(inst_list, client, short=True)
    if client is not None:
        import deep_read
        deep_read.run(client, main_list, cfg, log=print)
        endpoint_name = f"{client.endpoint.get('label') or client.endpoint['name']} / {client.model}"
    main_list.sort(key=lambda p: (TIER_ORDER.get(p.get("tier", "C"), 3), -p.get("score", 0)))

    a = sum(1 for p in main_list if p.get("tier") == "A")
    b = sum(1 for p in main_list if p.get("tier") == "B")
    c = sum(1 for p in main_list if p.get("tier") == "C")
    reported = len(main_list) + len(inst_list)
    stats = {"fetched": len(records), "fresh": len(fresh),
             "candidates": len(main_list) + len(inst_list), "reported": reported}

    deep_papers = [p for p in main_list if p.get("deep")]
    models_used = {p["deep"].get("_model") for p in deep_papers if p["deep"].get("_model")}
    if client is not None and client.model:
        models_used.add(client.model)
    meta = {
        "endpoint": (client.endpoint.get("label") or client.endpoint["name"]) if client else "未使用",
        "primary_model": client.model if client else "",
        "models": sorted(models_used),
        "llm_calls": getattr(client, "calls", 0) if client else 0,
        "deep_html": sum(1 for p in deep_papers if p["deep"].get("_source") == "html"),
        "deep_pdf": sum(1 for p in deep_papers if p["deep"].get("_source") == "pdf"),
        "deep_total": len(deep_papers),
        "figures": sum(len(p.get("figures") or []) for p in (main_list + inst_list)),
        "window_hours": round((end - start).total_seconds() / 3600, 1),
        "duration_s": int((dt.datetime.now(dt.timezone.utc) - started).total_seconds()),
        "categories": ", ".join(cfg["arxiv"]["categories"]),
    }

    ctx = {"date": today, "main": main_list, "instrument": inst_list, "background": background,
           "stats": stats, "model": endpoint_name, "meta": meta}

    html = render_html(ctx)
    text = render_text(ctx)
    md = render_markdown(ctx)

    outdir = os.path.join(APP_HOME, "output", today[:7].replace("-", "/"))
    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(outdir, f"{today}.md"), "w", encoding="utf-8") as fh:
        fh.write(md)
    if args.dry_run:
        with open(os.path.join(outdir, f"{today}.html"), "w", encoding="utf-8") as fh:
            fh.write(html)
        print(f"[dry-run] 产物: {os.path.join(outdir, today)}.html | .md")

    # ---- 邮件 ----
    subject = ("[测试] " if replay else "") + f"{cfg['mail']['subject_prefix']}{today} · {reported} 篇（A{a}/B{b}/C{c}）"
    sent = False
    if args.no_mail or args.dry_run:
        print(f"[邮件] 已跳过。主题预览: {subject}")
    elif not fresh and not cfg["mail"].get("send_empty", True):
        print("[邮件] 今日无新增，且配置为不发送空日报")
    else:
        try:
            import figures as figmod
            images = [{**fg, "cid": figmod.cid(p["arxiv_id"], fg["n"])}
                      for p in (main_list + inst_list) for fg in (p.get("figures") or [])]
            send(cfg, creds.load(), subject, html, text,
                 attachment_name=f"VLBI日报-{today}.md", attachment_text=md, images=images)
            sent = True
        except Exception as exc:      # noqa: BLE001
            print(f"[邮件] 发送失败: {exc}")

    # ---- 台账 ----
    # 关键：邮件没发出去就不能把论文记成"已见"，否则下次会因去重而永久漏掉
    delivered = sent or args.no_mail
    reported_ids: set[str] = set()
    if ledger and delivered:
        reported_ids = {p["arxiv_id"] for p in main_list} | {p["arxiv_id"] for p in inst_list} if sent else set()
        for rec in fresh:
            status = "reported" if rec["arxiv_id"] in reported_ids else "suppressed"
            ledger.record_paper(rec, score_paper(rec, cfg)["score"], "main", status)
    elif ledger:
        print(f"[台账] 邮件未发出，本次 {len(fresh)} 篇不写入台账，下次运行会重新纳入")
    if ledger:
        ledger.record_run(
            run_id=started.strftime("%Y%m%dT%H%M%SZ"), started=started.isoformat(),
            fetched=len(records), candidates=reported, reported=len(reported_ids),
            status="ok" if (sent or args.no_mail) else "error",
            error="" if (sent or args.no_mail) else "mail failed",
            endpoint=endpoint_name)
        print(f"[台账] {ledger.stats()}")
        ledger.close()

    if args.json_out:
        os.makedirs(os.path.dirname(os.path.abspath(args.json_out)), exist_ok=True)
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump({"window": {"start": start.isoformat(), "end": end.isoformat()},
                       "main": main_list, "instrument": inst_list, "stats": stats},
                      fh, ensure_ascii=False, indent=1)
        print(f"[输出] {args.json_out}")

    print("\n=== 主榜 ===")
    for i, p in enumerate(main_list[: args.top], 1):
        s = p.get("summary") or {}
        print(f"{i:>2}. [{p.get('tier','C')}|{p['score']:>3}] {p['arxiv_id']} {p['title'][:74]}")
        if s.get("one_liner"):
            print(f"      {s['one_liner'][:110]}")
    if inst_list:
        print("\n=== 技术拾遗 ===")
        for i, p in enumerate(inst_list, 1):
            print(f"{i:>2}. [{p['instrument_score']:>3}] {p['arxiv_id']} {p['title'][:74]}")
    return 0 if delivered else 1


if __name__ == "__main__":
    raise SystemExit(main())