#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from datetime import datetime

from common import atomic_write_text, build_result, load_workspace_env, obsidian_frontmatter, target_dir_for_source
from translation_utils import detect_language, is_simplified_chinese, prompt_translation_choice, translate_markdown
from x_api_executor import (
    fetch_fxtwitter_tweet,
    fxtwitter_entity_map,
    fxtwitter_media_catalog,
    localize_media,
    localize_media_map,
    parse_status_url,
    render_fxtwitter_article,
)
from x_opencli_executor import sanitize_title


def article_plain_text(article: dict) -> str:
    return '\n\n'.join(
        (block.get('text') or '').strip()
        for block in ((article.get('content') or {}).get('blocks') or [])
        if (block.get('text') or '').strip()
    )


def regular_media_urls(tweet: dict) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    media = tweet.get('media') or {}
    items = media.get('all') if isinstance(media, dict) else media
    for item in items or []:
        if not isinstance(item, dict):
            continue
        url = item.get('url') or item.get('thumbnail_url')
        if url and url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def build_article_body(article: dict, basename: str, target_dir: str) -> tuple[str, str | None, int, int]:
    cover_url, media_url_map = fxtwitter_media_catalog(article)
    ordered_urls: list[str] = [cover_url] if cover_url else []
    entity_map = fxtwitter_entity_map(article)
    for block in ((article.get('content') or {}).get('blocks') or []):
        if (block.get('type') or '').strip() != 'atomic':
            continue
        ranges = block.get('entityRanges') or []
        key = str((ranges[0] or {}).get('key')) if ranges else ''
        entity = entity_map.get(key) or {}
        if entity.get('type') != 'MEDIA':
            continue
        items = (entity.get('data') or {}).get('mediaItems') or []
        media_id = str((items[0] or {}).get('mediaId')) if items else ''
        media_url = media_url_map.get(media_id)
        if media_url:
            ordered_urls.append(media_url)
    link_map, asset_dir, ok, fail = localize_media_map(ordered_urls, basename, target_dir)
    return render_fxtwitter_article(article, link_map), asset_dir, ok, fail


def main() -> int:
    load_workspace_env()
    if len(sys.argv) not in (2, 4):
        print(json.dumps({'status': 'error', 'error': 'usage: x_fxtwitter_executor.py <url> [--translation-choice ask|translate|original|both]'}, ensure_ascii=False))
        return 2

    source_url = sys.argv[1].strip()
    translation_choice = 'ask'
    if len(sys.argv) == 4:
        if sys.argv[2] != '--translation-choice' or sys.argv[3] not in {'ask', 'translate', 'original', 'both'}:
            print(json.dumps({'status': 'error', 'error': 'invalid translation-choice'}, ensure_ascii=False))
            return 2
        translation_choice = sys.argv[3]

    target_dir = target_dir_for_source('x')
    os.makedirs(target_dir, exist_ok=True)
    username, tweet_id = parse_status_url(source_url)
    if not username or not tweet_id:
        result = build_result('x', 'x-fxtwitter', target_dir, status='error', error='FxTwitter fallback requires an /<username>/status/<id> URL')
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1

    try:
        payload = fetch_fxtwitter_tweet(username, tweet_id)
        tweet = payload.get('tweet') or {}
        article = tweet.get('article') or {}
        author = tweet.get('author') or {}
        author_handle = (author.get('screen_name') or username).strip()
        canonical_url = (tweet.get('url') or f'https://x.com/{author_handle}/status/{tweet_id}').strip()
        date_str = datetime.now().strftime('%Y%m%d')

        if ((article.get('content') or {}).get('blocks') or []):
            note_kind = 'article'
            title = sanitize_title(article.get('title') or article.get('preview_text') or f'@{author_handle} 的 X Article')
            plain_content = article_plain_text(article)
            basename = f'{date_str}--{title}'
            mixed_content, asset_dir, images_ok, images_fail = build_article_body(article, basename, target_dir)
        else:
            note_kind = 'post'
            plain_content = (tweet.get('raw_text') or tweet.get('text') or '').strip()
            if not plain_content:
                raise ValueError('FxTwitter returned no article or post text')
            title = sanitize_title(plain_content or f'@{author_handle} 的帖子')
            basename = f'{date_str}--{title}'
            media_links, asset_dir, images_ok, images_fail = localize_media(regular_media_urls(tweet), basename, target_dir)
            mixed_content = '\n\n'.join(media_links + [plain_content]).strip() + '\n'

        meta = f'原文链接: {canonical_url}\n抓取方式: FxTwitter public API\n作者: @{author_handle}\n帖子类型: {note_kind}'
        base_markdown = f'# {title}\n\n{meta}\n\n---\n\n{mixed_content}'
        detected_lang = detect_language(plain_content, None)
        if not is_simplified_chinese(detected_lang) and translation_choice == 'ask':
            translation_choice = prompt_translation_choice('x', detected_lang, title)

        note_path = os.path.join(target_dir, f'{basename}.md')
        frontmatter = obsidian_frontmatter(
            title=title,
            source_url=canonical_url,
            source_type='x',
            extra={
                'capture_method': 'fxtwitter-public-api',
                'source_language': detected_lang,
                'translated': False,
                'author_handle': author_handle,
                'x_post_kind': note_kind,
                'x_tweet_id': tweet.get('id') or tweet_id,
            },
        )
        atomic_write_text(note_path, f'{frontmatter}{base_markdown}')

        translated_note_path = None
        if not is_simplified_chinese(detected_lang) and translation_choice in {'translate', 'both'}:
            translated = translate_markdown(base_markdown)
            zh_title = sanitize_title(translated['translated_title'] or f'中文译文 {title}')
            translated_note_path = os.path.join(target_dir, f'{date_str}--{zh_title}.md')
            translated_frontmatter = obsidian_frontmatter(
                title=zh_title,
                source_url=canonical_url,
                source_type='x',
                extra={
                    'capture_method': 'fxtwitter-public-api',
                    'source_language': detected_lang,
                    'translated': True,
                    'translation_model': translated['model'],
                    'translation_strategy': translated['strategy'],
                    'original_title': title,
                    'author_handle': author_handle,
                    'x_post_kind': note_kind,
                    'x_tweet_id': tweet.get('id') or tweet_id,
                },
            )
            atomic_write_text(translated_note_path, f"{translated_frontmatter}{translated['translated_markdown'].rstrip()}\n")
            if translation_choice == 'translate' and os.path.exists(note_path):
                os.remove(note_path)

        result = build_result(
            'x',
            'x-fxtwitter',
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
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        result = build_result('x', 'x-fxtwitter', target_dir, status='error', error=str(exc))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1


if __name__ == '__main__':
    sys.exit(main())
