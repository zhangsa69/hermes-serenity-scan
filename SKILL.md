---
name: serenity-scan
description: 监控 @aleabitoreddit（白毛股神 Serenity）Twitter 推文，自动采集→翻译→解读→邮件推送→小红书发布→飞书通知。依赖 Camofox 浏览器 + Hermes cron。
version: 1.0.0
author: hermes
tags: [monitoring, twitter, serenity, camofox, cron, social, xiaohongshu, email]
dependencies:
  - camofox-browser
  - xhs-note-creator
---

# Serenity Scan — 白毛股神推文监控

监控 @aleabitoreddit（Serenity / 白毛股神）的 Twitter 推文，全自动流水线：

```
Camofox 浏览器采集推文 → 去重（snowflake ID）→ 
  → 🥇 邮件群发（67人BCC）
  → 🥈 小红书卡片发布（原文+直译+解读）
  → 🥉 飞书推送
```

## 前置依赖

### 1. Camofox 浏览器
```bash
# 安装 Camofox 浏览器 skill
hermes skills install camofox-browser

# 确保 Camofox 运行在 localhost:9377
curl http://localhost:9377/health  # → {"ok":true}

# 导入 Twitter cookies（需已登录 X.com）
# 参考 camofox-browser skill 的 cookie 导入流程
```

### 2. 小红书发布
```bash
hermes skills install xhs-note-creator

# 配置 .env
cd /opt/data/skills/xhs-note-creator
cat > .env << 'EOF'
XHS_COOKIE="a1=...; web_session=...;"
EOF
```

### 3. 邮件脚本（可选，仅需群发时）
将 `scripts/send_serenity_emails.py` 复制到 `/opt/data/scripts/`，修改 `RECIPIENTS` 列表。

### 4. 卡片生成脚本
将 `scripts/xhs_tweet_card.py` 复制到 `/opt/data/scripts/`。

## 快速开始

### Step 1: 部署监控脚本
```bash
# 复制监控脚本到 Hermes scripts 目录
cp scripts/monitor_serenity.py /opt/data/scripts/
chmod +x /opt/data/scripts/monitor_serenity.py

# 首次运行（静默播种缓存，不产生输出）
python3 /opt/data/scripts/monitor_serenity.py
```

### Step 2: 创建 cron 任务
```bash
# 通过 Hermes 的 cronjob 工具创建（在 Hermes chat 中执行）
# Schedule: every 1m（每分钟采集，去重缓存保证 0 成本）
# Script: monitor_serenity.py
# Skills: serenity-scan（本技能）+ social-monitoring（可选）
# Deliver: feishu（飞书自动推送）
# Enabled toolsets: terminal, file
```

### Step 3: 测试
```bash
# 手动运行一次验证
python3 /opt/data/scripts/monitor_serenity.py
# 有输出 → 新推文已采集，cron 会处理
# 无输出 → 无新推文，正常
```

## 工作流详解

### 监控脚本 (monitor_serenity.py)

1. 通过 Camofox API 打开 `https://x.com/aleabitoreddit`
2. 等待 SPA 加载 → 滚动触发推文渲染
3. 两遍点击 "Show more" 展开折叠文本
4. JS 提取前 5 条推文（含作者过滤 + 回复过滤）
5. Snowflake ID 去重（首次运行静默播种）
6. 输出 JSON：`{"count": N, "tweets": [...], "checked_at": "..."}`

### Agent 处理（cron prompt）

当脚本输出 `count > 0` 时，agent 按以下顺序执行：

**🥇 STEP 1: 邮件推送**（MUST BE FIRST）
```
生成邮件正文 → send_serenity_emails.py --tweet-id <ID>
67人BCC群发，自动去重
```

**🥈 STEP 2: 小红书卡片发布**
```
xhs_tweet_card.py → 生成原文+直译卡片（最多N页）
publish_xhs.py --public → 发布（标题≤20字，desc=纯解读）
```

**🥉 STEP 3: 飞书推送**
Agent 最终回复自动投递到飞书

### 三文本分离规则

| # | 名称 | 内容 | 参数 | 目标 |
|---|------|------|------|------|
| A | 全文逐句直译 | 严谨逐句翻译，不省略 | `--translation` | 卡片图片「中文翻译」|
| B | 解读/分析 | 纯分析，微信八卦风 | `--desc` | 小红书正文 |
| C | 原文 | 推文原文，不修改 | `--tweet` | 卡片图片「原文」|

