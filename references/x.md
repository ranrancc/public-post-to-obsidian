# X / Twitter

## 执行顺序

X 抓取不是单一路径，而是四段回退：

1. `scripts/x_api_executor.py`
2. `scripts/x_fxtwitter_executor.py`
3. `scripts/x_opencli_executor.py`
4. `scripts/x_executor.py`

默认原则：

- 优先走 API
- API 不可用时先走公开 FxTwitter 链路
- 再尝试 opencli 登录态浏览器，最后退到 Jina 轻量链路
- 统一入口同时检查执行器退出码和 JSON `status`，不会把“退出码 0 的错误 JSON”误判为成功

## 各链路说明

### `x_api_executor.py`

适用：

- X Article / 长文
- 普通 `status` 链接
- 希望长期稳定、尽量少依赖浏览器时

依赖：

- `X_BEARER_TOKEN`，兼容 `TWITTER_BEARER_TOKEN`

特点：

- 直接调用 X API v2 读取元数据与媒体
- 对 X Article 会继续用 FxTwitter 的 `article.content.blocks + entityMap` 重建正文
- `MEDIA` 会原位落成图片
- `MARKDOWN` 会尽量按代码块 / 文本块回填

优点：

- 不依赖浏览器扩展
- 对长文和技术内容最稳定
- 图文顺序保真度更高

限制：

- 需要可用 token

### `x_fxtwitter_executor.py`

适用：

- `/<username>/status/<id>` 形式的公开帖子和 X Article
- 没有 X API token，或 API 临时认证/限流失败时

特点：

- 直接重建 `article.content.blocks + entityMap`
- 不需要浏览器登录态
- 属于第三方公开服务，响应结构或可用性可能变化，因此始终保留后续回退

### `x_opencli_executor.py`

适用：

- API 不可用，但本机浏览器环境完整
- 需要抓浏览器里实际可见的 X 长文内容

依赖：

- 本机安装 `opencli`
- Chrome 已安装并启用 opencli Browser Bridge
- 浏览器里已有可用的 X 登录态

优点：

- 对一部分 X 长文正文抓取比轻量链路稳

限制：

- 扩展断连或登录态失效就会失败
- 当前执行器只做有限自动恢复

### `x_executor.py`

适用：

- 只需要纯公开、轻量、尽快兜底

机制：

- 走 `r.jina.ai/http://x.com/...`

限制：

- 稳定性最差
- 可能拿到占位页、登录墙或半截标题

## 翻译行为

X 目前支持：

- `ask`
- `translate`
- `original`
- `both`

若结果不是简体中文，统一入口通常会先询问用户。

## 落盘标记

X Article 当前会保留：

- `capture_method: x-api-v2`
- `render_method: x-api-v2+fxtwitter-blocks` 或 `x-api-v2`
- FxTwitter 独立成功时：`capture_method: fxtwitter-public-api`

判断原则：

- 成功 block 重建 -> `x-api-v2+fxtwitter-blocks`
- 普通帖子或回退正文 -> `x-api-v2`

## 分发给别人时要说明

- 没有 `X_BEARER_TOKEN` 时会跳过官方 API，不会阻断后续公开回退
- 没有 `opencli`、Browser Bridge 和 X 登录态时，也不能承诺浏览器链路可用
- 纯公开分发版仍可使用 FxTwitter → Jina，但应说明 FxTwitter 是非官方依赖
