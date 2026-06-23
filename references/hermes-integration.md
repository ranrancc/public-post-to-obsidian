# Hermes 环境集成说明

> 本 skill 原始开发于 OpenClaw workspace，后复制到 Hermes 技能库。本文档记录迁移过程中的陷阱与解决方案。

## 技能目录双轨制

现状：

- OpenClaw 技能存放于 `~/.openclaw/workspace/skills/`（workspace 级）和 `~/.openclaw/skills/` （global 级）
- Hermes 只扫描 `~/.hermes/skills/`
- `skill_view()` / `skills_list()` 调用不会自动去 OpenClaw 目录查找

影响：

- `public-post-to-obsidian` 在 OpenClaw workspace 里日常运行良好，但 Hermes 查询时返回 "Skill not found"
- 导致代理错误地认为该技能不存在，转向其他抓取方案

解决：

1. 复制整个技能目录到 Hermes：`cp -r ~/.openclaw/workspace/skills/public-post-to-obsidian ~/.hermes/skills/`
2. 确认 `SKILL.md` 在 `~/.hermes/skills/public-post-to-obsidian/SKILL.md`
3. 此后 `skill_view('public-post-to-obsidian')` 正常返回

## 环境变量隔离

现状：

- `X_BEARER_TOKEN` 存放于 `~/.openclaw/workspace/.env`
- OpenClaw 启动时会自动加载该 `.env`
- Hermes 启动时**不会**自动加载 OpenClaw 的 `.env`
- 直接运行 `x_api_executor.py` 时，`os.environ.get('X_BEARER_TOKEN')` 返回 None

影响：

- X 抓取自动降级到 `x_opencli_executor.py`（需要 Chrome 扩展）
- 若 opencli 未运行，报错 `BROWSER_CONNECT`

当前解决方案（可移植）：

1. **显式指定配置文件（跨 Agent 推荐）**
   ```bash
   export PUBLIC_POST_ENV_FILE="$HOME/.config/public-post-to-obsidian/.env"
   python3 scripts/run_public_capture.py "<URL>"
   ```

2. **使用 Agent 自己的环境文件**
   Hermes 使用 `~/.hermes/.env`，OpenClaw 可使用 `~/.openclaw/workspace/.env`。技能会自动检查这些位置，进程中已有的变量始终优先。

3. **技能目录旁配置**
   从 `.env.example` 复制为技能根目录 `.env`；该文件已加入 `.gitignore`，适合独立 checkout。不要把真实 token 提交到 GitHub。

## 路径自适应

好消息：

- `scripts/*.py` 已使用 `Path(__file__).resolve().parent` 自推导，复制到任何位置都能自动找到 `vendor/` 和 `references/`

清理工作（已完成）：

| 文件 | 原硬编码 | 改后 |
|------|----------|--------|
| `SKILL.md` | `python3 /Users/.../.openclaw/.../run_public_capture.py` | `python3 scripts/run_public_capture.py` + 根目录提示 |
| `references/feishu.md` | 同上 | `python3 scripts/...` + 根目录提示 |
| `references/tencent-meeting.md` | 同上 | `python3 scripts/...` + 根目录提示 |
| `README-share.md` | `/Users/.../.openclaw/.../vendor/baoyu-url-to-markdown` | `vendor/baoyu-url-to-markdown` 相对路径 |
| `GITHUB_PUBLISH_CHECKLIST.md` | 列出待清理的绝对路径 | 更新为"已完成"状态 |

验证：
```bash
# 确认无残留硬编码
grep -r "openclaw/workspace/skills/public-post-to-obsidian\|zhangyiran" ~/.hermes/skills/public-post-to-obsidian/ 2>/dev/null || echo "已清理完毕"
```

## 批量同步策略（OpenClaw → Hermes）

当需要把大量 OpenClaw 技能同步到 Hermes 时，区分两类技能采用不同策略：

| 类型 | 存放位置 | 策略 | 原因 |
|------|----------|------|------|
| **Workspace 技能** | `~/.openclaw/workspace/skills/` | **物理复制** | 内部文档含大量硬编码绝对路径，软链接无法修改这些路径 |
| **Global 技能** | `~/.openclaw/skills/` | **软链接** | 脚本本身用 `Path(__file__)` 自适应，无需改动；通过 `openclaw-imports/` 统一管理 |

**一次性批量软链接脚本示例：**
```python
from pathlib import Path
import subprocess

hermes_skills = Path.home() / ".hermes" / "skills"
openclaw_global = Path.home() / ".openclaw" / "skills"
openclaw_workspace = Path.home() / ".openclaw" / "workspace" / "skills"
imports_dir = hermes_skills / "openclaw-imports"
imports_dir.mkdir(exist_ok=True)

# Global skills → 软链接
for skill_dir in openclaw_global.iterdir():
    if skill_dir.is_dir():
        link = imports_dir / skill_dir.name
        if not link.exists():
            link.symlink_to(skill_dir)

# Workspace skills（排除已单独复制的）
for skill_dir in openclaw_workspace.iterdir():
    if skill_dir.is_dir() and skill_dir.name != "public-post-to-obsidian":
        link = imports_dir / skill_dir.name
        if not link.exists():
            link.symlink_to(skill_dir)
```

**命名空间规则：**
- 需要独立修改的 workspace 技能 → 直接放 `~/.hermes/skills/<name>/`
- 只读引用的 global 技能 → 软链接到 `~/.hermes/skills/openclaw-imports/<name>/`
- 两者在 `skill_view()` 和 `skills_list()` 中都会被扫描到

## 编辑记忆文件规范

在集成过程中，常需要更新 `~/.hermes/memories/MEMORY.md` 或 `~/.hermes/SOUL.md`。

**用户偏好（硬性约束）：**
> 只修改被**明确请求**的条目，不动其他已有内容。

**正例：**
```bash
# 用户说："只需要把 link to obsidian 改成全名吧！"
# 正确做法：只替换该技能名称，保留整行结构和前后所有其他规则不变
```

**反例（用户纠正）：**
```bash
# 错误：重写整个 MEMORY.md 段落，"优化"了格式和措辞
# 结果：用户反馈 "memory 别乱改"
```

**执行原则：**
1. 收到修改请求时，先用 `read_file` 定位精确行号
2. 用 `patch` 做单点替换，而不是重写整个文件
3. 替换后 `read_file` 验证：只动了被要求的那一行/那一处
4. 如果担心影响上下文，向用户确认"是否只改 X，不动 Y"后再执行

## 已落地的健壮性改进（2026-06-23）

1. 环境文件采用显式配置 + Agent 根目录 + 通用配置目录的候选链。
2. X 采用 API → FxTwitter → OpenCLI → Jina 的真实执行回退，而不只是在文档里声称回退。
3. 每个失败步骤记录在 `fallback_chain`；错误 JSON 使用非零退出码。
4. 401/403 不重试，429/5xx/网络错误有限重试。
5. 笔记和资源目录使用临时路径完成后原子替换，降低中断导致旧文件损坏的风险。

仍建议把 GitHub 仓库作为唯一源码，再通过安装/同步脚本分发到 Hermes、OpenClaw 和其他 Agent，避免多份物理复制长期漂移。
