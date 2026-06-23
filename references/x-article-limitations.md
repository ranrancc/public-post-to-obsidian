# X Article 抓取限制

## 背景

X 平台有两种帖子形态：
- **普通帖子（Tweet）**：短文本 + 可选图片/视频，可通过 API v2 和匿名浏览器抓取
- **X Article（长文）**：类似 Medium 的富文本文档，内嵌于 X 平台

## 当前能力与限制

X Article 的可用性取决于具体入口，而不是一概要求 OAuth 用户令牌：

| 方式 | 结果 | 原因 |
|------|------|------|
| X API v2 (`x_api_executor.py`) | 首选 | 当前有效 app Bearer Token 可读取 Article 字段；401 应先诊断 token 是否实际加载 |
| FxTwitter (`x_fxtwitter_executor.py`) | 公开兜底 | 可重建 blocks 和图片，但属于第三方服务，不能视为永久稳定 API |
| 匿名浏览器 | 登录墙 | X 对 Article 强制要求登录态 |
| Jina AI (`r.jina.ai`) | 500 Internal Server Error 或空内容 | Jina 也无法穿透 Article 的认证层 |
| OpenCLI (`x_opencli_executor.py`) | `BROWSER_CONNECT` | 需要登录态浏览器扩展 |

## 已知案例

- `https://x.com/CivicOrderism/status/2069214449123119434`（2026-06-23）：在未加载 Hermes token 时复现 401；加载有效 Bearer Token 后官方完整字段请求返回 200，FxTwitter 同时可返回 65 个正文块。

## 处理策略

1. 检查 `fallback_chain`，区分 token 缺失、401、429、服务超时和内容为空
2. 自动按 X API → FxTwitter → OpenCLI → Jina 执行
3. 所有执行器失败后才标记 `error`，不以单个 401 推断 Article 永久不可抓取
