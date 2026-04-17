#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

from common import TARGET_DIRS, build_result, load_workspace_env, obsidian_frontmatter
from translation_utils import detect_language, is_simplified_chinese, prompt_translation_choice, translate_markdown
from x_opencli_executor import sanitize_title


API_URL = 'https://api.x.com/2/tweets/{tweet_id}'
FX_API_URL = 'https://api.fxtwitter.com/{username}/status/{tweet_id}'
API_FIELDS = {
    'tweet.fields': 'article,attachments,author_id,created_at,entities,note_tweet,text',
    'expansions': 'article.cover_media,article.media_entities,attachments.media_keys,author_id',
    'media.fields': 'type,url,preview_image_url,alt_text',
    'user.fields': 'name,username',
}


def get_bearer_token() -> str | None:
    for key in ('X_BEARER_TOKEN', 'TWITTER_BEARER_TOKEN'):
        value = (os.environ.get(key) or '').strip()
        if value:
            return value
    return None


def parse_status_url(source_url: str) -> tuple[str | None, str | None]:
    parsed = urllib.parse.urlparse(source_url)
    parts = [p for p in parsed.path.split('/') if p]
    if len(parts) >= 3 and parts[1] == 'status':
        return parts[0], parts[2]
    if len(parts) >= 3 and parts[0] == 'i' and parts[1] == 'article':
        return None, parts[2]
    return None, None


def fetch_tweet(tweet_id: str, bearer_token: str) -> dict:
    query = urllib.parse.urlencode(API_FIELDS)
    url = API_URL.format(tweet_id=tweet_id) + '?' + query
    last_error = None
    for attempt in range(4):
        try:
            req = urllib.request.Request(
                url,
                headers={
                    'Authorization': f'Bearer {bearer_token}',
                    'User-Agent': 'Mozilla/5.0',
                },
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except Exception as exc:
            last_error = exc
            if attempt < 3:
                time.sleep(1.5 * (attempt + 1))
    raise last_error


def fetch_fxtwitter_tweet(username: str, tweet_id: str) -> dict:
    url = FX_API_URL.format(username=username, tweet_id=tweet_id)
    last_error = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode('utf-8'))
            if data.get('code') != 200:
                raise ValueError(data.get('message') or f'FxTwitter returned code {data.get("code")}')
            return data
        except Exception as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(1.0 * (attempt + 1))
    raise last_error


def indexed_media(includes: dict) -> dict[str, dict]:
    return {item.get('media_key'): item for item in (includes or {}).get('media', []) if item.get('media_key')}


def first_user_handle(includes: dict, author_id: str | None) -> str | None:
    for user in (includes or {}).get('users', []):
        if author_id and user.get('id') == author_id:
            return user.get('username')
    users = (includes or {}).get('users', [])
    return users[0].get('username') if users else None


def extract_media_urls(data: dict, includes: dict) -> list[str]:
    media_by_key = indexed_media(includes)
    urls: list[str] = []
    seen: set[str] = set()

    def add_media_key(media_key: str | None):
        if not media_key:
            return
        media = media_by_key.get(media_key) or {}
        media_url = media.get('url') or media.get('preview_image_url')
        if not media_url or media_url in seen:
            return
        seen.add(media_url)
        urls.append(media_url)

    article = data.get('article') or {}
    add_media_key(article.get('cover_media'))
    for media_key in article.get('media_entities') or []:
        add_media_key(media_key)

    attachments = data.get('attachments') or {}
    for media_key in attachments.get('media_keys') or []:
        add_media_key(media_key)

    return urls


def fxtwitter_entity_map(article: dict) -> dict[str, dict]:
    mapping: dict[str, dict] = {}
    for item in (article.get('content', {}) or {}).get('entityMap') or []:
        if not isinstance(item, dict):
            continue
        key = item.get('key')
        value = item.get('value')
        if key is None or not isinstance(value, dict):
            continue
        mapping[str(key)] = value
    return mapping


def fxtwitter_media_catalog(article: dict) -> tuple[str | None, dict[str, str]]:
    cover_url = None
    media_map: dict[str, str] = {}

    cover = article.get('cover_media') or {}
    cover_url = (((cover.get('media_info') or {}).get('original_img_url')) or '').strip() or None
    cover_id = str(cover.get('media_id') or '').strip()
    if cover_id and cover_url:
        media_map[cover_id] = cover_url

    for item in article.get('media_entities') or []:
        media_id = str(item.get('media_id') or '').strip()
        media_url = ((((item.get('media_info') or {}).get('original_img_url')) or '')).strip()
        if media_id and media_url:
            media_map[media_id] = media_url
    return cover_url, media_map


