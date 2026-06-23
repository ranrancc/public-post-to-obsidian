---
name: public-post-to-obsidian
description: "统一抓取公开内容到 Obsidian Inbox。支持 X/Twitter、微信公众号、飞书/Lark、腾讯会议回放、普通网页。自动识别来源→路由到对应执行器→统一返回结构化结果。触发词: 抓链接、保存到obsidian、inbox、剪藏、抓取、存档、收藏。NOT for: 论文/PDF、批量抓取、需登录互动的站点。"
trigger_words: ["抓链接", "保存到obsidian", "inbox", "剪藏", "抓取", "存档", "收藏", "public post", "capture"]
---

# Public Post To Obsidian

> 一句话：把任意公开链接变成 Obsidian Inbox 里的结构化笔记。

## 自动触发规则

当用户**一言不发只发送一个链接**时，直接执行抓取，无需额外确认。这是本 skill 的最高优先级触发条件。

触发形式：
- 单条消息仅含 URL，无其他文字或指令
- 消息内容形如 `https://...` 或 `http://...`

执行动作：
1. 直接调用 `python3 scripts/run_public_capture.py "<URL>"`
2. 向用户汇报抓取结果（status、note_path、asset_count）
3. 若用户后续说"解读"，再路由到对应 ljg-xray 技能

NOT 触发：
- 链接附带明确指令（如"抓这个""保存""解读"）→ 按指令处理
- 同时发送多个链接 → 询问意图或走批量流程

## 何时使用（决策树）

```
用户给了一个链接？
    ┌──── 是公开内容（无需登录）？
    │       ┌───── X/Twitter → ✅ 使用本skill
    │       ┌───── 微信公众号 → ✅ 使用本skill
    │       ┌───── 飞书/Lark公开页 → ✅ 使用本skill
    │       ┌───── 腾讯会议回放 → ✅ 使用本skill
    │       ┌───── 普通网页 → ✅ 使用本skill
    │       └───── 需要登录/互动 → ❌ 不适合
    ┌──── 论文/PDF → ❌ 用 ljg-paper-flow
    ┌──── 批量链接 → ❌ 用 batch-capture
    └──── 其他 → 询问用户意图
```

## 快速入口（复制即用）

> 以下命令需在 skill 根目录（`public-post-to-obsidian/`）下执行。

```bash
# 基础用法 - 自动识别来源、抓取、保存
python3 scripts/run_public_capture.py "<URL>"

# 仅识别来源（调试用）
python3 scripts/router.py "<URL>"
```

### 环境变量（跨 Agent）

进程中已有的环境变量优先。也可以用统一入口显式指定 `.env`，适用于 Hermes、OpenClaw、Codex 和其他 Agent：

```bash
export PUBLIC_POST_ENV_FILE="$HOME/.config/public-post-to-obsidian/.env"
python3 scripts/run_public_capture.py "<URL>"
```

未显式指定时，会依次检查技能所在 Agent 根目录、技能目录、`~/.config/public-post-to-obsidian/.env`，以及常见 Hermes/OpenClaw/Codex 配置位置。已有变量不会被后续文件覆盖。仓库只提交 `.env.example`，不得提交真实密钥。

## 核心工作流（5步闭环）

```
┌─────────────────────────────────────────────────────────────┐
│  Step 1: 识别                                                │
│  └── router.py 分析 URL → 确定 source_type                   │
├─────────────────────────────────────────────────────────────┤
│  Step 2: 路由                                                │
│  └── run_public_capture.py 分发到对应执行器                   │
├─────────────────────────────────────────────────────────────┤
│  Step 3: 执行                                                │
│  └── 各执行器抓取内容 → 生成 markdown + assets               │
├─────────────────────────────────────────────────────────────┤
│  Step 4: 校验                                                │
│  └── 检查 status、note_path、assets_dir、asset_count        │
├─────────────────────────────────────────────────────────────┤
│  Step 5: 确认                                                │
│  └── 向用户报告结果路径 + 预览关键字段                        │
└─────────────────────────────────────────────────────────────┘
```

## 路由规则与执行器映射

