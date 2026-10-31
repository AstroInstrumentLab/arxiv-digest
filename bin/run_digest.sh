#!/usr/bin/env bash
# 入口脚本：凭据由 Python 侧读取（见 src/secrets.py），本脚本不 export 任何密钥
set -euo pipefail
APP_HOME="${VLBI_DIGEST_HOME:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
PY="${VLBI_DIGEST_PYTHON:-python3}"
cd "$APP_HOME"
mkdir -p "$APP_HOME/logs" "$APP_HOME/data" "$APP_HOME/output"
LOG="$APP_HOME/logs/digest-$(date +%Y-%m-%d).log"
umask 077
echo "==== $(date '+%F %T') 参数: $* ====" | tee -a "$LOG"
"$PY" -u "$APP_HOME/src/main.py" "$@" 2>&1 | tee -a "$LOG"
find "$APP_HOME/logs" -name 'digest-*.log' -mtime +30 -delete 2>/dev/null || true