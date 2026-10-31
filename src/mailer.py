"""SMTP 发送（QQ 邮箱 SSL 465），支持多收件人、抄送、内嵌配图与附件。"""
from __future__ import annotations

import re
import smtplib
import time
from email.header import Header
from email.mime.application import MIMEApplication
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate


def split_addresses(value) -> list[str]:
    """支持字符串（逗号/分号分隔）或列表，去重保序。"""
    if not value:
        return []
    if isinstance(value, (list, tuple)):
        value = ",".join(str(v) for v in value)
    seen, out = set(), []
    for part in re.split(r"[,;]", str(value)):
        addr = part.strip()
        if addr and addr not in seen:
            seen.add(addr)
            out.append(addr)
    return out


def recipients(cfg, credentials):
    to = split_addresses(credentials.get("MAIL_TO") or cfg["mail"].get("to"))
    cc = split_addresses(cfg["mail"].get("cc"))
    return to, [a for a in cc if a not in to]


def _build(cfg, credentials, subject, html, text, attachment_name, attachment_text, images, to, cc):
    msg = MIMEMultipart("mixed")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = formataddr((str(Header("VLBI 文献日报", "utf-8")), credentials["SMTP_USER"]))
    msg["To"] = ", ".join(to)
    if cc:
        msg["Cc"] = ", ".join(cc)
    msg["Date"] = formatdate(localtime=True)

    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(text, "plain", "utf-8"))
    alt.attach(MIMEText(html, "html", "utf-8"))

    if images:
        related = MIMEMultipart("related")
        related.attach(alt)
        for img in images:
            subtype = (img.get("mime") or "image/png").split("/")[-1]
            part = MIMEImage(img["data"], _subtype=subtype)
            part.add_header("Content-ID", f"<{img['cid']}>")
            part.add_header("Content-Disposition", "inline", filename=f"fig{img['n']}.{subtype}")
            related.attach(part)
        msg.attach(related)
    else:
        msg.attach(alt)

    if attachment_name and attachment_text:
        part = MIMEApplication(attachment_text.encode("utf-8"))
        part.add_header("Content-Disposition", "attachment", filename=("utf-8", "", attachment_name))
        msg.attach(part)
    return msg


def send(cfg, credentials, subject, html, text, attachment_name=None, attachment_text=None,
         images=None, log=print):
    to, cc = recipients(cfg, credentials)
    if not to:
        raise RuntimeError("没有收件人：检查 config.yaml 的 mail.to 或凭据中的 MAIL_TO")
    msg = _build(cfg, credentials, subject, html, text, attachment_name, attachment_text, images, to, cc)
    all_rcpt = to + cc

    last = None
    for attempt in range(3):
        try:
            with smtplib.SMTP_SSL(cfg["mail"]["smtp"], int(cfg["mail"]["port"]), timeout=45) as smtp:
                smtp.login(credentials["SMTP_USER"], credentials["SMTP_PASS"])
                smtp.sendmail(credentials["SMTP_USER"], all_rcpt, msg.as_string())
            log(f"[邮件] 已发送 -> {', '.join(all_rcpt)}（内嵌图片 {len(images or [])} 张）")
            return
        except Exception as exc:
            last = exc
            log(f"[邮件] 第 {attempt + 1} 次失败: {type(exc).__name__}")
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"邮件发送失败: {last}")