#!/usr/bin/env bash
# ============================================================
#  arxiv-digest 一键部署（需要一次 sudo）
#
#  用法:
#    sudo bash deploy/install.sh --creds ~/digest-credentials.env
#
#  可选:
#    --user  USER     运行服务的用户（默认: sudo 发起者）
#    --app   DIR      程序目录（默认: 本仓库所在目录）
#    --python PATH    Python 解释器（默认: 自动探测 python3）
#    --time  HH:MM    每日运行时刻（默认: 03:00）
#    --tz    TZ       时区（默认: Asia/Shanghai）
#    --keep-creds     安装后保留明文凭据（默认会 shred 掉）
# ============================================================
set -euo pipefail

USER_NAME="${SUDO_USER:-$(id -un)}"
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="$(command -v python3 || true)"
CREDS=""
RUN_TIME="03:00"
TZ_NAME="Asia/Shanghai"
KEEP=0
CRED_DIR=/etc/arxiv-digest

usage() { sed -n '2,18p' "$0"; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --creds)      CREDS="${2:-}"; shift 2 ;;
    --user)       USER_NAME="${2:-}"; shift 2 ;;
    --app)        APP_DIR="${2:-}"; shift 2 ;;
    --python)     PYTHON_BIN="${2:-}"; shift 2 ;;
    --time)       RUN_TIME="${2:-}"; shift 2 ;;
    --tz)         TZ_NAME="${2:-}"; shift 2 ;;
    --keep-creds) KEEP=1; shift ;;
    -h|--help)    usage ;;
    *) echo "未知参数: $1"; usage ;;
  esac
done

[ "$(id -u)" -eq 0 ] || { echo "请用 sudo 运行"; exit 1; }
[ -n "$CREDS" ] || { echo "必须用 --creds 指定凭据文件"; usage; }
[ -f "$CREDS" ] || { echo "凭据文件不存在: $CREDS"; exit 1; }
[ -n "$PYTHON_BIN" ] || { echo "找不到 python3，请用 --python 指定"; exit 1; }
command -v systemd-creds >/dev/null || { echo "缺少 systemd-creds（systemd >= 250）"; exit 1; }

echo "== 1/6 检查凭据 =="
for k in SMTP_USER SMTP_PASS LLM_KEY_PRIMARY; do
  grep -q "^${k}=" "$CREDS" || echo "  ⚠ 凭据缺少 ${k}=（若只用备用端点可忽略 LLM_KEY_PRIMARY）"
done

echo "== 2/6 加密凭据 =="
install -d -m 0700 -o root -g root "$CRED_DIR"
systemd-creds encrypt --with-key=host --name=arxiv-digest-env "$CREDS" "$CRED_DIR/credentials.env.cred"
chmod 600 "$CRED_DIR/credentials.env.cred"
ls -l "$CRED_DIR/credentials.env.cred"

echo "== 3/6 生成 systemd 单元 =="
render() {
  sed -e "s|@@USER@@|${USER_NAME}|g" \
      -e "s|@@APP@@|${APP_DIR}|g" \
      -e "s|@@PYTHON@@|${PYTHON_BIN}|g" \
      -e "s|@@TIME@@|${RUN_TIME}|g" \
      -e "s|@@TZ@@|${TZ_NAME}|g" "$1" > "$2"
}
TMP=$(mktemp -d)
render deploy/arxiv-digest.service.in      "$TMP/arxiv-digest.service"
render deploy/arxiv-digest.timer.in        "$TMP/arxiv-digest.timer"
render deploy/arxiv-digest-test.service.in "$TMP/arxiv-digest-test.service"
grep -E "User=|WorkingDirectory=|OnCalendar=|ExecStart" "$TMP"/arxiv-digest.*

install -m 0644 "$TMP/arxiv-digest.service"      /etc/systemd/system/
install -m 0644 "$TMP/arxiv-digest.timer"        /etc/systemd/system/
install -m 0644 "$TMP/arxiv-digest-test.service" /etc/systemd/system/
rm -rf "$TMP"
systemctl daemon-reload

echo "== 4/6 销毁明文凭据 =="
if [ "$KEEP" -eq 0 ]; then
  shred -u "$CREDS" 2>/dev/null || rm -f "$CREDS"
  echo "  已删除 $CREDS"
else
  echo "  保留（--keep-creds）"
fi

echo "== 5/6 试跑一次（真实抓取 + 摘要 + 发信）=="
if systemctl start arxiv-digest.service; then
  echo "  ✅ 试跑成功，检查邮箱"
else
  echo "  ❌ 试跑失败，定时器不会启用"
  journalctl -u arxiv-digest.service -n 40 --no-pager || true
  exit 1
fi

echo "== 6/6 启用定时器 =="
systemctl enable --now arxiv-digest.timer
systemctl list-timers arxiv-digest.timer --no-pager

cat <<EOF

完成。
  每日运行:  ${RUN_TIME} ${TZ_NAME}
  手动触发:  sudo systemctl start arxiv-digest.service
  复盘测试:  sudo systemctl start arxiv-digest-test.service
  查看日志:  tail -f ${APP_DIR}/logs/digest-\$(date +%F).log
EOF