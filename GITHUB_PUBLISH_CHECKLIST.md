# Public Post To Obsidian GitHub 发布准备清单

这个 skill 很适合放到 GitHub，但建议先做一轮“分享版整理”，再公开。

## 当前适合公开的部分

- 核心定位清晰：公开链接抓取到 Obsidian Inbox
- 路由结构清晰：`router.py` + `run_public_capture.py`
- 场景覆盖有吸引力：X、微信公众号、飞书公开页、腾讯会议回放、普通网页
- 输出契约明确：统一 JSON 结果，便于复用和二次集成

## 发布前必须处理

### 1. 去掉个人绝对路径

当前发现的问题：

- `scripts/common.py`
- `scripts/feishu_executor.py`
- `SKILL.md`
- `references/*.md`

这些文件里仍包含类似 `/Users/zhangyiran/...` 的路径。

建议改法：

- 所有脚本入口都改成相对路径推导
- 所有输出目录改成可配置项
- 文档示例改成仓库相对路径或通用命令

目标状态：

```bash
python3 scripts/run_public_capture.py "<URL>"
```

而不是依赖你本机的完整目录。

### 2. 把 Obsidian / OneDrive 路径配置化

当前发现的问题：

- `scripts/common.py` 里写死了：
  - `VAULT_ROOT`
  - `LECTURE_ARCHIVE_ROOT`

这会导致别人 clone 后几乎无法直接运行。

建议改法：

- 优先从环境变量读取
- 没配时给出清晰报错
- 可以提供 `.env.example`

推荐变量名：

```env
PUBLIC_POST_OBSIDIAN_VAULT_ROOT=
PUBLIC_POST_LECTURE_ARCHIVE_ROOT=
```

### 3. 明确哪些能力需要额外账号或密钥

当前发现的问题：

- X 可能依赖 `X_BEARER_TOKEN` / `TWITTER_BEARER_TOKEN`
- 网页标题清理可能依赖 `OPENAI_API_KEY`
- 翻译流程提到了 `kimi`
- 网页抓取依赖本地浏览器和 JS 运行时

建议在 GitHub README 里单独写：

- 必需依赖
- 可选依赖
- 哪些功能在“无 API Key”时仍可用

### 4. 检查 vendored 代码的公开边界

当前发现的问题：

- 你 vendored 了 `baoyu-url-to-markdown`
- `README-share.md` 还提到包含 `node_modules`

发布前要确认：

- 上游许可证允许这样分发
- 你是否真的要把 `node_modules` 一起提交
- 是否更适合只保留 `package.json` / lockfile，让用户自行安装

如果目标是“让高校教师也能尝试”，保留 vendored 代码是可以理解的；
但如果目标是“让开发者愿意 fork 和维护”，仓库最好更轻、更干净。

## 强烈建议再处理

### 5. 增加一个真正面向 GitHub 的 README

目前 `SKILL.md` 更像给 agent 看的，`README-share.md` 更像内部分享说明。

建议新增标准 `README.md`，结构如下：

1. 这个项目解决什么问题
2. 适合谁用
3. 支持哪些来源
4. 安装方式
5. 最小可运行示例
6. 输出到哪里
7. 常见问题
8. 路线图

### 6. 减少“只对你自己有意义”的术语

比如：

- `Inbox`
- 某些特定目录命名
- 你自己的工作流词汇

建议保留 Obsidian 语境，但把它们解释成通用概念，例如：

- “保存到指定 Obsidian 文件夹”
- “生成 Markdown 笔记与附件目录”

### 7. 增加最小 smoke test

建议至少保留一条可复制测试命令：

```bash
python3 scripts/run_public_capture.py --dry-run https://example.com
```

以及一条真实测试命令：

```bash
python3 scripts/run_public_capture.py \
  --web-backend auto \
  --translation-choice original \
  https://example.com
```

## 高校教师版本的定位建议

如果你想把它包装成“适合高校教师使用”的 skill，GitHub 首页不要先讲技术栈，先讲应用场景：

- 收藏讲座/公众号文章并进入备课资料库
- 保存公开网页形成课程笔记素材
- 抓取腾讯会议回放逐字稿用于整理教研记录
- 把零散公开内容统一沉淀到 Obsidian

一句话定位建议：

> 一个面向高校教师与知识工作者的公开内容采集工具，把网页、公众号、X、飞书公开页和会议回放统一整理成 Obsidian 笔记。

## 推荐发布顺序

### 路线 A：先发布“可运行版”

适合你现在立刻开始：

1. 先做脱敏
2. 先补 README
3. 先公开一个仓库
4. 先让别人能跑通普通网页抓取
5. 其余来源逐步补强

优点：

- 起步快
- 容易获得早期反馈

缺点：

- 代码会比较“工程中”

### 路线 B：先整理成“展示版”

适合你希望第一印象更成熟：

1. 先把配置项抽出来
2. 先清理 vendored 依赖策略
3. 先写面向教师用户的 README
4. 再发布

优点：

- 更适合转发
- 更容易被别人理解和复用

缺点：

- 首发会慢一点

## 我建议你的第一步

最稳妥的下一步是：

1. 先把这个 skill 复制成一个“GitHub 分享版”目录
2. 我帮你把绝对路径改成“首次运行向导 + 默认保存目录”
3. 我再帮你生成正式 `README.md`
4. 我们把默认输出做成两种模式：
5. `Obsidian Markdown (.md)`
6. `普通文本 (.txt)`
7. 最后再决定是否把 vendored 依赖一起提交

## 小白打包版的推荐产品规则

如果用户没有 Obsidian，建议不要卡住，更不要报配置错误。

推荐规则：

- 第一次运行先问是否使用 Obsidian
- 如果不使用，默认保存到下载目录
- 默认建立一个固定文件夹：`Public Post To Obsidian`
- 文件格式允许二选一：`.md` 或 `.txt`

推荐默认路径：

- macOS: `~/Downloads/Public Post To Obsidian/`
- Windows: 用户下载目录下的同名文件夹

推荐默认格式：

- 默认 `.md`
- 小白模式可以切换成 `.txt`

这样做的好处：

- 没有 Obsidian 也能立即试用
- 结果文件更容易找到
- 降低首次使用门槛

## 当前结论

这个 skill 值得放上 GitHub，而且题材也很好。

但在公开前，至少要先完成两件事：

- 路径与环境配置脱敏
- README 从“给自己/给 agent 看”改成“给陌生用户看”