def select_content(data: dict, author_handle: str | None, source_url: str) -> tuple[str, str, str, str]:
    article = data.get('article') or {}
    note_tweet = data.get('note_tweet') or {}
    text = (data.get('text') or '').strip()
    title = ''
    note_kind = 'post'
    content = ''

    if article.get('plain_text'):
        note_kind = 'article'
        title = sanitize_title(article.get('title') or article.get('preview_text') or text or 'X Article')
        content = article['plain_text'].strip()
    elif note_tweet.get('text'):
        note_kind = 'note_tweet'
        title = sanitize_title(f"@{author_handle} 的 Note Tweet" if author_handle else 'Note Tweet')
        content = note_tweet['text'].strip()
    else:
        title = sanitize_title(text or (f'{author_handle}-post' if author_handle else 'X-post'))
        content = text

    canonical_url = source_url
    if author_handle and data.get('id'):
        canonical_url = f'https://x.com/{author_handle}/status/{data["id"]}'
    return title, content, note_kind, canonical_url


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


def localize_media(media_urls: list[str], note_basename: str, target_dir: str) -> tuple[list[str], str | None, int, int]:
    if not media_urls:
        return [], None, 0, 0
    asset_dir = Path(target_dir) / 'assets' / note_basename
    if asset_dir.exists():
        shutil.rmtree(asset_dir)
    asset_dir.mkdir(parents=True, exist_ok=True)

    links: list[str] = []
    ok = 0
    fail = 0
    for i, src in enumerate(media_urls, start=1):
        file_name = f'file-{datetime.now().strftime("%Y%m%d%H%M%S")}{i:03d}.{infer_ext(src)}'
        dst = asset_dir / file_name
        if download(src, str(dst)):
            links.append(f'![[assets/{note_basename}/{file_name}]]')
            ok += 1
        else:
            fail += 1
        time.sleep(0.03)

    if ok == 0:
        shutil.rmtree(asset_dir)
        return [], None, 0, fail
    return links, str(asset_dir), ok, fail


def localize_media_map(media_urls: list[str], note_basename: str, target_dir: str) -> tuple[dict[str, str], str | None, int, int]:
    ordered_unique: list[str] = []
    seen: set[str] = set()
    for url in media_urls:
        if url and url not in seen:
            seen.add(url)
            ordered_unique.append(url)
    if not ordered_unique:
        return {}, None, 0, 0

    asset_dir = Path(target_dir) / 'assets' / note_basename
    if asset_dir.exists():
        shutil.rmtree(asset_dir)
    asset_dir.mkdir(parents=True, exist_ok=True)

    mapping: dict[str, str] = {}
    ok = 0
    fail = 0
    for i, src in enumerate(ordered_unique, start=1):
        file_name = f'file-{datetime.now().strftime("%Y%m%d%H%M%S")}{i:03d}.{infer_ext(src)}'
        dst = asset_dir / file_name
        if download(src, str(dst)):
            mapping[src] = f'![[assets/{note_basename}/{file_name}]]'
            ok += 1
        else:
            fail += 1
        time.sleep(0.03)

    if ok == 0:
        shutil.rmtree(asset_dir)
        return {}, None, 0, fail
    return mapping, str(asset_dir), ok, fail


def extract_code_blocks(data: dict) -> list[str]:
    blocks: list[str] = []
    for item in ((data.get('article') or {}).get('entities') or {}).get('code') or []:
        content = (item.get('content') or '').strip()
        if content:
            blocks.append(content)
    return blocks


def wrap_inline_styles(text: str, ranges: list[dict] | None) -> str:
    if not text or not ranges:
        return text
    markers: dict[int, list[str]] = {}
    for item in ranges:
        try:
            start = int(item.get('offset', 0))
            length = int(item.get('length', 0))
        except (TypeError, ValueError):
            continue
        end = start + length
        style = item.get('style')
        marker = None
        if style == 'Bold':
            marker = '**'
        elif style == 'Italic':
            marker = '*'
        if not marker or length <= 0:
            continue
        markers.setdefault(start, []).append(marker)
        markers.setdefault(end, []).insert(0, marker)

    parts: list[str] = []
    for idx in range(len(text) + 1):
        for marker in markers.get(idx, []):
            parts.append(marker)
        if idx < len(text):
            parts.append(text[idx])
    return ''.join(parts)


