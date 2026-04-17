#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from common import (
    build_result,
    markdown_to_text,
    output_settings_for_source,
    target_dir_for_source,
    yaml_quote,
)

SCRIPT_DIR = Path(__file__).resolve().parent
FEISHU_EXPORTER = str(SCRIPT_DIR / 'grab_feishu_public_doc.js')
FEISHU_PROBER = str(SCRIPT_DIR / 'feishu_probe.py')

AUTHOR_LINE_RE = re.compile(r'^原创\s+.+\d{4}年\d{1,2}月\d{1,2}日')
PUBLISHED_AT_RE = re.compile(r'(\d{4}年\d{1,2}月\d{1,2}日(?:\s+\d{1,2}:\d{2})?)')
SOURCE_LINK_RE = re.compile(r'https?://[^\s)>\]]+')


def extract_author_line(markdown: str) -> str | None:
    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if AUTHOR_LINE_RE.search(line):
            return line
    return None


def extract_published_at(text: str | None) -> str | None:
    if not text:
        return None
    match = PUBLISHED_AT_RE.search(text)
    return match.group(1) if match else None


def extract_embedded_source_url(markdown: str) -> str | None:
    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if '原文链接' not in line:
            continue
        match = SOURCE_LINK_RE.search(line)
        if match:
            return match.group(0)
    return None


def enrich_feishu_note(
    note_path: str,
    *,
    title: str,
    source_url: str,
    fetched_at: str,
    page_id: str,
    space_id: str,
    container_id: str,
    asset_count: int,
    probe_data: dict | None = None,
    include_frontmatter: bool = True,
    file_format: str = 'md',
) -> dict:
    path = Path(note_path)
    markdown = path.read_text(encoding='utf-8')
    author_line = extract_author_line(markdown)
    embedded_source_url = extract_embedded_source_url(markdown)
    if probe_data and probe_data.get('embedded_source_url'):
        embedded_source_url = probe_data['embedded_source_url']
    if probe_data and probe_data.get('author_line') and not author_line:
        author_line = probe_data['author_line']
    metadata_extra = {
        'capture_method': 'feishu-client-vars',
        'page_id': page_id,
        'space_id': space_id,
        'container_id': container_id,
        'asset_count': asset_count,
        'embedded_source_url': embedded_source_url,
        'author_line': author_line,
        'published_at': extract_published_at(author_line),
        'source_created_at': (probe_data or {}).get('source_created_at'),
        'source_updated_at': (probe_data or {}).get('source_updated_at'),
    }
    if include_frontmatter and not markdown.startswith('---\n'):
        lines = [
            '---',
            f'title: {yaml_quote(title)}',
            f'source: {yaml_quote(source_url)}',
            f'created: {fetched_at[:10]}',
            f'fetched_at: {yaml_quote(fetched_at)}',
            'source_type: "feishu"',
            f'source_domain: {yaml_quote(urlparse(source_url).netloc.lower())}',
            'tags:',
        ]
        for tag in ['inbox', 'capture', 'feishu']:
            lines.append(f'  - {tag}')
        for key, value in metadata_extra.items():
            if value:
                lines.append(f'{key}: {yaml_quote(str(value))}')
        lines.extend(['---', ''])
        markdown = '\n'.join(lines) + markdown
    if file_format == 'txt':
        path = path.with_suffix('.txt')
        markdown = markdown_to_text(markdown)
    path.write_text(markdown, encoding='utf-8')
    return {
        'note_path': str(path),
        'embedded_source_url': embedded_source_url,
        'author_line': author_line,
        'published_at': extract_published_at(author_line),
    }


def probe_runtime_metadata(url: str) -> dict:
    cp = subprocess.run(
        [sys.executable, FEISHU_PROBER, url],
        capture_output=True,
        text=True,
    )
    if cp.returncode != 0:
        error = cp.stderr.strip() or cp.stdout.strip() or 'feishu probe failed'
        raise RuntimeError(error)
    return json.loads(cp.stdout)


def main():
    parser = argparse.ArgumentParser(description='Wrapper around the stable Feishu public exporter.')
    parser.add_argument('--url', required=True)
    parser.add_argument('--page-id')
    parser.add_argument('--space-id')
    parser.add_argument('--container-id')
    parser.add_argument('--title')
    parser.add_argument('--cookie-header')
    parser.add_argument('--dest-dir', default=target_dir_for_source('feishu', interactive=False))
    parser.add_argument('--date', default=datetime.now().strftime('%Y%m%d'))
    parser.add_argument('--write-meta', action='store_true')
    args = parser.parse_args()
    output = output_settings_for_source('feishu')
    args.dest_dir = output['target_dir']

    page_id = args.page_id
    space_id = args.space_id
    container_id = args.container_id
    title = args.title
    cookie_header = args.cookie_header
    probe_data = {}
    if not all([page_id, space_id, container_id, title, cookie_header]):
        probe_data = probe_runtime_metadata(args.url)
        page_id = page_id or probe_data.get('page_id')
        space_id = space_id or probe_data.get('space_id')
        container_id = container_id or probe_data.get('container_id')
        title = title or probe_data.get('title')
        cookie_header = cookie_header or probe_data.get('cookie_header')

    if not all([page_id, space_id, container_id, title, cookie_header]):
        missing = [
            name
            for name, value in [
                ('page_id', page_id),
                ('space_id', space_id),
                ('container_id', container_id),
                ('title', title),
                ('cookie_header', cookie_header),
            ]
            if not value
        ]
        raise RuntimeError(f'feishu runtime metadata incomplete: {", ".join(missing)}')

    cmd = [
        'node',
        FEISHU_EXPORTER,
        '--url', args.url,
        '--page-id', page_id,
        '--space-id', space_id,
        '--container-id', container_id,
        '--title', title,
        '--dest-dir', args.dest_dir,
        '--cookie-header', cookie_header,
        '--date', args.date,
    ]
    display_source_url = probe_data.get('embedded_source_url') or args.url
    if display_source_url:
        cmd.extend(['--display-source-url', display_source_url])
    if args.write_meta:
        cmd.append('--write-meta')

    cp = subprocess.run(cmd, capture_output=True, text=True)
    if cp.returncode != 0:
        error = cp.stderr.strip() or cp.stdout.strip() or 'feishu exporter failed'
        result = build_result(
            'feishu',
            'public-post-feishu',
            args.dest_dir,
            status='error',
            error=error,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(1)

    payload = json.loads(cp.stdout)
    fetched_at = datetime.now().isoformat(timespec='seconds')
    metadata = enrich_feishu_note(
        payload['note_path'],
        title=title,
        source_url=args.url,
        fetched_at=fetched_at,
        page_id=page_id,
        space_id=space_id,
        container_id=container_id,
        asset_count=payload.get('asset_count', 0),
        probe_data=probe_data,
        include_frontmatter=output['include_frontmatter'],
        file_format=output['file_format'],
    )
    result = build_result(
        'feishu',
        'public-post-feishu',
        args.dest_dir,
        note_path=metadata.get('note_path') or payload.get('note_path'),
        asset_dir=payload.get('asset_dir'),
        meta_path=payload.get('meta_path'),
        title=title,
        page_id=page_id,
        space_id=space_id,
        container_id=container_id,
        probe_used=bool(probe_data),
        file_format=output['file_format'],
        storage_mode=output['storage_mode'],
        **metadata,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
