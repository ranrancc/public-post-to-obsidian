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
git clone <YOUR-REPO-URL>
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

### 第 3 步：配置输出目录

小白打包版不建议让用户手改环境变量。

更适合的做法是：

- 程序第一次运行时，弹出提示
- 先询问是否使用 Obsidian
- 如果使用，再让用户输入 Obsidian 仓库路径
- 如果不使用，默认保存到本地下载目录里的专用文件夹
- 再自动保存配置

也就是说，GitHub 公开版最好提供“首次运行向导”，而不是要求用户自己编辑 `.env`。

在你真正发布前，可以先把默认体验设计成下面这样：

1. 第一次运行时询问“你是否使用 Obsidian？”
2. 如果使用，再询问“你的 Obsidian 仓库在哪？”
3. 如果不使用，默认保存到 `下载/Public Post To Obsidian/`
4. 如果用户要抓腾讯会议，再询问“会议回放保存到哪里？”
5. 再询问默认文件格式：`.md` 或 `.txt`
6. 以后默认记住，不再重复问

这一版 README 先按这个目标来写，但当前代码还需要再补一层配置向导才能完全做到。

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

## 可选功能

## 对小白更友好的默认保存方式

推荐把公开版的默认行为设计成这样：

- 如果检测到 Obsidian，就优先保存为 `.md`
- 如果没有配置 Obsidian，就默认保存到 `下载/Public Post To Obsidian/`
- 给用户一个简单选项：`保存为 Markdown` 或 `保存为 TXT`

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

部分流程会尝试调用本地 `kimi` 命令做翻译。

如果你没有这个环境，也没关系：

- 可以先使用 `--translation-choice original`
- 先保证原文抓取成功

## 新手排错

### 1. 运行后提示找不到输出目录

先检查 `.env` 里路径是不是已经填写，而且是真实存在的目录。

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

## 给 GitHub 仓库维护者的建议

如果你准备把这个项目分享给更多非技术用户，建议仓库首页再补：

- macOS 安装说明
- Windows 安装说明
- Obsidian 路径如何查找
- 常见报错截图

## 当前状态

这是一个偏实用型项目，优先目标是“能帮人把公开内容沉淀进 Obsidian”。

如果你要做一个更适合大众用户的版本，推荐下一步继续补：

- 图文安装教程
- 一键环境检查脚本
- 首次配置向导
- 把 X 能力拆成进阶版，而不是默认版
- Obsidian / 非 Obsidian 双模式保存
- `.md` / `.txt` 格式切换
