# Public Post To Obsidian

Self-contained public URL capture skill for Obsidian inboxes.

This skill captures:

- X / Twitter public posts
- WeChat public articles
- Feishu / Lark public wiki/docx pages
- Generic public webpages

For generic webpages, this skill now vendors its own copy of `baoyu-url-to-markdown` under:

- [vendor/baoyu-url-to-markdown](vendor/baoyu-url-to-markdown)

That means the skill no longer depends on an external `baoyu-url-to-markdown` skill directory to run.

## Runtime Requirements

Required:

- `python3`
- `bun` or `npx`
- Chrome / Chromium / Edge installed locally

Optional but recommended:

- `defuddle`
- `OPENAI_API_KEY` for title cleanup fallback
- `kimi` for translation flow in non-Chinese captures

## Portable Environment Configuration

Never commit a real `.env`. Copy `.env.example` to a private location and either export variables normally or point the skill at that file:

```bash
export PUBLIC_POST_ENV_FILE="$HOME/.config/public-post-to-obsidian/.env"
python3 scripts/run_public_capture.py 'https://x.com/user/status/123'
```

Without an explicit path, the loader checks the current Agent root, the skill root, the shared config directory, and common Hermes/OpenClaw/Codex locations. Existing process variables have highest priority.

For reproducible Agent or CI installs, output and user configuration can also be detached from the checkout:

```bash
export PUBLIC_POST_OUTPUT_ROOT="$HOME/Downloads/Public Post To Obsidian"
export PUBLIC_POST_CONFIG_FILE="$HOME/.config/public-post-to-obsidian/config.json"
```

For X URLs, the portable fallback order is:

1. official X API when a token is available
2. FxTwitter public API for `/<username>/status/<id>` URLs
3. OpenCLI with a logged-in browser bridge
4. Jina Reader

The final JSON includes `fallback_chain`, making missing credentials and unavailable optional dependencies diagnosable without exposing secrets.

## What Is Vendored

This skill includes a vendored copy of:

- `baoyu-url-to-markdown`
- its local `vendor/baoyu-chrome-cdp`
- its installed `node_modules`

Vendored source reference:

- upstream skill: `baoyu-url-to-markdown`
- version observed during vendoring: `1.58.1`
- upstream homepage: [JimLiu/baoyu-skills](https://github.com/JimLiu/baoyu-skills#baoyu-url-to-markdown)

## Entry Point

Unified entrypoint:

```bash
python3 scripts/run_public_capture.py '<url>'
```

Generic webpage capture with explicit backend:

```bash
python3 scripts/run_public_capture.py \
  --web-backend auto \
  --translation-choice original \
  'https://example.com'
```

## Smoke Test

Dry-run routing:

```bash
python3 scripts/run_public_capture.py --dry-run https://example.com
```

Real generic webpage smoke test:

```bash
python3 scripts/run_public_capture.py \
  --web-backend auto \
  --translation-choice original \
  'https://example.com'
```

Python syntax check:

```bash
python3 -m py_compile scripts/baoyu_web_capture.py scripts/generic_web_executor.py scripts/run_public_capture.py
```

## Packaging Notes

If you share this skill folder with others, keep these paths together:

- `SKILL.md`
- `README-share.md`
- `scripts/`
- `agents/`
- `vendor/baoyu-url-to-markdown/`
- `.env.example`

Do not remove the vendored `node_modules` unless you also want recipients to run dependency installation themselves.

## Current Generic-Web Behavior

For `source_type=web`, the execution order is:

1. vendored `baoyu-url-to-markdown` browser capture
2. local `defuddle --json --md`
3. `r.jina.ai` fallback

The final note writing policy still belongs to this skill:

- output directory
- Obsidian frontmatter
- filename format
- local asset download path
- translation branching
- result JSON contract

## Known Tradeoff

This self-contained version is easier to share, but larger in size because the vendored JS runtime dependencies are included.
