#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

from common import (
    TARGET_DIRS,
    build_result,
    note_path_for,
    output_settings_for_source,
    render_note_content,
)

SCRIPT_DIR = Path(__file__).resolve().parent
EXTRACT_SCRIPT = SCRIPT_DIR / 'wechat_extract.py'
JSON_DIR = Path('/tmp/wechat_articles')
NOISE_SUBSTRINGS = (
    '已关注',
    '观看更多',
    '退出全屏',
    '分享视频',
    '分享点赞在看',
    '已同步到看一看',
    '您的浏览器不支持 video 标签',
    '[播放](javascript:;)',
    '[倍速](javascript:;)',
    '[视频详情](javascript:;)',
    '[0.5倍](javascript:;)',
    '[0.75倍](javascript:;)',
    '[1.0倍](javascript:;)',
    '[1.5倍](javascript:;)',
    '[2.0倍](javascript:;)',
    '[超清](javascript:;)',
    '[流畅](javascript:;)',
    '超清  流畅',
    '0.5倍',
    '0.75倍',
    '1.0倍',
    '1.5倍',
    '2.0倍',
    '切换到横屏模式',
    '进度条，百分之0',
    '倍速播放中',
    '时长',
    '写下你的评论',
)
NOISE_EXACT = {
    '**',
    '***',
    '****',
    '更多**',
    '关闭**',
    '关闭',
    '更多',
    '播放',
    '原创',
    '视频详情',
    '转载',
    ',',
    '0/0',
    '*全屏*',
    '全屏',
    '倍速',
    '继续播放',
    '继续观看',
    '分享',
    '赞',
    '重播',
    '关注',
}
TIME_LINE_RE = re.compile(r'^(?:\d{2}:\d{2}(?:/\d{2}:\d{2})?|/)$')
IMAGE_LINE_RE = re.compile(r'^(?:!\[img\]\(.+\)|!\[\[[^\]]+\]\])$')
LOCAL_MARKDOWN_IMAGE_RE = re.compile(r'!\[[^\]]*\]\((?:\./)?(?P<path>assets/[^)]+\.(?:png|jpe?g|gif|bmp|tiff|avif|webp|svg))\)', re.I)


def sanitize_title(text: str) -> str:
    text = re.sub(r'[\\/:*?"<>|]', '', text).strip()
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'[。.\s]+$', '', text)
    return (text[:80] or '未命名').strip()


def first_image_url(images: list[dict]) -> str | None:
    for image in images:
        src = (image.get('src') or '').strip()
        if src:
            return src
    return None


def infer_ext(url: str) -> str:
    if 'wx_fmt=png' in url or 'mmbiz_png' in url:
        return 'png'
    if 'wx_fmt=gif' in url or 'mmbiz_gif' in url:
        return 'gif'
    if 'wx_fmt=svg' in url or 'mmbiz_svg' in url:
        return 'svg'
    if 'wx_fmt=webp' in url or 'mmbiz_webp' in url:
        return 'webp'
    return 'jpg'


