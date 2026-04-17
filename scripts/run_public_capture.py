#!/usr/bin/env python3
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from common import load_workspace_env
from router import detect_source

SCRIPT_DIR = Path(__file__).resolve().parent


def is_x_article_url(url: str) -> bool:
    u = url.lower()
    return any(x in u for x in ['/status/', '/article/'])


def has_x_api_token() -> bool:
    return bool((os.environ.get('X_BEARER_TOKEN') or os.environ.get('TWITTER_BEARER_TOKEN') or '').strip())


def build_command(args, source: str) -> list[str]:
    if source == 'x':
        if is_x_article_url(args.url) and has_x_api_token():
            executor = 'x_api_executor.py'
        elif is_x_article_url(args.url):
            executor = 'x_opencli_executor.py'
        else:
            executor = 'x_executor.py'
        return [
            sys.executable,
            str(SCRIPT_DIR / executor),
            args.url,
            '--translation-choice',
            'both',
        ]
    if source == 'wechat':
        return [sys.executable, str(SCRIPT_DIR / 'wechat_executor.py'), args.url]
    if source == 'tencent_meeting':
        cmd = [
            sys.executable,
            str(SCRIPT_DIR / 'tencent_meeting_executor.py'),
            args.url,
        ]
        if args.tencent_meeting_download_video:
            cmd.append('--download-video')
        return cmd
    if source == 'web':
        return [
            sys.executable,
            str(SCRIPT_DIR / 'generic_web_executor.py'),
            '--llm-title',
            args.llm_title,
            '--web-backend',
            args.web_backend,
            '--translation-choice',
            args.translation_choice,
            args.url,
        ]
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
        return cmd
    raise ValueError(f'unsupported URL for public-post-to-obsidian: {args.url}')


def main():
    load_workspace_env()
    parser = argparse.ArgumentParser(
        description='Unified entrypoint for public-post-to-obsidian executors.'
    )
    parser.add_argument('url')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--llm-title', choices=['auto', 'on', 'off'], default='auto')
    parser.add_argument('--translation-choice', choices=['ask', 'translate', 'original', 'both'], default='ask')
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
        cmd = build_command(args, source)
    except ValueError as exc:
        print(json.dumps({'status': 'error', 'error': str(exc)}, ensure_ascii=False, indent=2))
        sys.exit(1)

    if args.dry_run:
        print(
            json.dumps(
                {
                    'status': 'ready',
                    'source_type': source,
                    'command': cmd,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    cp = subprocess.run(cmd, capture_output=True, text=True)
    if cp.stdout:
        print(cp.stdout.strip())
    if cp.returncode != 0:
        if cp.stderr:
            print(cp.stderr.strip(), file=sys.stderr)
        sys.exit(cp.returncode)


if __name__ == '__main__':
    main()