**铁律：**
- 翻译必须全文逐句直译，不能省略或概括
- 分析中称呼白毛股神为「白毛女神」，用「她」
- 标题格式 `YY年M月D日 HH:MM 白毛股神`（≤20字）
- desc 纯中文，禁止英文缩写

## Cron Prompt 模板

以下为 cron job 的完整 prompt（可直接使用）：

```
Read the data-collection script output below. It contains JSON: {"count": N, "tweets": [...], "checked_at": "..."}.

If "count" == 0 OR there is no output → respond with exactly "[SILENT]" and nothing else.

If "count" > 0 → process ALL tweets. EXECUTION ORDER IS MANDATORY:

━━━━━━━━━━━━━━━━━━━━━━
🥇 STEP 1: 邮箱推送（MUST BE FIRST — DO NOT SKIP）
━━━━━━━━━━━━━━━━━━━━━━
For each tweet, write email body and send via BCC script:
cat > /tmp/email_body.txt << 'EMAILEOF'
发文时间（北京时间）：[UTC+8]
原文：> [tweet original]
解读：[Chinese analysis, WeChat style]
链接：[tweet URL]
EMAILEOF
python3 /opt/data/scripts/send_serenity_emails.py "🔔 白毛股神 新推文" /tmp/email_body.txt --tweet-id <TWEET_ID>

✅ Verify email sent. Both "OK BCC sent" and "SKIP" are successes.
🚫 Step 1 失败 → 全流程终止

━━━━━━━━━━━━━━━━━━━━━━
🥈 STEP 2: 小红书卡片 + 发布（每推文独立，只发一次）
━━━━━━━━━━━━━━━━━━━━━━
For each tweet:
DIR=$(mktemp -d)
python3 /opt/data/scripts/xhs_tweet_card.py \
  --tweet "原文" --time "UTC时间" \
  --translation "中文直译（中文推文复用原文）" --out "$DIR"
DESC=$(cat /tmp/desc.txt)
cd /opt/data/skills/xhs-note-creator && python3 scripts/publish_xhs.py \
  --title "26年6月5日 19:37 白毛股神" --desc "$DESC" \
  --images $(ls "$DIR"/card_*.png | sort) --public
rm -rf "$DIR"

🚫 铁律：标题≤20字 | 三文本分离 | 白毛女神 | desc纯中文 | 不发重试

━━━━━━━━━━━━━━━━━━━━━━
🥉 STEP 3: Feishu 推送（自动 — your response IS the delivery）
━━━━━━━━━━━━━━━━━━━━━━
**发文时间（北京时间）：** [UTC+8]
**原文：** > [original]
**解读：** [Chinese analysis]
**链接：** [tweet URL]

多条 --- 分隔。BJ时间精确到分钟。微信八卦风。
```

## 缓存与去重

- **Snowflake ID 缓存**: `.serenity_cache/last_max_id.txt` — 记录已处理的最高 tweet ID
- **首次运行**: 自动播种缓存（`.seeded` 标记），静默退出
- **邮件去重**: `send_serenity_emails.py --tweet-id` → 检查 `.serenity_cache/last_emailed_id.txt`
- **缓存清理**: 删除 `.serenity_cache/` 目录重新开始

## 故障排查

| 症状 | 原因 | 修复 |
|------|------|------|
| 脚本输出 0 字节 | Camofox 挂了 | `curl localhost:9377/health` → 重启 Camofox |
| 邮件重复发送 | SMTP 超时后的重试 | `--tweet-id` 去重自动处理 |
| 小红书发布失败 | Cookie 过期 | 重新导出 XHS_COOKIE |
| 飞书无推送 | cron deliver 配置错误 | 确认 `deliver: feishu` |
| 推文丢失 | 缓存被污染 | 删除 `.serenity_cache/` |

## 目录结构

```
serenity-scan/
├── SKILL.md                    # 本文件
├── scripts/
│   ├── monitor_serenity.py     # 推文采集脚本
│   ├── send_serenity_emails.py # 邮件群发脚本（67人BCC）
│   └── xhs_tweet_card.py       # 小红书卡片生成
└── references/
    └── cron-prompt-full.md     # 完整 cron prompt
```
