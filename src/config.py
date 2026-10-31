"""配置加载与时间窗计算。"""
from __future__ import annotations

import datetime as dt
import os

import yaml

DEFAULT_CONFIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.yaml")


def load(path: str | None = None) -> dict:
    """读取 YAML 配置并做最小校验。"""
    path = path or os.environ.get("VLBI_DIGEST_CONFIG", DEFAULT_CONFIG)
    with open(path, "r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    for key in ("arxiv", "keywords", "weights", "quota", "threshold", "window"):
        if key not in cfg:
            raise KeyError(f"config.yaml 缺少必需段落: {key}")
    if not cfg["arxiv"].get("categories"):
        raise ValueError("config.yaml: arxiv.categories 不能为空")
    return cfg


def resolve_window(cfg: dict, last_success: dt.datetime | None, now: dt.datetime | None = None,
                   hours: float | None = None) -> tuple[dt.datetime, dt.datetime]:
    """计算抓取时间窗 [start, end)，UTC。

    优先级: 显式 hours > 上次成功运行(滚动) > 配置的最小时长。
    周一额外放大窗口，覆盖 arXiv 周末不公告的空档。
    """
    now = now or dt.datetime.now(dt.timezone.utc)
    win = cfg["window"]
    min_hours = float(win.get("min_hours", 36))
    overlap = float(win.get("overlap_hours", 12))

    if hours is not None:
        start = now - dt.timedelta(hours=hours)
    elif last_success is not None and last_success.tzinfo is not None:
        start = last_success - dt.timedelta(hours=overlap)
        floor = now - dt.timedelta(hours=min_hours)
        if start > floor:
            start = floor
    else:
        start = now - dt.timedelta(hours=min_hours)

    # 周一（北京时间）补足周末空档
    local = now.astimezone(dt.timezone(dt.timedelta(hours=8)))
    if local.weekday() == 0:
        monday_start = now - dt.timedelta(hours=float(win.get("monday_hours", 72)))
        if monday_start < start:
            start = monday_start

    return start, now