def render_fxtwitter_block(block: dict, entity_map: dict[str, dict], media_id_to_link: dict[str, str]) -> str | None:
    block_type = (block.get('type') or 'unstyled').strip()
    text = wrap_inline_styles(block.get('text') or '', block.get('inlineStyleRanges'))
    if block_type == 'atomic':
        ranges = block.get('entityRanges') or []
        entity_key = str((ranges[0] or {}).get('key')) if ranges else ''
        entity = entity_map.get(entity_key) or {}
        entity_type = entity.get('type')
        entity_data = entity.get('data') or {}
        if entity_type == 'MARKDOWN':
            markdown = (entity_data.get('markdown') or '').strip()
            return markdown or None
        if entity_type == 'MEDIA':
            items = entity_data.get('mediaItems') or []
            media_id = str((items[0] or {}).get('mediaId')) if items else ''
            return media_id_to_link.get(media_id)
        return None
    if block_type == 'header-one':
        return f'## {text.strip()}'
    if block_type == 'header-two':
        return f'### {text.strip()}'
    if block_type == 'header-three':
        return f'#### {text.strip()}'
    if block_type == 'blockquote':
        lines = [line.rstrip() for line in text.splitlines() if line.strip()]
        return '\n'.join(f'> {line}' for line in lines) if lines else None
    if block_type == 'unstyled':
        return text.strip() or None
    return text.strip() or None


def render_fxtwitter_article(article: dict, media_link_map: dict[str, str]) -> str:
    blocks = ((article.get('content') or {}).get('blocks')) or []
    entity_map = fxtwitter_entity_map(article)
    cover_url, media_url_map = fxtwitter_media_catalog(article)
    media_id_to_link = {
        media_id: media_link_map[url]
        for media_id, url in media_url_map.items()
        if url in media_link_map
    }

    output: list[str] = []
    if cover_url and cover_url in media_link_map:
        output.extend([media_link_map[cover_url], ''])

    idx = 0
    while idx < len(blocks):
        block = blocks[idx]
        block_type = (block.get('type') or '').strip()
        if block_type in {'ordered-list-item', 'unordered-list-item'}:
            list_type = block_type
            list_index = 1
            while idx < len(blocks) and (blocks[idx].get('type') or '').strip() == list_type:
                item = blocks[idx]
                item_text = wrap_inline_styles(item.get('text') or '', item.get('inlineStyleRanges')).strip()
                if item_text:
                    prefix = f'{list_index}. ' if list_type == 'ordered-list-item' else '- '
                    output.append(prefix + item_text)
                    if list_type == 'ordered-list-item':
                        list_index += 1
                idx += 1
            output.append('')
            continue

        rendered = render_fxtwitter_block(block, entity_map, media_id_to_link)
        if rendered:
            output.extend([rendered, ''])
        idx += 1

    while output and not output[-1].strip():
        output.pop()
    return '\n'.join(output).rstrip() + '\n'


def image_slot_score(prev_line: str, next_line: str) -> int:
    context = f'{prev_line} {next_line}'
    patterns = [
        r'是这样的',
        r'安全哲学',
        r'失败策略',
        r'架构',
        r'流程图',
        r'系统工程',
        r'这不是一个',
    ]
    score = 0
    for pattern in patterns:
        if re.search(pattern, context):
            score += 3
    if '图' in context or '如下' in context:
        score += 2
    return score


