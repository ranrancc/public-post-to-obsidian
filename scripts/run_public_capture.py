#!/usr/bin/env python3
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

from common import load_workspace_env
from router import detect_source

SCRIPT_DIR = Path(__file__).resolve().parent


def is_x_status_url(url: str) -> bool:
    u = url.lower()
    return any(x in u for x in ['/status/', '/article/'])


def has_x_api_token() -> bool:
    return bool((os.environ.get('X_BEARER_TOKEN') or os.environ.get('TWITTER_BEARER_TOKEN') or '').strip())


def supports_fxtwitter(url: str) -> bool:
    parts = [part for part in urlparse(url).path.split('/') if part]
    return len(parts) >= 3 and parts[1].lower() == 'status' and bool(parts[0] and parts[2])


def x_commands(args) -> list[list[str]]:
    translation_choice = 'both' if args.translation_choice == 'ask' else args.translation_choice
    suffix = [args.url, '--translation-choice', translation_choice]
    commands: list[list[str]] = []
    if is_x_status_url(args.url) and has_x_api_token():
        commands.append([sys.executable, str(SCRIPT_DIR / 'x_api_executor.py'), *suffix])
    if supports_fxtwitter(args.url):
        commands.append([sys.executable, str(SCRIPT_DIR / 'x_fxtwitter_executor.py'), *suffix])
    if is_x_status_url(args.url):
        commands.append([sys.executable, str(SCRIPT_DIR / 'x_opencli_executor.py'), *suffix])
    commands.append([sys.executable, str(SCRIPT_DIR / 'x_executor.py'), *suffix])
    return commands


def build_commands(args, source: str) -> list[list[str]]:
    if source == 'x':
        return x_commands(args)
    if source == 'wechat':
        return [[sys.executable, str(SCRIPT_DIR / 'wechat_executor.py'), args.url]]
    if source == 'tencent_meeting':
        cmd = [
            sys.executable,
            str(SCRIPT_DIR / 'tencent_meeting_executor.py'),
            args.url,
        ]
        if args.tencent_meeting_download_video:
            cmd.append('--download-video')
        return [cmd]
    if source == 'web':
        return [[
            sys.executable,
            str(SCRIPT_DIR / 'generic_web_executor.py'),
            '--llm-title',
            args.llm_title,
            '--web-backend',
            args.web_backend,
            '--translation-choice',
            args.translation_choice,
            args.url,
        ]]
    if source == 'feishu':
        cmd = [
            sys.executable,
            str(SCRIPT_DIR / 'feishu_executor.py'),
            '--url',
            args.url,
        ]
        if args.page_id:
            cmd.extend(['--page-id', args.page_id])
        if args.space_id:
            cmd.extend(['--space-id', args.space_id])
        if args.container_id:
            cmd.extend(['--container-id', args.container_id])
        if args.title:
            cmd.extend(['--title', args.title])
        if args.cookie_header:
            cmd.extend(['--cookie-header', args.cookie_header])
        if args.date:
            cmd.extend(['--date', args.date])
        if args.write_meta:
            cmd.append('--write-meta')
        return [cmd]
    raise ValueError(f'unsupported URL for public-post-to-obsidian: {args.url}')


def build_command(args, source: str) -> list[str]:
    """Backward-compatible helper for callers that expect one command."""
    return build_commands(args, source)[0]


def parse_result(stdout: str) -> dict | None:
    text = stdout.strip()
    if not text:
        return None
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else None
    except json.JSONDecodeError:
        start = text.find('{')
        end = text.rfind('}')
        if start < 0 or end <= start:
            return None
        try:
            value = json.loads(text[start:end + 1])
            return value if isinstance(value, dict) else None
        except json.JSONDecodeError:
            return None


def run_fallback_chain(commands: list[list[str]], env: dict[str, str]) -> tuple[dict, int]:
    attempts: list[dict] = []
    last_result: dict | None = None
    for command in commands:
        cp = subprocess.run(command, capture_output=True, text=True, env=env)
        result = parse_result(cp.stdout)
        handler = Path(command[1]).stem if len(command) > 1 else command[0]
        if result is None:
            result = {
                'source_type': 'x',
                'handler_used': handler,
                'status': 'error',
                'error': (cp.stderr or cp.stdout or 'executor returned no JSON result').strip()[:2000],
            }
        status = result.get('status')
        attempts.append({
            'handler': result.get('handler_used') or handler,
            'status': status or 'error',
            'returncode': cp.returncode,
            'error': (result.get('error') or '').strip()[:1000] or None,
        })
        last_result = result
        if cp.returncode == 0 and status not in {'error', 'auth_required'}:
            result['fallback_chain'] = attempts
            return result, 0
    final = last_result or {'source_type': 'x', 'status': 'error', 'error': 'no X executor was available'}
    final['status'] = 'error'
    final['fallback_chain'] = attempts
    if not final.get('error'):
        final['error'] = 'all X capture executors failed'
    return final, 1


def main():
    load_workspace_env()  # Must load before any env-dependent checks
    parser = argparse.ArgumentParser(
        description='Unified entrypoint for public-post-to-obsidian executors.'
    )
    parser.add_argument('url')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--llm-title', choices=['auto', 'on', 'off'], default='auto')
    parser.add_argument('--translation-choice', choices=['ask', 'translate', 'original', 'both'], default='ask')
    parser.add_argument('--translation-model', help='Translation model in provider:model format (default: TRANSLATION_MODEL env or deepseek:deepseek-v4-flash)')
    parser.add_argument('--web-backend', choices=['auto', 'baoyu', 'legacy'], default='auto')
    parser.add_argument('--page-id')
    parser.add_argument('--space-id')
    parser.add_argument('--container-id')
    parser.add_argument('--title')
    parser.add_argument('--cookie-header')
    parser.add_argument('--date')
    parser.add_argument('--write-meta', action='store_true')
    parser.add_argument('--tencent-meeting-download-video', action='store_true')
    args = parser.parse_args()

    try:
        source = detect_source(args.url)
        commands = build_commands(args, source)
    except ValueError as exc:
        print(json.dumps({'status': 'error', 'error': str(exc)}, ensure_ascii=False, indent=2))
        sys.exit(1)

    if args.dry_run:
        print(
            json.dumps(
                {
                    'status': 'ready',
                    'source_type': source,
                    'command': commands[0],
                    'commands': commands,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    env = os.environ.copy()
    if args.translation_model:
        env['TRANSLATION_MODEL'] = args.translation_model

    if source == 'x':
        result, exit_code = run_fallback_chain(commands, env)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(exit_code)

    cmd = commands[0]
    cp = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if cp.stdout:
        print(cp.stdout.strip())
    if cp.returncode != 0:
        if cp.stderr:
            print(cp.stderr.strip(), file=sys.stderr)
        sys.exit(cp.returncode)


if __name__ == '__main__':
    main()
