#!/usr/bin/env python3
from __future__ import annotations
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

SKILL_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = SKILL_ROOT / '.public-post-to-obsidian.json'
LEGACY_CONFIG_PATH = Path.home() / '.public-post-to-obsidian.json'
APP_FOLDER_NAME = 'Public Post To Obsidian'
DEFAULT_STORAGE_MODE = 'downloads'
DEFAULT_FILE_FORMAT = 'md'
DEFAULT_OBSIDIAN_INBOX = Path.home() / 'Library' / 'Mobile Documents' / 'iCloud~md~obsidian' / 'Documents' / 'ZYR' / '00-Inbox'
DEFAULT_LECTURE_ARCHIVE_ROOT = Path.home() / 'Library' / 'CloudStorage' / 'OneDrive-个人' / '讲座录制'

SOURCE_SUBDIRS = {
    'x': 'X',
    'wechat': '微信剪藏',
    'feishu': '飞书',
    'web': '网页剪藏',
    'tencent_meeting': '腾讯会议回放',
}

SOURCE_TAGS = {
    'x': ['inbox', 'capture', 'x'],
    'wechat': ['inbox', 'capture', 'wechat'],
    'feishu': ['inbox', 'capture', 'feishu'],
    'web': ['inbox', 'capture', 'web'],
    'tencent_meeting': ['inbox', 'capture', 'tencent-meeting'],
}


def default_downloads_root() -> Path:
    return Path.home() / 'Downloads'


def default_downloads_app_root() -> Path:
    return default_downloads_root() / APP_FOLDER_NAME


def build_target_dirs(base_root: str | Path) -> dict[str, str]:
    root = Path(base_root).expanduser()
    target_dirs = {
        source_type: str(root / subdir)
        for source_type, subdir in SOURCE_SUBDIRS.items()
    }
    target_dirs['tencent_meeting'] = str(DEFAULT_LECTURE_ARCHIVE_ROOT)
    return target_dirs


TARGET_DIRS = build_target_dirs(default_downloads_app_root())


def load_workspace_env() -> None:
    env_path = Path(__file__).resolve().parents[3] / '.env'
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding='utf-8').splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        key = key.strip()
        value = value.strip()
        if not key or key in os.environ:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        os.environ[key] = value


def load_user_config() -> dict:
    config_path = CONFIG_PATH if CONFIG_PATH.exists() else LEGACY_CONFIG_PATH
    if not config_path.exists():
        return {}
    try:
        payload = json.loads(config_path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def save_user_config(config: dict) -> None:
    CONFIG_PATH.write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8',
    )


def is_interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def prompt_choice(prompt: str, options: dict[str, str], default: str) -> str:
    while True:
        answer = input(prompt).strip().lower()
        if not answer:
            return default
        if answer in options:
            return options[answer]
        print(f'请输入 {"/".join(options)}，或直接回车使用默认值。')


def prompt_path(prompt: str, default: Path | None = None) -> str:
    suffix = f' [{default}]' if default else ''
    while True:
        raw = input(f'{prompt}{suffix}: ').strip()
        chosen = Path(raw).expanduser() if raw else default
        if chosen is None:
            print('这个路径不能为空。')
            continue
        return str(chosen)


def onboarding_config() -> dict:
    default_downloads = default_downloads_app_root()
    print('首次使用 Public Post To Obsidian，需要先设置默认保存位置。')
    storage_mode = prompt_choice(
        '请选择保存位置：1=Obsidian Inbox，2=下载目录，3=自定义目录 [默认 2]: ',
        {'1': 'obsidian', '2': 'downloads', '3': 'custom'},
        DEFAULT_STORAGE_MODE,
    )
    config = {
        'storage_mode': storage_mode,
        'file_format': DEFAULT_FILE_FORMAT,
    }
    if storage_mode == 'obsidian':
        inbox_path = prompt_path('请输入你的 Obsidian Inbox 路径')
        config['obsidian_inbox'] = inbox_path
    elif storage_mode == 'custom':
        custom_root = prompt_path('请输入默认保存目录')
        config['custom_root'] = custom_root
    else:
        config['downloads_root'] = str(default_downloads)

    file_format = prompt_choice(
        '请选择默认文件格式：1=.md，2=.txt [默认 1]: ',
        {'1': 'md', '2': 'txt'},
        DEFAULT_FILE_FORMAT,
    )
    config['file_format'] = file_format
    return config


def ensure_user_config(interactive: bool = True) -> dict:
    config = load_user_config()
    if config:
        return config
    if DEFAULT_OBSIDIAN_INBOX.exists():
        return {
            'storage_mode': 'obsidian',
            'obsidian_inbox': str(DEFAULT_OBSIDIAN_INBOX),
            'file_format': DEFAULT_FILE_FORMAT,
        }
    if interactive and is_interactive():
        config = onboarding_config()
        save_user_config(config)
        return config
    return {
        'storage_mode': DEFAULT_STORAGE_MODE,
        'downloads_root': str(default_downloads_app_root()),
        'file_format': DEFAULT_FILE_FORMAT,
    }


