# arXiv Digest

> 每天自动抓取 arXiv 新论文，按你的研究方向筛选、用 LLM 写中文摘要、对重点论文精读全文，
> 最后把一份日报发到你邮箱。
>
> *A self-hosted daily arXiv digest: fetch → score → LLM summarize → full-text deep read → email.*

维护：**Astro Instrument Lab**（中国科学院国家天文台） · [组织主页](https://github.com/AstroInstrumentLab)

**适合谁**：研究方向窄、每天需要扫 arXiv，但不想被几百篇噪声淹没的研究者。
默认配置面向 **射电天文 / VLBI 天体测量 / 长周期暂现源**，改关键词即可用于任何方向。

---

## 它解决什么问题

arXiv 每天在 astro-ph 下发布 50–200 篇论文，其中真正与你相关的通常只有 3–8 篇。
本项目把「找论文」这件事自动化，并且**只推你要的**：

```
arXiv 全量
   │  ① 召回：指定类目 + 时间窗（默认回看 5 天）
   │  ② 去重：SQLite 台账，同一篇只推一次
   │  ③ 规则打分：关键词加权（主题/方法/设备/交叉/时效）
   │  ④ LLM 判定：相关性、分级(A/B/C)、类型(观测/理论/方法/仪器)
   │  ⑤ 全文精读：A/B 级抓全文，提结构化要点 + 关键插图
   │  ⑥ 邮件推送：HTML 日报 + Markdown 附件
   ▼
每天 3–8 篇，5 分钟读完
```

## 特点

- **两级筛选**：规则打分（无成本、可解释）+ LLM 判定（理解语义、剔除误报）
- **全文精读**：不只看摘要，抓 arXiv HTML（缺失时退 PDF），提取方法、结果、局限、可追问的问题
- **关键插图**：由模型判断哪张图支撑核心结论，内嵌到邮件里
- **分级栏目**：A 必读 / B 关注 / C 了解 / 📖 背景补充（理论类白话导读）/ 📡 技术拾遗
- **永不漏论文**：滚动窗口 + 台账只记"真正送达"的内容 + 失败自动重试
- **多模型降级**：端点 A 模型 1 → 模型 2 → 端点 B，页脚记录实际使用的模型
- **凭据加密**：systemd-creds 用主机密钥加密，明文不落盘
- **零第三方依赖**：只需 `requests` 和 `PyYAML`

## 快速开始

### 0. 环境要求

| 项 | 要求 |
|---|---|
| 系统 | Linux + systemd（250+，需要 `systemd-creds`） |
| Python | 3.10+ |
| 依赖 | `pip install requests pyyaml` |
| 可选 | `poppler-utils`（PDF 兜底全文）、`pdftotext` |
| 必需 | 一个 OpenAI 兼容的 LLM API key、一个可发信的 SMTP 账号 |

### 1. 获取代码

```bash
git clone https://github.com/AstroInstrumentLab/arxiv-digest.git
cd arxiv-digest
python3 -m pip install --user requests pyyaml
```

### 2. 写配置

```bash
cp config.example.yaml config.yaml
```

至少改这四处：

```yaml
arxiv:
  user_agent: "arxiv-digest/1.0 (you@example.com)"   # arXiv 要求留联系方式

llm:
  endpoints:
    - name: primary
      base_url: "https://api.your-provider.com/v1"
      models: ["your-model-name"]
      key_env: LLM_KEY_PRIMARY

mail:
  from: "you@example.com"
  to:   "you@example.com"
```

**改关键词**（最关键的一步）：

```yaml
keywords:
  source:        # ← 你的研究主题，命中最多的最相关
    - "long-period radio transient"
    - "repeating FRB"
    - "tidal disruption event|TDE"
```

### 3. 写凭据

```bash
mkdir -p ~/.config/arxiv-digest && chmod 700 ~/.config/arxiv-digest
cat > /tmp/digest-credentials.env <<'EOF'
SMTP_USER=you@example.com
SMTP_PASS=你的SMTP授权码
LLM_KEY_PRIMARY=sk-xxxx
EOF
chmod 600 /tmp/digest-credentials.env
```

> QQ 邮箱：设置 → 账户 → 开启 SMTP 服务 → 生成**授权码**（不是登录密码）。
> Gmail：需要应用专用密码。其他邮箱同理。

### 4. 先自检（不需要 sudo）

```bash
python3 src/preflight.py
```

会检查：凭据权限、SMTP 登录、LLM 端点是否可用、用一篇假摘要试调一次。**不发信、不写台账**。

### 5. 一键部署（需要一次 sudo）

```bash
sudo bash deploy/install.sh --creds /tmp/digest-credentials.env
```

脚本会依次：加密凭据 → shred 明文 → 生成并安装 systemd 单元 → **试跑一次真实任务并发一封邮件** →
成功才启用定时器。

常用参数：

```bash
sudo bash deploy/install.sh --creds <文件> --time 03:00 --tz Asia/Shanghai
sudo bash deploy/install.sh --creds <文件> --user alice --app /opt/arxiv-digest --python /usr/bin/python3
```

### 6. 日常操作

```bash
sudo systemctl start arxiv-digest.service        # 手动跑一次（会发信）
sudo systemctl start arxiv-digest-test.service   # 复盘 72 小时，主题带[测试]
systemctl list-timers arxiv-digest.timer         # 看下次触发
tail -f logs/digest-$(date +%F).log              # 实时日志
```

## 邮件长什么样

```
VLBI 文献日报 · 2026-10-31
抓取 189 篇 → 候选 6 篇 → 入报 6 篇（A3/B3/C0），其中 6 篇做了全文精读

今日概览
  · 重复 FRB 20240209A 的偏振与爆发结构
  · EP241021a：偏核的月尺度暂现源（含 VLBI 定位）

─────────────
A · 必读（全文精读）
[一句话] HST/Gemini 晚期观测定位 EP241021a 为矮星暴盘星系中的偏核暂现源
[背景与问题] ...
[数据与方法] HST/WFC3 + Gemini-N/GMOS，触发后约 300 天
[关键结果] · 投影偏移 0.95 ± 0.13 kpc
           · 宿主 R_e = 1.7 kpc，M* ≈ 3×10^8 Msun
[结论与论证] ...
[局限] ...
[与你研究的关系] ...
[值得追问] ? 多历元 VLBI 能否给出自行上限？
[关键数值] ...
（插图 + 图注 + 这张图支撑了哪条结论）
─────────────
📖 背景补充（非主线，帮助理解）
📡 技术拾遗
─────────────
数据来源：arXiv astro-ph.HE, astro-ph.IM, astro-ph.GA, astro-ph.SR（时间窗 120 小时）
全文来源：arXiv HTML 5 篇 · PDF 1 篇 · 内嵌插图 2 张
生成模型：你的中转站 · gpt-6.1-sol（API 调用 9 次）
```

## 配置参考

| 配置项 | 说明 | 默认 |
|---|---|---|
| `window.min_hours` | 每次至少回看小时数 | 120 |
| `quota.main` / `background` / `instrument` | 各栏目上限 | 25 / 2 / 2 |
| `threshold.main` / `instrument` | 规则打分入榜线 | 26 / 30 |
| `keywords.source` | **你的主线关键词** | VLBI 暂现源示例 |
| `llm.endpoints[].models` | 模型优先级链 | — |
| `llm.endpoints[].dns_pin` | 把域名钉到指定 IP（仅特殊网络环境） | null |
| `deep_read.max_papers` | 每天全文精读篇数（主要成本） | 7 |
| `deep_read.parallel` | 精读并发数 | 3 |
| `deep_read.figures.enabled` | 是否内嵌插图 | true |
| `mail.to` / `mail.cc` | 收件人 / 抄送，逗号分隔 | — |

## 成本

以每天 6 篇全文精读 + 7 篇摘要计：

| 项目 | 量级 |
|---|---|
| 摘要（10 篇/批） | ~4k tokens |
| 全文精读（6 篇 × 3.5 万字符） | ~60k tokens |
| **每天合计** | **~65k tokens** |
| **每月** | **约 200 万 tokens** |

按主流模型价格，每月通常几元到几美元。想省钱：

```yaml
deep_read:
  max_papers: 3       # 只精读 A 级 3 篇
  max_chars: 25000    # 缩短喂入长度
```

## 安全设计

- 凭据用 `systemd-creds` 以主机密钥加密，`/etc/arxiv-digest/credentials.env.cred`（root 600），
  **脱离本机或脱离 root 都无法解密**
- 服务以普通用户运行，沙箱：`ProtectSystem=strict`、`PrivateTmp`、`NoNewPrivileges`
- 代码侧 `src/secrets.py` 对备用凭据文件做权限校验（非 0600 直接拒绝启动）
- 日志中密钥一律脱敏

轮换密钥：

```bash
sudo systemd-creds encrypt --with-key=host --name=arxiv-digest-env <新文件> \
     /etc/arxiv-digest/credentials.env.cred
sudo chmod 600 /etc/arxiv-digest/credentials.env.cred
```

## 常见问题

**没收到邮件？**
先看 `logs/digest-$(date +%F).log` 里有没有 `[邮件] 已发送`。有的话查垃圾箱——建议把发件人加白。
QQ 邮箱对"一封多收件人"较敏感，收件人建议 ≤5 个。

**「新论文 0 条」正常吗？**
正常，说明该时间窗内的论文都已推送过。台账在 `data/ledger.sqlite3`。

**arXiv 每天都公告吗？**
工作日 20:00 ET（= 北京时间次日 08:00 夏令时 / 09:00 冬令时）。默认 03:00 运行拿到的是前一天的批次，
如果在意时效可以改到 09:40。

**LLM 端点连不上？**
页脚会显示降级到了哪个端点。可以用 `dns_pin` 把域名钉到可用 IP（TLS 证书仍按原域名校验）。

**能换成别的研究方向吗？**
可以。改 `keywords` 里的六组词表 + `arxiv.categories` 即可，其余逻辑通用。

## 目录结构

```
src/
  main.py         编排：召回→打分→摘要→精读→渲染→发信→台账
  fetch_arxiv.py  arXiv API 召回与 Atom 解析
  score.py        规则打分
  summarize.py    LLM 客户端（模型链、DNS 钉扎、JSON 校验）
  deep_read.py    全文抓取、压缩、并行精读
  figures.py      图表抽取与下载
  render.py       HTML / 纯文本 / Markdown 渲染
  mailer.py       SMTP 发送（多收件人、内嵌图）
  ledger.py       SQLite 台账
  secrets.py      凭据加载（fail-closed）
  preflight.py    连通性自检
deploy/
  *.service.in    单元模板
  install.sh      一键部署
```

## 许可

MIT