#!/usr/bin/env python3
from __future__ import annotations
import json
import os
import re
import shutil
import sys
import time
import urllib.request
from datetime import datetime
from urllib.parse import urlparse

from common import build_result, obsidian_frontmatter, target_dir_for_source
from translation_utils import detect_language, is_simplified_chinese, prompt_translation_choice, translate_markdown


def x_jina_url(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if host.endswith('twitter.com'):
        host = host.replace('twitter.com', 'x.com')
    path = parsed.path or ''
    query = f'?{parsed.query}' if parsed.query else ''
    return f'https://r.jina.ai/http://{host}{path}{query}'


def sanitize_title(text: str) -> str:
    text = re.sub(r'[`*_#>\[\]()]', ' ', text)
    text = re.sub(r'https?://\S+', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    text = re.sub(r'^\s*.+?\s+on\s+X[:：]\s*', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\s*/\s*X\s*$', '', text, flags=re.IGNORECASE)
    text = re.sub(r'^\s*["“](.*)["”]\s*$', r'\1', text)
    text = re.sub(r'[\\/:*?"<>|]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return (text[:60] or 'X-post').strip()


def parse_x_identity(source_url: str) -> tuple[str | None, str | None]:
    parsed = urlparse(source_url)
    parts = [p for p in parsed.path.split('/') if p]
    user = parts[0] if parts else None
    status_id = None
    if len(parts) >= 3 and parts[1] == 'status':
        status_id = parts[2]
    return user, status_id


def extract_title(body: str, source_url: str) -> str:
    lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
    bad_titles = {'X', 'Twitter', 'X-post', 'Post'}
    bad_fragments = [
        'Don’t miss what’s happening',
        "Don't miss what's happening",
        'Hmm...this page doesn’t exist',
        "Hmm...this page doesn't exist",
        'People on X are the first to know.',
        'Sign up',
        'Log in',
    ]

    for ln in lines[:12]:
        if ln.startswith('Title:'):
            cand = sanitize_title(ln.split(':', 1)[1].strip())
            if cand and cand not in bad_titles:
                return cand

    for ln in lines[:20]:
        cand = sanitize_title(ln)
        if not cand or cand in bad_titles:
            continue
        if any(frag in ln for frag in bad_fragments):
            continue
        if ln.startswith(('URL Source:', 'Published Time:', 'Warning:', 'Markdown Content:')):
            continue
        return cand

    user, status_id = parse_x_identity(source_url)
    if user and status_id:
        return f'{user}-{status_id}'
    if user:
        return f'{user}-x-post'
    return 'X-post'


def fetch_text(url: str) -> str:
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode('utf-8', errors='replace')


def infer_ext(url: str) -> str:
    lower = url.lower()
    if 'format=png' in lower or lower.endswith('.png'):
        return 'png'
    if 'format=gif' in lower or lower.endswith('.gif'):
        return 'gif'
    if 'format=webp' in lower or lower.endswith('.webp'):
        return 'webp'
    return 'jpg'


def download(url: str, path: str) -> bool:
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()
        with open(path, 'wb') as f:
            f.write(data)
        return True
    except Exception:
        return False


def localize_images(body: str, note_basename: str, target_dir: str) -> tuple[str, str | None, int, int]:
    asset_dir = os.path.join(target_dir, 'assets', note_basename)
    if os.path.isdir(asset_dir):
        shutil.rmtree(asset_dir)
    os.makedirs(asset_dir, exist_ok=True)

    # 匹配 [![alt](image_url)](link_url) 格式
    image_pattern = re.compile(r'\[!\[(?P<alt>[^\]]*)\]\((?P<src>https://pbs\.twimg\.com/[^\)]+)\)\]\((?P<link>https://x\.com/[^\)]+)\)')
    # 匹配 ![alt](image_url) 格式（无链接包裹）
    simple_image_pattern = re.compile(r'!\[(?P<alt>[^\]]*)\]\((?P<src>https://pbs\.twimg\.com/[^\)]+)\)')
    
    matches = list(image_pattern.finditer(body))
    simple_matches = list(simple_image_pattern.finditer(body))
    
    ok = 0
    fail = 0
    image_index = 0

    # 处理带链接包裹的图片
    for match in matches:
        src = match.group('src')
        alt = match.group('alt') or 'Image'
        if '/profile_images/' in src:
            continue
        image_index += 1
        ext = infer_ext(src)
        stamp = datetime.now().strftime('%Y%m%d%H%M%S') + f'{image_index:03d}'
        file_name = f'file-{stamp}.{ext}'
        local_path = os.path.join(asset_dir, file_name)
        if download(src, local_path):
            rel = f'assets/{note_basename}/{file_name}'
            replacement = f'![[{rel}]]'
            body = body.replace(match.group(0), replacement)
            ok += 1
        else:
            fail += 1
        time.sleep(0.03)
    
    # 处理简单图片（无链接包裹）
    for match in simple_matches:
        src = match.group('src')
        alt = match.group('alt') or 'Image'
        if '/profile_images/' in src:
            continue
        # 跳过已经处理过的
        if 'file-' in src and note_basename in src:
            continue
        image_index += 1
        ext = infer_ext(src)
        stamp = datetime.now().strftime('%Y%m%d%H%M%S') + f'{image_index:03d}'
        file_name = f'file-{stamp}.{ext}'
        local_path = os.path.join(asset_dir, file_name)
        if download(src, local_path):
            rel = f'assets/{note_basename}/{file_name}'
            replacement = f'![[{rel}]]'
            body = body.replace(match.group(0), replacement)
            ok += 1
        else:
            fail += 1
        time.sleep(0.03)


    if ok == 0 and fail == 0:
        shutil.rmtree(asset_dir)
        return body, None, 0, 0
    return body, asset_dir, ok, fail


def main():
    if len(sys.argv) not in (2, 4):
        print(json.dumps({'status': 'error', 'error': 'usage: x_executor.py <url> [--translation-choice ask|translate|original|both]'}, ensure_ascii=False))
        sys.exit(1)

    source_url = sys.argv[1].strip()
    translation_choice = 'ask'
    if len(sys.argv) == 4:
        if sys.argv[2] != '--translation-choice' or sys.argv[3] not in {'ask', 'translate', 'original', 'both'}:
            print(json.dumps({'status': 'error', 'error': 'invalid translation-choice'}, ensure_ascii=False))
            sys.exit(1)
        translation_choice = sys.argv[3]
    fetch_url = x_jina_url(source_url)
    target_dir = target_dir_for_source('x')
    os.makedirs(target_dir, exist_ok=True)

    try:
        body = fetch_text(fetch_url)
        title = extract_title(body, source_url)
        date_str = datetime.now().strftime('%Y%m%d')
        basename = f"{date_str}--{title}"
        body, asset_dir, images_ok, images_fail = localize_images(body, basename, target_dir)
        note_path = os.path.join(target_dir, f'{basename}.md')
        base_markdown = (
            f"# {title}\n\n"
            f"原文链接: {source_url}\n"
            f"抓取链接: {fetch_url}\n\n"
            f"---\n\n{body}\n"
        )
        detected_lang = detect_language(base_markdown, None)
        if not is_simplified_chinese(detected_lang) and translation_choice == 'ask':
            translation_choice = prompt_translation_choice('x', detected_lang, title)
        frontmatter = obsidian_frontmatter(
            title=title,
            source_url=source_url,
            source_type='x',
            extra={
                'capture_method': 'r.jina.ai',
                'fetch_url': fetch_url,
                'source_language': detected_lang,
                'translated': False,
            },
        )
        md = (
            f"{frontmatter}"
            f"{base_markdown}"
        )
        with open(note_path, 'w', encoding='utf-8') as f:
            f.write(md)
        translated_note_path = None
        if not is_simplified_chinese(detected_lang) and translation_choice in {'translate', 'both'}:
            translated = translate_markdown(base_markdown, model_label='kimi 2.5')
            zh_title = sanitize_title(translated['translated_title'] or f'中文译文 {title}')
            zh_basename = f"{date_str}--{zh_title}__x"
            translated_note_path = os.path.join(target_dir, f'{zh_basename}.md')
            translated_frontmatter = obsidian_frontmatter(
                title=zh_title,
                source_url=source_url,
                source_type='x',
                extra={
                    'capture_method': 'r.jina.ai',
                    'fetch_url': fetch_url,
                    'source_language': detected_lang,
                    'translated': True,
                    'translation_model': translated['model'],
                    'translation_strategy': translated['strategy'],
                    'original_title': title,
                },
            )
            translated_md = f"{translated_frontmatter}{translated['translated_markdown'].rstrip()}\n"
            with open(translated_note_path, 'w', encoding='utf-8') as f:
                f.write(translated_md)
            if translation_choice == 'translate' and os.path.exists(note_path):
                os.remove(note_path)
        result = build_result(
            'x',
            'x-jina-http',
            target_dir,
            note_path=translated_note_path if translation_choice == 'translate' and translated_note_path else note_path,
            asset_dir=asset_dir,
            fetch_url=fetch_url,
            images_ok=images_ok,
            images_fail=images_fail,
            source_language=detected_lang,
            translation_choice=translation_choice,
            translated_note_path=translated_note_path,
        )
    except Exception as e:
        result = build_result('x', 'x-jina-http', target_dir, status='error', error=str(e), fetch_url=fetch_url)

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