def base_root_from_config(config: dict) -> Path:
    mode = (config.get('storage_mode') or DEFAULT_STORAGE_MODE).strip().lower()
    if mode == 'obsidian':
        inbox = (config.get('obsidian_inbox') or '').strip()
        if inbox:
            return Path(inbox).expanduser()
        return default_downloads_app_root()
    if mode == 'custom':
        custom_root = (config.get('custom_root') or '').strip()
        if custom_root:
            return Path(custom_root).expanduser()
        return default_downloads_app_root()
    downloads_root = (config.get('downloads_root') or '').strip()
    if downloads_root:
        return Path(downloads_root).expanduser()
    return default_downloads_app_root()


def target_dir_for_source(source_type: str, *, interactive: bool = True) -> str:
    config = ensure_user_config(interactive=interactive)
    base_root = base_root_from_config(config)
    return build_target_dirs(base_root).get(source_type, str(base_root))


def output_settings_for_source(source_type: str, *, interactive: bool = True) -> dict:
    config = ensure_user_config(interactive=interactive)
    target_dir = target_dir_for_source(source_type, interactive=interactive)
    file_format = (config.get('file_format') or DEFAULT_FILE_FORMAT).strip().lower()
    if file_format not in {'md', 'txt'}:
        file_format = DEFAULT_FILE_FORMAT
    storage_mode = (config.get('storage_mode') or DEFAULT_STORAGE_MODE).strip().lower()
    return {
        'target_dir': target_dir,
        'file_format': file_format,
        'storage_mode': storage_mode,
        'include_frontmatter': file_format == 'md' and storage_mode == 'obsidian',
    }


def note_path_for(target_dir: str, basename: str, file_format: str) -> str:
    ext = '.txt' if file_format == 'txt' else '.md'
    return str(Path(target_dir) / f'{basename}{ext}')


def count_assets(asset_dir: str | None) -> int:
    if not asset_dir or not os.path.isdir(asset_dir):
        return 0
    count = 0
    for _, _, files in os.walk(asset_dir):
        count += len(files)
    return count


def validate_result(result: dict) -> dict:
    note_path = result.get('note_path')
    asset_dir = result.get('asset_dir')
    if note_path and not os.path.exists(note_path):
        result['status'] = 'error'
        result['error'] = f'note_path not found: {note_path}'
    result['asset_count'] = count_assets(asset_dir)
    return result


def build_result(source_type: str, handler_used: str | None, target_dir: str | None, status='ready', **extra) -> dict:
    result = {
        'source_type': source_type,
        'handler_used': handler_used,
        'target_dir': target_dir,
        'status': status,
        'note_path': None,
        'asset_dir': None,
        'asset_count': 0,
        'error': None,
    }
    result.update(extra)
    return validate_result(result)


def yaml_quote(value: str) -> str:
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'


def compact_value(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        text = value.strip()
        return text or None
    return value


def obsidian_frontmatter(
    *,
    title: str,
    source_url: str,
    source_type: str,
    created: str | None = None,
    fetched_at: str | None = None,
    tags: list[str] | None = None,
    extra: dict[str, str | list[str] | None] | None = None,
) -> str:
    created_value = created or datetime.now().strftime('%Y-%m-%d')
    fetched_value = fetched_at or datetime.now().isoformat(timespec='seconds')
    host = urlparse(source_url).netloc.lower()
    lines = [
        '---',
        f'title: {yaml_quote(title)}',
        f'source: {yaml_quote(source_url)}',
        f'created: {created_value}',
        f'fetched_at: {yaml_quote(fetched_value)}',
        f'source_type: {yaml_quote(source_type)}',
        f'source_domain: {yaml_quote(host)}',
        'tags:',
    ]
    for tag in (tags or SOURCE_TAGS.get(source_type, ['inbox', 'capture'])):
        lines.append(f'  - {tag}')
    for key, value in (extra or {}).items():
        value = compact_value(value)
        if value is None:
            continue
        if isinstance(value, list):
            lines.append(f'{key}:')
            for item in value:
                lines.append(f'  - {item}')
        elif isinstance(value, bool):
            lines.append(f'{key}: {"true" if value else "false"}')
        elif isinstance(value, (int, float)):
            lines.append(f'{key}: {value}')
        else:
            lines.append(f'{key}: {yaml_quote(str(value))}')
    lines.extend(['---', ''])
    return '\n'.join(lines)


def markdown_to_text(markdown: str) -> str:
    text = markdown
    text = re.sub(r'^---\n.*?\n---\n', '', text, flags=re.S)
    text = re.sub(r'!\[\[([^\]]+)\]\]', r'[图片: \1]', text)
    text = re.sub(r'!\[([^\]]*)\]\(([^)]+)\)', r'[图片: \1 \2]', text)
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'\1 (\2)', text)
    text = re.sub(r'^\s{0,3}#{1,6}\s*', '', text, flags=re.M)
    text = re.sub(r'^\s*[-*+]\s+', '- ', text, flags=re.M)
    text = re.sub(r'`([^`]+)`', r'\1', text)
    text = re.sub(r'[*_]{1,3}', '', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip() + '\n'


def render_note_content(
    *,
    title: str,
    source_url: str,
    source_type: str,
    base_markdown: str,
    extra: dict[str, str | list[str] | None] | None = None,
    include_frontmatter: bool = True,
    file_format: str = 'md',
) -> str:
    markdown = base_markdown.rstrip() + '\n'
    if include_frontmatter:
        markdown = (
            obsidian_frontmatter(
                title=title,
                source_url=source_url,
                source_type=source_type,
                extra=extra,
            )
            + markdown
        )
    if file_format == 'txt':
        return markdown_to_text(markdown)
    return markdown
