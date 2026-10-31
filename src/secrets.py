"""凭据加载（fail-closed）。

三级来源，按优先级：
1. systemd 加密凭据  $CREDENTIALS_DIRECTORY/vlbi-digest-env
   （由 root 用 systemd-creds --with-key=host 加密，明文永不落盘）
2. 用户私有文件       ~/.config/vlbi-digest/env   （权限必须 <= 0600）
3. 环境变量覆盖       仅用于临时调试（VLBI_DIGEST_ALLOW_ENV=1 才启用）

任何日志、异常、repr 中都不会输出凭据值。
"""
from __future__ import annotations

import os
import stat
from pathlib import Path

REQUIRED = ("SMTP_USER", "SMTP_PASS")   # 收件人可来自 config.yaml；LLM 密钥由端点配置决定
DEFAULT_PATH = Path.home() / ".config" / "vlbi-digest" / "env"
CRED_NAME = "arxiv-digest-env"
LEGACY_NAMES = ("vlbi-digest-env",)   # 兼容旧部署


class CredentialError(RuntimeError):
    pass


def _parse(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        data[key.strip()] = val.strip().strip('"').strip("'")
    return data


def _assert_private(path: Path) -> None:
    """文件与上级目录都不能被同组/其他用户读取。"""
    mode = stat.S_IMODE(os.stat(path).st_mode)
    if mode & 0o077:
        raise CredentialError(
            f"凭据文件权限过宽: {path} ({oct(mode)})，请执行 chmod 600 {path}")
    parent_mode = stat.S_IMODE(os.stat(path.parent).st_mode)
    if parent_mode & 0o077:
        raise CredentialError(
            f"凭据目录权限过宽: {path.parent} ({oct(parent_mode)})，请执行 chmod 700 {path.parent}")


def load(required: bool = True) -> dict[str, str]:
    cred_dir = os.environ.get("CREDENTIALS_DIRECTORY")
    if cred_dir:
        for name in (CRED_NAME,) + LEGACY_NAMES:
            candidate = Path(cred_dir) / name
            if candidate.exists():
                data = _parse(candidate)      # systemd 已保证 tmpfs + 0500
                _validate(data, required)
                return data

    if os.environ.get("VLBI_DIGEST_ALLOW_ENV") == "1":
        data = {k: os.environ[k] for k in REQUIRED if k in os.environ}
        if data:
            _validate(data, required)
            return data

    path = Path(os.environ.get("VLBI_DIGEST_ENV", DEFAULT_PATH)).expanduser()
    if not path.exists():
        if required:
            raise CredentialError(
                f"未找到凭据文件 {path}。请在服务器上执行：\n"
                f"  mkdir -p {path.parent} && chmod 700 {path.parent}\n"
                f"  然后写入 SMTP_USER/SMTP_PASS/LLM_KEY_PRIMARY 等字段并 chmod 600 {path}")
        return {}
    _assert_private(path)
    data = _parse(path)
    _validate(data, required)
    return data


def _validate(data: dict[str, str], required: bool) -> None:
    if not required:
        return
    missing = [k for k in REQUIRED if not data.get(k)]
    if missing:
        raise CredentialError(f"凭据文件缺少字段: {', '.join(missing)}")


def mask(value: str, keep: int = 4) -> str:
    """给日志用的脱敏显示，例如 'sk-a***9f2c'。"""
    if not value:
        return "<empty>"
    if len(value) <= keep * 2:
        return "*" * len(value)
    return f"{value[:keep]}***{value[-keep:]}"


def describe() -> str:
    """不含敏感值的凭据来源描述，可安全写进日志/邮件页脚。"""
    if os.environ.get("CREDENTIALS_DIRECTORY"):
        return "systemd-credential(加密)"
    p = Path(os.environ.get("VLBI_DIGEST_ENV", DEFAULT_PATH)).expanduser()
    if p.exists():
        return f"file:{p} (0600)"
    if os.environ.get("VLBI_DIGEST_ALLOW_ENV") == "1":
        return "env(调试)"
    return "none"