def download(url: str, path: Path) -> bool:
    try:
        req = urllib.request.Request(
            url,
            headers={
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
                'Referer': 'https://mp.weixin.qq.com/',
                'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            },
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = resp.read()
        path.write_bytes(data)
        return True
    except Exception as exc:
        print(f'wechat image download failed: {url} :: {type(exc).__name__}: {exc}', file=sys.stderr)
        return False


def load_json(json_path: Path) -> dict:
    if not json_path.exists():
        raise FileNotFoundError(f'wechat extract json not found: {json_path}')
    return json.loads(json_path.read_text(encoding='utf-8'))


def is_noise_line(line: str, title: str = '') -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if stripped in NOISE_EXACT:
        return True
    if TIME_LINE_RE.match(stripped):
        return True
    if any(token in stripped for token in NOISE_SUBSTRINGS):
        return True
    if stripped.startswith('*切换到竖屏全屏'):
        return True
    if '重播' in stripped and '分享' in stripped and '赞' in stripped:
        return True
    if title and stripped == title:
        return True
    return False


def clean_markdown(body: str, title: str = '') -> str:
    cleaned_lines: list[str] = []
    seen_images: set[str] = set()

    for raw_line in body.splitlines():
        stripped = raw_line.strip()
        if is_noise_line(raw_line, title=title):
            continue
        if stripped and not IMAGE_LINE_RE.match(stripped):
            stripped = re.sub(r'\[(.+?)\]\(javascript:;\)', r'\1', stripped)
        if IMAGE_LINE_RE.match(stripped):
            if stripped in seen_images:
                continue
            seen_images.add(stripped)
            cleaned_lines.append(stripped)
            cleaned_lines.append('')
            continue
        if stripped:
            cleaned_lines.append(stripped)
        elif cleaned_lines and cleaned_lines[-1] != '':
            cleaned_lines.append('')

    text = '\n'.join(cleaned_lines)
    text = re.sub(r'\n{3,}', '\n\n', text).strip()
    return text + '\n'


def convert_local_markdown_images_to_wikilinks(body: str) -> str:
    return LOCAL_MARKDOWN_IMAGE_RE.sub(lambda m: f'![[{m.group("path")}]]', body)


def localize_images(
    body: str,
    images: list[dict],
    note_basename: str,
    asset_dir: Path,
    *,
    title: str,
) -> tuple[str, int, int]:
    ok = 0
    fail = 0
    for index, image in enumerate(images, start=1):
        src = image.get('src') or ''
        if not src:
            continue
        ext = infer_ext(src)
        stamp = datetime.now().strftime('%Y%m%d%H%M%S') + f'{index:03d}'
        file_name = f'file-{stamp}.{ext}'
        local_path = asset_dir / file_name
        if download(src, local_path):
            body = re.sub(
                r'!\[img\]\(' + re.escape(src) + r'\)',
                f'![img](./assets/{note_basename}/{file_name})',
                body,
            )
            ok += 1
        else:
            fail += 1
        time.sleep(0.03)
    body = clean_markdown(body, title=title)
    body = convert_local_markdown_images_to_wikilinks(body)
    return body, ok, fail


def main():
    parser = argparse.ArgumentParser(description='Extract a WeChat article into Obsidian format.')
    parser.add_argument('url')
    parser.add_argument('--dest-dir', default=TARGET_DIRS['wechat'])
    parser.add_argument('--date', default=datetime.now().strftime('%Y%m%d'))
    args = parser.parse_args()

    JSON_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%dT%H%M%S')
    json_path = JSON_DIR / f'{stamp}.json'

    extract_cp = subprocess.run(
        [sys.executable, str(EXTRACT_SCRIPT), args.url, stamp],
        check=False,
        capture_output=True,
        text=True,
    )
    if extract_cp.returncode != 0:
        details = {
            'status': 'error',
            'error': 'wechat_extract_failed',
            'command': [sys.executable, str(EXTRACT_SCRIPT), args.url, stamp],
            'returncode': extract_cp.returncode,
            'stdout': extract_cp.stdout,
            'stderr': extract_cp.stderr,
        }
        print(json.dumps(details, ensure_ascii=False, indent=2), file=sys.stderr)
        sys.exit(extract_cp.returncode)

    data = load_json(json_path)
    title = sanitize_title(data.get('title') or '未命名')
    source_account = (data.get('author') or '').strip()
    image_count = len(data.get('images') or [])
    cover_image = first_image_url(data.get('images') or [])
    note_basename = f'{args.date}--{title}__weixin'
    dest_dir = Path(args.dest_dir)
    output = output_settings_for_source('wechat')
    dest_dir = Path(output['target_dir'])
    note_path = Path(note_path_for(str(dest_dir), note_basename, output['file_format']))
    asset_dir = dest_dir / 'assets' / note_basename
    if asset_dir.exists():
        shutil.rmtree(asset_dir)
    asset_dir.mkdir(parents=True, exist_ok=True)

    body, ok, fail = localize_images(
        data.get('body', ''),
        data.get('images', []),
        note_basename,
        asset_dir,
        title=title,
    )
    md = render_note_content(
        title=title,
        source_url=data.get('url') or args.url,
        source_type='wechat',
        base_markdown=(
        f'# {title}\n\n'
        f'原文链接: {data.get("url") or args.url}\n\n'
        f'作者: {data.get("author") or ""}\n\n'
        f'发布时间: {data.get("date") or ""}\n\n'
        f'---\n\n'
        f'{body}\n'
        ),
        extra={
            'author': source_account,
            'published_at': data.get('date') or '',
            'source_account': source_account,
            'source_url': data.get('url') or args.url,
            'image_count': image_count,
            'cover_image': cover_image,
            'capture_method': 'playwright',
        },
        include_frontmatter=output['include_frontmatter'],
        file_format=output['file_format'],
    )
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text(md, encoding='utf-8')

    result = build_result(
        'wechat',
        'public-post-wechat',
        output['target_dir'],
        note_path=str(note_path),
        asset_dir=str(asset_dir),
        images_ok=ok,
        images_fail=fail,
        file_format=output['file_format'],
        storage_mode=output['storage_mode'],
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