| 来源 | 执行器 | 优先级 | 备注 |
|------|--------|--------|------|
| X/Twitter | `x_api_executor.py` → `x_fxtwitter_executor.py` → `x_opencli_executor.py` → `x_executor.py` | 能力降级 | 每一步均检查 JSON status 与退出码 |
| 微信公众号 | `wechat_executor.py` → 浏览器兜底（见 `references/wechat-browser-fallback.md`） | playwright优先 | 支持图片本地化；playwright缺失时降级为浏览器JS提取 |
| 飞书/Lark | `feishu_executor.py` | 单一 | 需补充参数或浏览器态 |
| 腾讯会议 | `tencent_meeting_executor.py` | 单一 | 默认逐字稿，可选视频 |
| 普通网页 | `generic_web_executor.py` | 单一 | 带翻译策略 |

## 边界条件与异常处理

| 场景 | 处理策略 |
|------|---------|
| X API 认证失败 / Token 缺失 | 自动尝试 FxTwitter → OpenCLI → Jina，并在 `fallback_chain` 中记录每次结果 |
| X Article（长文帖子） | API 或 FxTwitter 任一可用即可重建正文；两者失败后再尝试登录态浏览器和 Jina |
| 来源识别失败 | 回退到 `generic_web_executor.py` |
| API 限流/失败 | X: 仅对 429/5xx/网络错误有限重试，再自动降级到 FxTwitter → OpenCLI → Jina；401/403 不盲目重试 |
| 内容为空/截断 | 标记 `status=partial`，提示用户检查 |
| 需要登录态 | 标记 `status=auth_required`，转人工处理 |
| 微信公众号 playwright 缺失 | `ModuleNotFoundError: No module named 'playwright'` → 降级为浏览器兜底（`references/wechat-browser-fallback.md`） |
| 路径不存在 | 自动创建目录，失败则标记 `status=error` |
| 资源下载失败 | 继续保存 markdown，标记 `asset_count=0` |

## Obsidian 目标目录规则

| 来源 | 目标目录 |
|------|---------|
| X/Twitter | `00-Inbox/` |
| 微信公众号 | `00-Inbox/微信剪藏/` |
| 视频/播客 | `00-Inbox/视频剪藏/` |
| 其他网页 | `00-Inbox/`（按内容主题可移到 `01-摘录库/` 对应子目录） |

## 检查点（人在回路）

- **抓取前**：向用户确认目标目录（默认 Inbox，可覆盖）
- **抓取后**：报告 `note_path` 和 `asset_count`，让用户确认内容完整性
- **异常时**：不猜测，不硬编，明确标记状态并转人工

## 输出字段说明

```json
{
  "source_type": "x|wechat|feishu|tencent_meeting|web",
  "handler_used": "具体执行器名称",
  "target_dir": "文件保存目录",
  "status": "success|partial|error|auth_required",
  "note_path": "markdown文件完整路径",
  "assets_dir": "资源目录（如有）",
  "asset_count": 0,
  "fallback_chain": [{"handler": "x-api-v2", "status": "error", "returncode": 1}],
  "stdout": "执行器输出",
  "stderr": "错误信息（如有）"
}
```

## 故障排查速查表

| 现象 | 第1步检查 | 第2步检查 | 第3步检查 |
|------|----------|----------|----------|
| 抓取失败 | `router.py` 识别正确？ | 对应执行器单独运行正常？ | `references/*.md` 查看专门说明 |
| 内容为空 | URL 是否需要登录？ | 执行器依赖是否完整？ | 目标站点是否反爬？ |
| 图片丢失 | `asset_dir` 是否存在？ | 图片链接是否可访问？ | 磁盘空间是否充足？ |
| 格式错乱 | 源站结构是否变化？ | 执行器是否需要更新？ | 是否触发翻译策略？ |

## 参考文档

- X 详细链路、依赖与回退：`references/x.md`
- X Article 抓取限制：`references/x-article-limitations.md`
- 飞书机制、坑位与绕过：`references/feishu.md`
- 腾讯会议回放说明：`references/tencent-meeting.md`
- Hermes 环境集成（目录双轨制、Token 加载、路径自适应）：`references/hermes-integration.md`
- 微信公众号浏览器兜底抓取（playwright 缺失时的降级方案）：`references/wechat-browser-fallback.md`
- 分享与打包说明：`README-share.md`

## 测试验证

典型测试场景：
1. **X 帖子** - 带图片，验证翻译策略触发
2. **微信公众号** - 长文，验证图片本地化
3. **普通网页** - 复杂排版，验证内容提取完整性

---

**版本**: 1.2.0 | **更新**: 2026-06-23 | **维护者**: OpenClaw / Hermes portable
