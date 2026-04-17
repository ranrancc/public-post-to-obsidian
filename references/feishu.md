# Feishu / Lark

## 统一入口

飞书链路当前以本 skill 自带实现为准：

- `scripts/feishu_executor.py`
- `scripts/grab_feishu_public_doc.js`
- `scripts/feishu_probe.py`
- `scripts/audit_feishu_exports.py`

## 运行前认知

- 飞书通常仍需要额外运行时参数
- 公开页参数和 cookie 往往要先从浏览器环境拿到
- 如果只想走统一入口，优先调用 `scripts/feishu_executor.py`

统一入口补参数示例：

```bash
python3 /Users/zhangyiran/.openclaw/workspace/skills/public-post-to-obsidian/scripts/run_public_capture.py \
  --page-id '...' \
  --space-id '...' \
  --container-id '...' \
  --title '...' \
  --cookie-header '...' \
  'https://waytoagi.feishu.cn/wiki/...'
```

## 已验证的关键机制

- 正文不能只靠页面可见 DOM 抓；稳定来源是 `space/api/docx/pages/client_vars`
- 图片下载后可能是加密内容，需要用 `cdn_url` 返回的 `secret + nonce` 做 `AES-256-GCM` 解密
- 图片扩展名不能信原始文件名，要按魔数识别真实格式

## 落盘规范

- 主文件：`YYYYMMDD--标题__note.md`
- 附件目录：`assets/{笔记文件名}/`
- 图片引用：`![[assets/笔记文件名/file-xxx.png]]`

`meta.json` 是审计 / 排错产物，不是最终阅读产物的必要部分。

## 已知坑

- 有些公开页会出现 `has_more=true` 但 `next_cursors=[]`
- 这时不能停，还要继续尝试 `data.cursor`
- code block 最后一行文本可能和闭合 ``` 连在同一行；如果不修，Obsidian 会把后面全当代码块

## `my.feishu.cn/docx/` 类型

现状：

- `feishu_probe.py` 只找 `wiki/v2/tree/get_node`
- docx 页面不发这个请求，所以探针可能直接失败

临时绕过：

```bash
python3 ~/.openclaw/workspace/tools/feishu_docx_grab.py \
  "$COOKIE" \
  "https://my.feishu.cn/docx/TOKEN" \
  "~/Library/Mobile Documents/iCloud~md~obsidian/Documents/ZYR/00-Inbox/网页剪藏/"
```

关键机制：

- 用 Playwright 注入 session cookie
- 监听页面里的 `client_vars?id=TOKEN&mode=7&...` 分页响应
- `block_sequence` 就是阅读顺序
- 图片可通过 drive stream 接口下载

## Cookie 说明

- session 常有时效，不能当长期稳定凭据
- `session` 通常需要从 DevTools 手动复制
- 有时还要配合 `passport_app_access_token` 和 `msToken`
- 如果只看 `next_cursors`，可能静默截断文档后半段

## 当前支持面

- 长文正文
- 多图教程
- Markdown 表格导出
- `heading4`
- ordered list
- quote / callout
- `view` 包裹块
- `file` 块占位保留

## 当前限制

- 参数和 cookie 获取仍偏依赖浏览器
- 视频附件下载已验证可行，但还不是主流程内建能力
- 如果只需要最终笔记，默认不应把 `meta.json` 当作必要产物