def interleave_rich_blocks(content: str, media_links: list[str], code_blocks: list[str]) -> str:
    if not media_links and not code_blocks:
        return content.rstrip() + '\n'

    lines = content.splitlines()
    cover = media_links[0] if media_links else None
    body_images = media_links[1:] if media_links else []
    if not body_images and not code_blocks:
        if cover:
            return f'{cover}\n\n{content.rstrip()}\n'
        return content.rstrip() + '\n'
    if cover and not body_images and not code_blocks:
        return f'{cover}\n\n{content.rstrip()}\n'

    output: list[str] = []
    if cover:
        output.extend([cover, ''])
    blank_slots = [i for i, line in enumerate(lines) if not line.strip()]
    if blank_slots:
        slot_map: dict[int, str] = {}
        image_slots: list[int] = []
        if body_images:
            scored_slots = []
            for idx in blank_slots:
                prev_line = next((lines[j].strip() for j in range(idx - 1, -1, -1) if lines[j].strip()), '')
                next_line = next((lines[j].strip() for j in range(idx + 1, len(lines)) if lines[j].strip()), '')
                scored_slots.append((image_slot_score(prev_line, next_line), idx))
            scored_slots.sort(key=lambda item: (-item[0], item[1]))
            image_slots = sorted(idx for _, idx in scored_slots[:len(body_images)])
            for idx, image in zip(image_slots, body_images):
                slot_map[idx] = image

        code_iter = iter(code_blocks)
        for idx, line in enumerate(lines):
            if not line.strip():
                if idx in slot_map:
                    output.extend([slot_map[idx], ''])
                    continue
                block = next(code_iter, None)
                if block is not None:
                    output.extend([block, ''])
                    continue
                output.append(line)
            else:
                output.append(line)
        remaining = list(code_iter)
        for image in body_images:
            if image not in slot_map.values():
                remaining.append(image)
        if remaining:
            output.extend([''])
            for block in remaining:
                output.extend([block, ''])
        return '\n'.join(output).rstrip() + '\n'

    blocks = [line for line in lines if line.strip()]
    rich_blocks = []
    if body_images:
        rich_blocks.extend(body_images)
    if code_blocks:
        rich_blocks.extend(code_blocks)
    if not blocks:
        prefix = [cover] if cover else []
        return '\n\n'.join(prefix + rich_blocks).rstrip() + '\n'

    insert_after: dict[int, list[str]] = {}
    total_blocks = len(blocks)
    total_rich = len(rich_blocks)
    for idx, block in enumerate(rich_blocks, start=1):
        anchor = max(1, round(total_blocks * idx / (total_rich + 1)))
        insert_after.setdefault(anchor, []).append(block)

    seen_blocks = 0
    for line in lines:
        output.append(line)
        if line.strip():
            seen_blocks += 1
            for block in insert_after.get(seen_blocks, []):
                output.extend(['', block, ''])

    return '\n'.join(output).rstrip() + '\n'


