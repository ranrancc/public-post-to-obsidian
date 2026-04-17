#!/usr/bin/env python3
from __future__ import annotations
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from common import build_result, obsidian_frontmatter, target_dir_for_source
from translation_utils import detect_language, is_simplified_chinese, prompt_translation_choice, translate_markdown


def sanitize_title(text: str) -> str:
    text = re.sub(r'[`*_#>\[\]()]', ' ', text)
    text = re.sub(r'https?://\S+', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    text = re.sub(r'[\\/:*?"<>|]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return (text[:80] or 'X-article').strip()


def is_note_tweet_title(text: str) -> bool:
    normalized = (text or '').strip().lower()
    return normalized in {'(note tweet)', 'note tweet', 'x-article', '(untitled)', 'untitled'}


def build_note_tweet_basename(date_str: str, author: str, canonical_url: str) -> str:
    status_id = canonical_url.rstrip('/').split('/')[-1] if '/status/' in canonical_url else 'post'
    author_slug = re.sub(r'[^A-Za-z0-9_.-]+', '-', (author or 'x').strip()).strip('-') or 'x'
    return f"{date_str}--{author_slug}-{status_id}"


def parse_json_output(stdout: str):
    text = stdout.strip()
    if not text:
        raise ValueError('opencli returned empty output')
    data = json.loads(text)
    if isinstance(data, list):
        if not data:
            raise ValueError('opencli returned empty list')
        return data[0]
    if isinstance(data, dict):
        return data
    raise ValueError('unexpected opencli output format')


def run_with_chrome_retry(cmd: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        err_text = f"{e.stderr or ''}\n{e.stdout or ''}".strip()
        needs_wake = (
            'Browser Extension is not connected' in err_text
            or 'Extension is not connected' in err_text
            or 'extension is not connected' in err_text.lower()
        )
        if not needs_wake:
            raise
        subprocess.run(['open', '-a', 'Google Chrome'], capture_output=True, text=True, check=False)
        subprocess.run(['sleep', '5'], capture_output=True, text=True, check=False)
        return subprocess.run(cmd, capture_output=True, text=True, check=True)


def collect_downloaded_media(download_root: Path) -> list[Path]:
    if not download_root.exists():
        return []
    exts = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
    return sorted([p for p in download_root.rglob('*') if p.is_file() and p.suffix.lower() in exts])


def localize_opencli_media(source_url: str, note_basename: str, target_dir: str) -> tuple[list[str], str | None]:
    with tempfile.TemporaryDirectory(prefix='x-opencli-media-') as tmp:
        tmp_path = Path(tmp)
        cmd = ['opencli', 'twitter', 'download', '--tweet-url', source_url, '--output', str(tmp_path)]
        try:
            run_with_chrome_retry(cmd)
        except subprocess.CalledProcessError:
            return [], None
        media_files = collect_downloaded_media(tmp_path)
        if not media_files:
            return [], None
        asset_dir = Path(target_dir) / 'assets' / note_basename
        if asset_dir.exists():
            shutil.rmtree(asset_dir)
        asset_dir.mkdir(parents=True, exist_ok=True)
        links: list[str] = []
        for i, src in enumerate(media_files, start=1):
            ext = src.suffix.lower() or '.jpg'
            name = f"file-{datetime.now().strftime('%Y%m%d%H%M%S')}{i:03d}{ext}"
            dst = asset_dir / name
            shutil.copy2(src, dst)
            links.append(f'![[assets/{note_basename}/{name}]]')
        return links, str(asset_dir)


def embed_media_with_llm(markdown: str, media_links: list[str], source_url: str) -> str:
    """
    用 LLM 把图片插回正文中语义最近的位置。
    如果 LLM 调用失败，降级策略：第一张放文章开头（封面），其余放末尾。
    """
    if not media_links:
        return markdown

    n = len(media_links)
    # 降级函数
    def fallback() -> str:
        result = markdown.rstrip()
        if n == 1:
            return media_links[0] + '\n\n' + result + '\n'
        cover = media_links[0]
        rest = '\n\n'.join(media_links[1:])
        return cover + '\n\n' + result + '\n\n' + rest + '\n'

    try:
        import urllib.request as _req
        import os as _os

        api_key = _os.environ.get('OPENAI_API_KEY') or _os.environ.get('GITHUB_TOKEN')
        base_url = _os.environ.get('OPENAI_BASE_URL', 'https://models.inference.ai.azure.com')
        model = 'gpt-4o-mini'

        if not api_key:
            return fallback()

        # 为每张图构造占位符，方便 LLM 引用
        placeholders = {f'[IMAGE_{i+1}]': link for i, link in enumerate(media_links)}
        placeholder_list = '\n'.join(f'{k} = {v}' for k, v in placeholders.items())

        system_prompt = (
            '你是一个 Markdown 编辑助手。用户会给你一篇文章正文和若干图片占位符。\n'
            '请判断每张图最可能出现在正文的哪个位置（通常在相关段落之后），\n'
            '将占位符直接插入对应位置，输出完整修改后的 Markdown。\n'
            '规则：\n'
            '1. 只插入占位符，不修改任何正文文字\n'
            '2. 图片占位符单独成段（前后各空一行）\n'
            '3. 若无法判断某张图的位置，将其放在文章末尾\n'
            '4. 只输出修改后的 Markdown，不要解释'
        )
        user_prompt = (
            f'图片占位符列表：\n{placeholder_list}\n\n'
            f'文章正文：\n{markdown}'
        )

        payload = json.dumps({
            'model': model,
            'messages': [
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': user_prompt},
            ],
            'max_tokens': 8192,
            'temperature': 0,
        }).encode('utf-8')

        req = _req.Request(
            f'{base_url}/chat/completions',
            data=payload,
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {api_key}',
            },
            method='POST',
        )
        with _req.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        result_md = data['choices'][0]['message']['content'].strip()

        # 把占位符换回真实的 wikilink
        for placeholder, link in placeholders.items():
            result_md = result_md.replace(placeholder, link)

        # 安全检查：确保所有图片都出现在结果里
        for link in media_links:
            if link not in result_md:
                return fallback()

        return result_md.rstrip() + '\n'

    except Exception:
        return fallback()


def main():
    if len(sys.argv) not in (2, 4):
        print(json.dumps({'status': 'error', 'error': 'usage: x_opencli_executor.py <url> [--translation-choice ask|translate|original|both]'}, ensure_ascii=False))
        sys.exit(1)

    source_url = sys.argv[1].strip()
    translation_choice = 'ask'
    if len(sys.argv) == 4:
        if sys.argv[2] != '--translation-choice' or sys.argv[3] not in {'ask', 'translate', 'original', 'both'}:
            print(json.dumps({'status': 'error', 'error': 'invalid translation-choice'}, ensure_ascii=False))
            sys.exit(1)
        translation_choice = sys.argv[3]

    target_dir = target_dir_for_source('x', interactive=False)
    os.makedirs(target_dir, exist_ok=True)

    cmd = ['opencli', 'twitter', 'article', source_url, '-f', 'json']
    try:
        cp = run_with_chrome_retry(cmd)
        item = parse_json_output(cp.stdout)
        raw_title = (item.get('title') or '').strip()
        author = (item.get('author') or '').strip()
        content = (item.get('content') or '').strip()
        canonical_url = (item.get('url') or source_url).strip()
        if not content:
            raise ValueError('opencli returned missing content')

        date_str = datetime.now().strftime('%Y%m%d')
        note_kind = 'article'
        if is_note_tweet_title(raw_title):
            title = f"@{author} 的 Note Tweet" if author else 'Note Tweet'
            basename = build_note_tweet_basename(date_str, author, canonical_url)
            heading = f"# {title}\n\n"
            meta = f"原文链接: {canonical_url}\n抓取方式: opencli twitter article\n帖子类型: Note Tweet（无独立标题）"
            if author:
                meta += f"\n作者: @{author}"
            note_kind = 'note_tweet'
        else:
            title = sanitize_title(raw_title)
            if not title:
                raise ValueError('opencli returned missing title/content')
            basename = f"{date_str}--{title}"
            heading = f"# {title}\n\n"
            meta = f"原文链接: {canonical_url}\n抓取方式: opencli twitter article"
            if author:
                meta += f"\n作者: @{author}"

        media_links, asset_dir = localize_opencli_media(source_url, basename, target_dir)
        note_path = os.path.join(target_dir, f'{basename}.md')
        base_markdown = f"{heading}{meta}\n\n---\n\n{content}\n"
        base_markdown = embed_media_with_llm(base_markdown, media_links, source_url)

        detected_lang = detect_language(content, None)
        if not is_simplified_chinese(detected_lang) and translation_choice == 'ask':
            translation_choice = prompt_translation_choice('x', detected_lang, title)

        frontmatter = obsidian_frontmatter(
            title=title,
            source_url=canonical_url,
            source_type='x',
            extra={
                'capture_method': 'opencli-twitter-article',
                'source_language': detected_lang,
                'translated': False,
                'author_handle': author or None,
                'x_post_kind': note_kind,
            },
        )
        md = f"{frontmatter}{base_markdown}"
        with open(note_path, 'w', encoding='utf-8') as f:
            f.write(md)

        translated_note_path = None
        if not is_simplified_chinese(detected_lang) and translation_choice in {'translate', 'both'}:
            translated = translate_markdown(base_markdown, model_label='kimi 2.5')
            zh_title = sanitize_title(translated['translated_title'] or f'中文译文 {title}')
            zh_basename = f"{date_str}--{zh_title}"
            translated_note_path = os.path.join(target_dir, f'{zh_basename}.md')
            translated_frontmatter = obsidian_frontmatter(
                title=zh_title,
                source_url=canonical_url,
                source_type='x',
                extra={
                    'capture_method': 'opencli-twitter-article',
                    'source_language': detected_lang,
                    'translated': True,
                    'translation_model': translated['model'],
                    'translation_strategy': translated['strategy'],
                    'original_title': title,
                    'author_handle': author or None,
                    'x_post_kind': note_kind,
                },
            )
            translated_md = f"{translated_frontmatter}{translated['translated_markdown'].rstrip()}\n"
            with open(translated_note_path, 'w', encoding='utf-8') as f:
                f.write(translated_md)
            if translation_choice == 'translate' and os.path.exists(note_path):
                os.remove(note_path)

        result = build_result(
            'x',
            'x-opencli-article',
            target_dir,
            note_path=translated_note_path if translation_choice == 'translate' and translated_note_path else note_path,
            asset_dir=asset_dir,
            source_language=detected_lang,
            translation_choice=translation_choice,
            translated_note_path=translated_note_path,
            author_handle=author,
        )
    except subprocess.CalledProcessError as e:
        stderr = (e.stderr or '').strip()
        stdout = (e.stdout or '').strip()
        result = build_result('x', 'x-opencli-article', target_dir, status='error', error=stderr or stdout or str(e))
    except Exception as e:
        result = build_result('x', 'x-opencli-article', target_dir, status='error', error=str(e))

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
