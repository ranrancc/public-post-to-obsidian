# Public Post To Obsidian

把公开网页、公众号文章、飞书公开页、腾讯会议回放整理成笔记文件。

如果你用了 Obsidian，它可以直接保存成适合 Obsidian 的 Markdown。
如果你没用 Obsidian，它也应该能默认保存到本地下载目录，并可选导出成 `.txt`。

这个项目特别适合这样的用户：

- 想把网上看到的内容沉淀到 Obsidian
- 想做备课资料、教研资料、课程素材库
- 不想每次都手动复制粘贴和整理格式

## 能做什么

这个面向小白用户的打包版，建议优先支持这些公开链接：

- X / Twitter 公开帖子（详见 [X 抓取说明](references/x.md)）
- 微信公众号文章
- 飞书 / Lark 公开页面
- 腾讯会议公开回放
- 普通网页文章

输出结果通常包括：

- 一篇笔记文件
- 一个附件目录（如果有图片）
- 一份结构化结果信息，方便排查问题

## 适合谁

这个工具优先面向：

- 高校教师
- 研究生
- 知识管理用户
- 使用 Obsidian 做资料整理的人

## 开始前先知道

这是一个“公开内容采集器”。

它适合：

- 公开可访问的网页
- 不需要登录就能打开的内容

它不适合：

- 论文 PDF
- 批量抓取很多链接
- 需要登录、点按钮、互动后才能看到的页面

## 安装方式

### 第 1 步：下载项目

如果你会用 Git：

```bash
git clone https://github.com/ranrancc/public-post-to-obsidian.git
cd public-post-to-obsidian
```

如果你不会用 Git：

1. 打开这个仓库首页
2. 点击 `Code`
3. 点击 `Download ZIP`
4. 解压后进入项目文件夹

### 第 2 步：安装基础环境

你至少需要：

- `Python 3`
- 一个本地浏览器：Chrome / Chromium / Edge

有些网页抓取还会用到：

- `bun` 或 `npx`

如果你完全是新手，建议先确认下面三个命令里至少前两个能运行：

```bash
python3 --version
google-chrome --version
bun --version
```

如果你的电脑里没有 `google-chrome` 这个命令，也没关系，只要已经安装了 Chrome、Chromium 或 Edge，后续通常也能用。

普通网页的浏览器抓取源码已放在 `vendor/`，仓库不包含 `node_modules`。首次使用前安装依赖：

```bash
cd vendor/baoyu-url-to-markdown/scripts
bun install
cd ../../..
```

没有 `bun` 命令但已安装 Node.js/npm 时，可将 `bun install` 替换为 `npx -y bun install`。

### 第 3 步：第一次运行会让你选择保存位置

这个工具不要求你手动编辑 `.env`。

第一次真实运行时，它会询问你的默认保存方式：

1. `Obsidian Inbox`
2. `下载目录`
3. `自定义目录`

然后它还会询问默认文件格式：

1. `.md`
2. `.txt`

选完之后，程序会自动记住，以后不需要重复设置。

对普通用户来说，推荐这样选：

- 如果你平时用 Obsidian，就选 `Obsidian Inbox`
- 如果你不用 Obsidian，就选 `下载目录`
- 如果你想自己管理资料位置，就选 `自定义目录`

## 第一次运行

### 先做一个安全测试

这条命令不会真正抓取，只会告诉你“它准备怎么处理这个链接”：

```bash
python3 scripts/run_public_capture.py --dry-run https://example.com
```

如果看到类似这些信息，说明入口已经正常：

- `source_type`
- `command`
- `status: ready`

### 再做第一次真实抓取

```bash
python3 scripts/run_public_capture.py https://example.com
```

建议第一次先用普通网页测试，成功率最高。

第一次真实抓取时，你通常会看到类似这样的提示：

```text
首次使用 Public Post To Obsidian，需要先设置默认保存位置。
请选择保存位置：1=Obsidian Inbox，2=下载目录，3=自定义目录 [默认 2]
请选择默认文件格式：1=.md，2=.txt [默认 1]
```

如果你只是想先试一下，最简单的选择是：

- 保存位置选 `2`
- 文件格式选 `1`

这样结果会默认保存到下载目录里的 `Public Post To Obsidian` 文件夹。

## 常见使用方式

