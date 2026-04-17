---
name: public-post-to-obsidian
description: "统一抓取公开内容到 Obsidian Inbox。支持 X/Twitter、微信公众号、飞书/Lark、腾讯会议回放、普通网页。自动识别来源→路由到对应执行器→统一返回结构化结果。触发词: 抓链接、保存到obsidian、inbox、剪藏、抓取、存档、收藏。NOT for: 论文/PDF、批量抓取、需登录互动的站点。"
trigger_words: ["抓链接", "保存到obsidian", "inbox", "剪藏", "抓取", "存档", "收藏", "public post", "capture"]
---

# Public Post To Obsidian

> 一句话：把任意公开链接变成 Obsidian Inbox 里的结构化笔记。

## 何时使用（决策树）

```
用户给了一个链接？
    ├── 是公开内容（无需登录）？
    │       ├── X/Twitter → ✅ 使用本skill
    │       ├── 微信公众号 → ✅ 使用本skill
    │       ├── 飞书/Lark公开页 → ✅ 使用本skill
    │       ├── 腾讯会议回放 → ✅ 使用本skill
    │       ├── 普通网页 → ✅ 使用本skill
    │       └── 需要登录/互动 → ❌ 不适合
    ├── 论文/PDF → ❌ 用 ljg-paper-flow
    ├── 批量链接 → ❌ 用 batch-capture
    └── 其他 → 询问用户意图
```

## 快速入口（复制即用）

```bash
# 基础用法 - 自动识别来源、抓取、保存
python3 /Users/zhangyiran/.openclaw/workspace/skills/public-post-to-obsidian/scripts/run_public_capture.py "<URL>"

# 仅识别来源（调试用）
python3 /Users/zhangyiran/.openclaw/workspace/skills/public-post-to-obsidian/scripts/router.py "<URL>"
```

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
| X/Twitter | `x_api_executor.py` → `x_opencli_executor.py` → `x_executor.py` | API优先 | 带翻译策略 |
| 微信公众号 | `wechat_executor.py` | 单一 | 支持图片本地化 |
| 飞书/Lark | `feishu_executor.py` | 单一 | 需补充参数或浏览器态 |
| 腾讯会议 | `tencent_meeting_executor.py` | 单一 | 默认逐字稿，可选视频 |
| 普通网页 | `generic_web_executor.py` | 单一 | 带翻译策略 |

## 边界条件与异常处理

| 场景 | 处理策略 |
|------|---------|
| 来源识别失败 | 回退到 `generic_web_executor.py` |
| API 限流/失败 | X: 自动降级到 opencli → 基础 executor |
| 内容为空/截断 | 标记 `status=partial`，提示用户检查 |
| 需要登录态 | 标记 `status=auth_required`，转人工处理 |
| 路径不存在 | 自动创建目录，失败则标记 `status=error` |
| 资源下载失败 | 继续保存 markdown，标记 `asset_count=0` |

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
- 飞书机制、坑位与绕过：`references/feishu.md`
- 腾讯会议回放说明：`references/tencent-meeting.md`
- 分享与打包说明：`README-share.md`

## 测试验证

典型测试场景：
1. **X 帖子** - 带图片，验证翻译策略触发
2. **微信公众号** - 长文，验证图片本地化
3. **普通网页** - 复杂排版，验证内容提取完整性

---

**版本**: 1.1.0 | **更新**: 2026-04-15 | **维护者**: OpenClaw