def main():
    load_workspace_env()
    if len(sys.argv) not in (2, 4):
        print(json.dumps({'status': 'error', 'error': 'usage: x_api_executor.py <url> [--translation-choice ask|translate|original|both]'}, ensure_ascii=False))
        sys.exit(1)

    source_url = sys.argv[1].strip()
    translation_choice = 'ask'
    if len(sys.argv) == 4:
        if sys.argv[2] != '--translation-choice' or sys.argv[3] not in {'ask', 'translate', 'original', 'both'}:
            print(json.dumps({'status': 'error', 'error': 'invalid translation-choice'}, ensure_ascii=False))
            sys.exit(1)
        translation_choice = sys.argv[3]

    target_dir = TARGET_DIRS['x']
    os.makedirs(target_dir, exist_ok=True)

    bearer_token = get_bearer_token()
    if not bearer_token:
        result = build_result('x', 'x-api-v2', target_dir, status='error', error='missing X_BEARER_TOKEN or TWITTER_BEARER_TOKEN')
        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(1)

    _, tweet_id = parse_status_url(source_url)
    if not tweet_id:
        result = build_result('x', 'x-api-v2', target_dir, status='error', error='unsupported X URL: missing tweet/article id')
        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(1)

    try:
        payload = fetch_tweet(tweet_id, bearer_token)
        data = payload.get('data') or {}
        includes = payload.get('includes') or {}
        if not data:
            raise ValueError(payload.get('detail') or 'X API returned empty data')

        author_handle = first_user_handle(includes, data.get('author_id'))
        title, content, note_kind, canonical_url = select_content(data, author_handle, source_url)
        if not content:
            raise ValueError('X API returned empty content')

        date_str = datetime.now().strftime('%Y%m%d')
        basename = f'{date_str}--{title}'
        media_urls = extract_media_urls(data, includes)
        code_blocks = extract_code_blocks(data)
        capture_method = 'x-api-v2'

        fx_payload = None
        _, parsed_username = None, None
        parsed_username, _ = parse_status_url(source_url)
        if parsed_username:
            try:
                fx_payload = fetch_fxtwitter_tweet(parsed_username, tweet_id)
            except Exception:
                fx_payload = None

        media_links: list[str] = []
        media_link_map: dict[str, str] = {}
        asset_dir = None
        images_ok = 0
        images_fail = 0
        mixed_content = ''

        fx_article = ((fx_payload or {}).get('tweet') or {}).get('article') or {}
        fx_blocks = ((fx_article.get('content') or {}).get('blocks')) or []
        if note_kind == 'article' and fx_blocks:
            title = sanitize_title(fx_article.get('title') or title)
            basename = f'{date_str}--{title}'
            fx_cover_url, fx_media_url_map = fxtwitter_media_catalog(fx_article)
            ordered_media_urls = []
            if fx_cover_url:
                ordered_media_urls.append(fx_cover_url)
            body_media_ids: list[str] = []
            entity_map = fxtwitter_entity_map(fx_article)
            for block in fx_blocks:
                if (block.get('type') or '').strip() != 'atomic':
                    continue
                ranges = block.get('entityRanges') or []
                entity_key = str((ranges[0] or {}).get('key')) if ranges else ''
                entity = entity_map.get(entity_key) or {}
                if entity.get('type') != 'MEDIA':
                    continue
                items = (entity.get('data') or {}).get('mediaItems') or []
                media_id = str((items[0] or {}).get('mediaId')) if items else ''
                if media_id:
                    body_media_ids.append(media_id)
            for media_id in body_media_ids:
                media_url = fx_media_url_map.get(media_id)
                if media_url:
                    ordered_media_urls.append(media_url)
            media_link_map, asset_dir, images_ok, images_fail = localize_media_map(ordered_media_urls, basename, target_dir)
            mixed_content = render_fxtwitter_article(fx_article, media_link_map)
            capture_method = 'x-api-v2+fxtwitter-blocks'
        else:
            media_links, asset_dir, images_ok, images_fail = localize_media(media_urls, basename, target_dir)
            mixed_content = interleave_rich_blocks(content, media_links, code_blocks)

        meta_lines = [f'原文链接: {canonical_url}', '抓取方式: X API v2']
        if capture_method != 'x-api-v2':
            meta_lines[-1] = '抓取方式: X API v2 + FxTwitter blocks'
        if author_handle:
            meta_lines.append(f'作者: @{author_handle}')
        if note_kind != 'post':
            meta_lines.append(f'帖子类型: {note_kind}')
        meta = '\n'.join(meta_lines)
        base_markdown = f'# {title}\n\n{meta}\n\n---\n\n{mixed_content}'

        detected_lang = detect_language(content, None)
        if not is_simplified_chinese(detected_lang) and translation_choice == 'ask':
            translation_choice = prompt_translation_choice('x', detected_lang, title)

        note_path = os.path.join(target_dir, f'{basename}.md')
        frontmatter = obsidian_frontmatter(
            title=title,
            source_url=canonical_url,
            source_type='x',
            extra={
                'capture_method': 'x-api-v2',
                'render_method': capture_method,
                'source_language': detected_lang,
                'translated': False,
                'author_handle': author_handle,
                'x_post_kind': note_kind,
                'x_tweet_id': data.get('id'),
            },
        )
        with open(note_path, 'w', encoding='utf-8') as f:
            f.write(f'{frontmatter}{base_markdown}')

        translated_note_path = None
        if not is_simplified_chinese(detected_lang) and translation_choice in {'translate', 'both'}:
            translated = translate_markdown(base_markdown, model_label='kimi 2.5')
            zh_title = sanitize_title(translated['translated_title'] or f'中文译文 {title}')
            zh_basename = f'{date_str}--{zh_title}'
            translated_note_path = os.path.join(target_dir, f'{zh_basename}.md')
            translated_frontmatter = obsidian_frontmatter(
                title=zh_title,
                source_url=canonical_url,
                source_type='x',
                extra={
                    'capture_method': 'x-api-v2',
                    'render_method': capture_method,
                    'source_language': detected_lang,
                    'translated': True,
                    'translation_model': translated['model'],
                    'translation_strategy': translated['strategy'],
                    'original_title': title,
                    'author_handle': author_handle,
                    'x_post_kind': note_kind,
                    'x_tweet_id': data.get('id'),
                },
            )
            with open(translated_note_path, 'w', encoding='utf-8') as f:
                f.write(f"{translated_frontmatter}{translated['translated_markdown'].rstrip()}\n")
            if translation_choice == 'translate' and os.path.exists(note_path):
                os.remove(note_path)

        result = build_result(
            'x',
            'x-api-v2',
            target_dir,
            note_path=translated_note_path if translation_choice == 'translate' and translated_note_path else note_path,
            asset_dir=asset_dir,
            source_language=detected_lang,
            translation_choice=translation_choice,
            translated_note_path=translated_note_path,
            author_handle=author_handle,
            images_ok=images_ok,
            images_fail=images_fail,
        )
    except Exception as e:
        result = build_result('x', 'x-api-v2', target_dir, status='error', error=str(e))

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