### 抓取普通网页

```bash
python3 scripts/run_public_capture.py "https://example.com/article"
```

### 抓取微信公众号文章

```bash
python3 scripts/run_public_capture.py "https://mp.weixin.qq.com/s/xxxx"
```

### 抓取飞书公开页

```bash
python3 scripts/run_public_capture.py "https://xxx.feishu.cn/wiki/xxxxx"
```

### 抓取腾讯会议回放

```bash
python3 scripts/run_public_capture.py "https://meeting.tencent.com/cw/xxxxx"
```

## 对小白更友好的默认保存方式

当前版本的默认行为是这样：

- 第一次运行时询问保存位置
- 记住你的选择
- 以后按这个默认值继续保存

推荐默认路径：

- macOS: `~/Downloads/Public Post To Obsidian/`
- Windows: `下载/Public Post To Obsidian/`

推荐默认格式：

- 默认 `Markdown (.md)`
- 小白模式可切换成 `Text (.txt)`

这样做的好处是：

- 用户不需要先理解 Obsidian
- 就算不用 Obsidian，也能马上看到成果
- `.txt` 对很多老师来说更熟悉

## 可选功能

有些功能不是必须的，但会让体验更好。

### 1. 非中文内容自动翻译

翻译通过 API 调用，支持 `deepseek`、`openrouter`、`openai` 三种 provider，不需要本地 `kimi` 命令。

在私有 `.env` 或进程环境中配置对应密钥：`DEEPSEEK_API_KEY`、`OPENROUTER_API_KEY` 或 `OPENAI_API_KEY`。模型使用 `provider:model` 格式；请填写你所用服务中可用的模型 ID。

```bash
python3 scripts/run_public_capture.py \
  --translation-choice both \
  --translation-model "provider:model" \
  "https://example.com/article"
```

上面的 `provider:model` 是占位符，运行前需替换。模型选择顺序是 `--translation-model`、`TRANSLATION_MODEL` 环境变量、代码默认值。普通网页翻译也遵循此设置。

不需要翻译时使用 `--translation-choice original`。当 API 返回 `finish_reason=length`，程序会报翻译截断错误；当前不会自动对失败块再次切分重试。

### 2. 微信抓取依赖

微信抓取需要 Python Playwright 和它的 Chromium 浏览器。建议在虚拟环境中安装，并用同一个 Python 运行抓取：

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install playwright
python3 -m playwright install chromium
```

以上激活命令适用于 macOS/Linux；Windows 使用 `.venv\Scripts\activate`。

如果运行环境已在其他目录安装 Playwright，可设置 `PLAYWRIGHT_PYTHONPATH`，指向包含 `playwright` 包的目录（通常为 `site-packages`）。该变量只补充 Python 包搜索路径，不会安装包或浏览器。

## 新手排错

### 1. 运行后提示找不到输出目录

如果你选择的是 `Obsidian Inbox` 或 `自定义目录`，先检查你输入的路径是否真实存在。

如果你不确定，重新选 `下载目录` 一般最稳。

### 2. 网页能打开，但抓取失败

常见原因有：

- 页面其实需要登录
- 网站有反爬
- 本地浏览器没有装好
- 缺少 `bun` / `npx`

建议先换成 `https://example.com` 做测试，确认程序本身可以跑通。

### 3. 翻译失败

先不要开翻译，直接保存原文：

```bash
python3 scripts/run_public_capture.py \
  --translation-choice original \
  "https://example.com/article"
```

### 4. 只有某一种来源失败

先用 dry-run 看路由是否正确：

```bash
python3 scripts/run_public_capture.py --dry-run "<URL>"
```

## 最近更新（2026-09-13）

- 普通网页翻译使用用户配置的模型。
- API 翻译被长度上限截断时明确报错。
- 微信和网页标题中的弯引号转为「」和『』。
- 飞书执行器使用 `.cjs` 入口，兼容 ESM 项目环境。
- 微信提取脚本支持 `PLAYWRIGHT_PYTHONPATH`。

验证包括现有集成检查、smoke 检查及上述改动的专项验证；未覆盖各平台在线抓取实测。

## 当前状态

已支持首次配置向导、Obsidian / 下载目录 / 自定义目录，以及 `.md` / `.txt` 输出。后续可补充图文安装教程和环境检查工具。
