#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from urllib.parse import urlparse

from baoyu_web_capture import capture_with_baoyu
from common import (
    build_result,
    note_path_for,
    output_settings_for_source,
    render_note_content,
)
from translation_utils import (
    detect_language,
    is_simplified_chinese,
    prompt_translation_choice,
    translate_markdown,
)

BAD_TITLE_EXACT = {
    'sign in', 'log in', 'login', 'subscribe', 'page not found', '404', 'home', 'menu'
}
BAD_TITLE_FRAGMENTS = [
    'don’t miss what’s happening', "don't miss what's happening",
    'sign up', 'log in', 'subscribe', 'cookie', 'javascript',
    '最具影響力的區塊鏈新聞媒體', '最具影响力的区块链新闻媒体'
]
SKIP_PREFIXES = ('URL Source:', 'Published Time:', 'Markdown Content:', 'Warning:')
SITE_SEPARATORS = [' | ', ' - ', '｜', '—', '–', '_']
DEFAULT_TITLE_MODEL = os.environ.get('OPENAI_TITLE_MODEL', 'gpt-5-mini')
DEFUDDLE_TIMEOUT_SECONDS = 90
MARKDOWN_IMAGE_RE = re.compile(r'!\[(?P<alt>[^\]]*)\]\((?P<src>https?://[^)\s]+)\)')
SUBSTACK_FETCH_PREFIX_RE = re.compile(r'(?:,\s*|,%20)https?://[^/]+/p/')


def jina_reader_url(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path or ''
    query = f'?{parsed.query}' if parsed.query else ''
    return f'https://r.jina.ai/http://{host}{path}{query}'


def command_exists(name: str) -> bool:
    for path_dir in os.environ.get('PATH', '').split(os.pathsep):
        if not path_dir:
            continue
        full = os.path.join(path_dir, name)
        if os.path.isfile(full) and os.access(full, os.X_OK):
            return True
    return False


def sanitize_title(text: str) -> str:
    text = re.sub(r'[`*_#>\[\]()]', ' ', text)
    text = re.sub(r'https?://\S+', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    text = re.sub(r'[\\/:*?"<>|]', '', text)
    return text.strip()


def normalize_host(host: str) -> str:
    host = host.lower()
    if host.startswith('www.'):
        host = host[4:]
    return host


def slug_from_url(source_url: str) -> str:
    parsed = urlparse(source_url)
    host = normalize_host(parsed.netloc or 'web')
    parts = [p for p in parsed.path.split('/') if p]
    tail = parts[-1] if parts else 'page'
    tail = re.sub(r'[^a-zA-Z0-9\-]+', '-', tail).strip('-').lower() or 'page'
    host_slug = re.sub(r'[^a-zA-Z0-9\-]+', '-', host).strip('-').lower() or 'web'
    return f'{host_slug}-{tail}'[:80]


def slug_keywords(source_url: str) -> set[str]:
    parsed = urlparse(source_url)
    parts = [p for p in parsed.path.split('/') if p]
    tail = parts[-1] if parts else ''
    words = [w for w in re.split(r'[^a-zA-Z0-9]+', tail.lower()) if len(w) >= 4]
    stop = {'https', 'http', 'html', 'page', 'news', 'blog', 'www', 'com', 'home', 'index', 'docs', 'doc'}
    return {w for w in words if w not in stop}


def clean_site_suffix(title: str, host: str) -> str:
    t = title.strip()
    host_main = normalize_host(host).split('.')[0]
    for sep in SITE_SEPARATORS:
        if sep in t:
            parts = [p.strip() for p in t.split(sep) if p.strip()]
            if len(parts) >= 2:
                last = parts[-1].lower()
                if host_main in last or any(x in last for x in ['blocktempo', 'news', '博客', 'blog', '媒体', '媒體', '官网', 'official']):
                    t = parts[0]
                    break
    return t.strip()


def score_title(title: str, host: str) -> int:
    t = title.strip()
    low = t.lower()
    score = 0
    if 8 <= len(t) <= 40:
        score += 3
    elif 5 <= len(t) <= 60:
        score += 1
    else:
        score -= 2
    if any(ch.isdigit() for ch in t):
        score += 1
    if re.search(r'[A-Za-z\u4e00-\u9fff]', t):
        score += 1
    if t.endswith(('。', '！', '？', '.', '!', '?')):
        score -= 2
    if normalize_host(host).split('.')[0] in low:
        score -= 1
    if any(frag in low for frag in BAD_TITLE_FRAGMENTS):
        score -= 4
    if low in BAD_TITLE_EXACT:
        score -= 5
    return score


def choose_title(candidates: list[str], source_url: str) -> str:
    host = urlparse(source_url).netloc or 'web'
    best_title = ''
    best_score = -999
    for raw in candidates:
        cand = sanitize_title(raw)
        if not cand:
            continue
        if raw.startswith(SKIP_PREFIXES):
            continue
        cand = clean_site_suffix(cand, host)
        low = cand.lower()
        if low in BAD_TITLE_EXACT:
            continue
        if any(frag in low for frag in BAD_TITLE_FRAGMENTS):
            continue
        score = score_title(cand, host)
        if score > best_score:
            best_score = score
            best_title = cand
    if best_title and best_score >= 2:
        kws = slug_keywords(source_url)
        if len(kws) >= 2:
            title_words = set(re.split(r'[^a-zA-Z0-9]+', best_title.lower()))
            if not any(k in title_words for k in kws):
                return slug_from_url(source_url)
        return best_title[:60].strip()
    return slug_from_url(source_url)


def extract_title(body: str, source_url: str) -> tuple[str, list[str], list[str]]:
    lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
    title_candidates = []
    body_candidates = []
    for ln in lines[:20]:
        if ln.startswith('Title:'):
            title_candidates.append(ln.split(':', 1)[1].strip())
    for ln in lines[:30]:
        if ln.startswith(SKIP_PREFIXES):
            continue
        body_candidates.append(ln)

    title_pick = choose_title(title_candidates, source_url)
    if title_pick != slug_from_url(source_url):
        return title_pick, title_candidates, body_candidates
    return choose_title(title_candidates + body_candidates, source_url), title_candidates, body_candidates


def should_use_llm_title(title: str, source_url: str) -> bool:
    low = title.lower().strip()
    slug = slug_from_url(source_url).lower()
    if not title or low == slug:
        return True
    if low in BAD_TITLE_EXACT:
        return True
    if any(frag in low for frag in BAD_TITLE_FRAGMENTS):
        return True
    if re.fullmatch(r'[a-z0-9\-]{8,}', low):
        return True
    if re.fullmatch(r'[a-z0-9\-]+(?:/[a-z0-9\-]+)+', low):
        return True
    return False


def call_openai_title_llm(source_url: str, candidates: list[str], body: str, fallback_title: str) -> str | None:
    api_key = os.environ.get('OPENAI_API_KEY')
    if not api_key:
        return None

    prompt = {
        'source_url': source_url,
        'fallback_title': fallback_title,
        'candidate_titles': [c for c in candidates if c][:8],
        'body_preview': '\n'.join([ln for ln in body.splitlines() if ln.strip()][:80])[:4000],
        'rules': [
            'Return only the best final page title.',
            'Prefer the real document/article/page title over URL slugs or site navigation labels.',
            'Remove site suffixes like brand names when they are not part of the content title.',
            'Keep the original language.',
            'Do not add quotes, markdown, or explanations.',
            'Keep it under 80 characters.',
        ],
    }
    req_body = {
        'model': DEFAULT_TITLE_MODEL,
        'messages': [
            {
                'role': 'system',
                'content': 'You clean webpage titles for an Obsidian web clipper. Output only the final title text.',
            },
            {
                'role': 'user',
                'content': json.dumps(prompt, ensure_ascii=False),
            },
        ],
        'temperature': 0,
        'max_completion_tokens': 80,
    }
    req = urllib.request.Request(
        'https://api.openai.com/v1/chat/completions',
        data=json.dumps(req_body).encode('utf-8'),
        headers={
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
        },
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode('utf-8', errors='replace'))
        content = payload['choices'][0]['message']['content'].strip()
        title = sanitize_title(content).strip(' "\'')
        return title[:80].strip() or None
    except (urllib.error.URLError, urllib.error.HTTPError, KeyError, IndexError, json.JSONDecodeError):
        return None


def refine_title_with_llm(title: str, source_url: str, title_candidates: list[str], body_candidates: list[str], mode: str) -> str:
    if mode == 'off':
        return title
    if mode == 'auto' and not should_use_llm_title(title, source_url):
        return title

    refined = call_openai_title_llm(
        source_url=source_url,
        candidates=title_candidates + body_candidates,
        body='\n'.join(body_candidates),
        fallback_title=title,
    )
    if refined:
        return refined
    if mode == 'on' and not os.environ.get('OPENAI_API_KEY'):
        raise RuntimeError('OPENAI_API_KEY is required when --llm-title=on')
    return title


def fetch_text(url: str) -> str:
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode('utf-8', errors='replace')


def clean_text(value: str | None, limit: int | None = None) -> str | None:
    if value is None:
        return None
    text = re.sub(r'\s+', ' ', str(value)).strip()
    if not text:
        return None
    if limit is not None:
        return text[:limit].strip() or None
    return text


def sanitize_filename_title(text: str) -> str:
    return sanitize_title(text)[:80].strip() or 'web-page'


def normalize_language(value: str | None) -> str | None:
    text = clean_text(value, limit=32)
    if not text:
        return None
    return text


def normalize_image(value: str | None, source_url: str) -> str | None:
    text = clean_text(value, limit=500)
    if not text:
        return None
    if text.startswith(('http://', 'https://')):
        return text
    parsed = urlparse(source_url)
    if text.startswith('/'):
        return f'{parsed.scheme}://{parsed.netloc}{text}'
    return None


def normalize_word_count(value) -> int | None:
    if value is None or value == '':
        return None
    try:
        count = int(value)
    except (TypeError, ValueError):
        return None
    if count < 0:
        return None
    return count


def normalize_published_at(value: str | None) -> str | None:
    text = clean_text(value, limit=80)
    if not text:
        return None
    return text


def infer_ext_from_headers(url: str, headers) -> str:
    content_type = (headers.get_content_type() or '').lower()
    if content_type == 'image/png':
        return 'png'
    if content_type == 'image/gif':
        return 'gif'
    if content_type == 'image/webp':
        return 'webp'
    if content_type == 'image/svg+xml':
        return 'svg'
    if content_type == 'image/avif':
        return 'avif'
    if content_type == 'image/jpeg':
        return 'jpg'
    lower = url.lower()
    if '.png' in lower:
        return 'png'
    if '.gif' in lower:
        return 'gif'
    if '.webp' in lower:
        return 'webp'
    if '.svg' in lower:
        return 'svg'
    if '.avif' in lower:
        return 'avif'
    return 'jpg'


def normalize_media_url(url: str) -> str:
    text = (url or '').strip()
    if not text:
        return text

    # Some Substack image URLs get absolutized into malformed variants like:
    # ..., https://host/p/w_424,...
    # Convert them back to the fetch syntax that Substack CDN accepts.
    if 'substackcdn.com/image/fetch/' in text and '/p/' in text:
        text = SUBSTACK_FETCH_PREFIX_RE.sub(',', text)

    parts = urllib.parse.urlsplit(text)
    if not parts.scheme or not parts.netloc:
        return text
    path = urllib.parse.quote(parts.path, safe='/%:@!$&\'()*+,;=-._~')
    query = urllib.parse.quote(parts.query, safe='=&:%@!$\'()*+,;/-._~')
    fragment = urllib.parse.quote(parts.fragment, safe='=&:%@!$\'()*+,;/-._~')
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, path, query, fragment))


def download_binary(url: str, path: str, *, referer: str | None = None) -> bool:
    headers = {
        'User-Agent': 'Mozilla/5.0',
        'Accept': 'image/avif,image/webp,image/apng,image/*,*/*;q=0.8',
    }
    if referer:
        headers['Referer'] = referer
    try:
        normalized_url = normalize_media_url(url)
        req = urllib.request.Request(normalized_url, headers=headers)
        with urllib.request.urlopen(req, timeout=45) as resp:
            data = resp.read()
            ext = infer_ext_from_headers(normalized_url, resp.headers)
        if not path.endswith(f'.{ext}'):
            root, _ = os.path.splitext(path)
            path = f'{root}.{ext}'
        with open(path, 'wb') as f:
            f.write(data)
        return True
    except Exception:
        return False


def localize_images(body: str, note_basename: str, target_dir: str, *, referer: str) -> tuple[str, str | None, int, int]:
    matches = list(MARKDOWN_IMAGE_RE.finditer(body))
    if not matches:
        return body, None, 0, 0

    asset_dir = os.path.join(target_dir, 'assets', note_basename)
    if os.path.isdir(asset_dir):
        shutil.rmtree(asset_dir)
    os.makedirs(asset_dir, exist_ok=True)

    seen_src_to_rel: dict[str, str] = {}
    ok = 0
    fail = 0

    for index, match in enumerate(matches, start=1):
        src = match.group('src')
        if src in seen_src_to_rel:
            replacement = f'![[{seen_src_to_rel[src]}]]'
            body = body.replace(match.group(0), replacement)
            continue

        stamp = datetime.now().strftime('%Y%m%d%H%M%S') + f'{index:03d}'
        base_path = os.path.join(asset_dir, f'file-{stamp}.jpg')
        if download_binary(src, base_path, referer=referer):
            real_file = max(
                (os.path.join(asset_dir, name) for name in os.listdir(asset_dir) if name.startswith(f'file-{stamp}.')),
                key=os.path.getmtime,
            )
            rel = f'assets/{note_basename}/{os.path.basename(real_file)}'
            seen_src_to_rel[src] = rel
            replacement = f'![[{rel}]]'
            body = body.replace(match.group(0), replacement)
            ok += 1
        else:
            fail += 1
        time.sleep(0.03)

    if ok == 0:
        shutil.rmtree(asset_dir)
        return body, None, 0, fail
    return body, asset_dir, ok, fail


def defuddle_metadata_to_extra(metadata: dict, fetch_url: str) -> dict:
    extra = {
        'author': clean_text(metadata.get('author'), limit=120),
        'published_at': normalize_published_at(metadata.get('published')),
        'description': clean_text(metadata.get('description'), limit=300),
        'site': clean_text(metadata.get('site'), limit=120),
        'language': normalize_language(metadata.get('language')),
        'image': normalize_image(metadata.get('image'), metadata.get('url') or ''),
        'word_count': normalize_word_count(metadata.get('wordCount')),
        'capture_method': 'defuddle',
        'fetch_url': fetch_url,
    }
    return extra


def parse_defuddle(source_url: str) -> dict | None:
    if not command_exists('defuddle'):
        return None
    cp = subprocess.run(
        ['defuddle', 'parse', source_url, '--json', '--md'],
        check=False,
        capture_output=True,
        text=True,
        timeout=DEFUDDLE_TIMEOUT_SECONDS,
    )
    if cp.returncode != 0:
        raise RuntimeError(f'defuddle failed: {cp.stderr.strip() or cp.stdout.strip() or cp.returncode}')
    try:
        payload = json.loads(cp.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f'defuddle returned invalid json: {exc}') from exc
    if not isinstance(payload, dict):
        raise RuntimeError('defuddle returned non-object json')
    return payload


def extract_body_from_defuddle(payload: dict) -> str:
    for key in ('content', 'markdown'):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    raise RuntimeError('defuddle returned empty content')


def extract_title_from_defuddle(payload: dict, source_url: str) -> str:
    primary = clean_text(payload.get('title'), limit=120)
    if primary:
        return sanitize_title(primary)[:80].strip() or slug_from_url(source_url)
    candidates = []
    for key in ('site', 'description'):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            candidates.append(value)
    title = choose_title(candidates, source_url)
    return title if title else slug_from_url(source_url)


def capture_with_defuddle(source_url: str) -> tuple[str, str, dict]:
    payload = parse_defuddle(source_url)
    if payload is None:
        raise FileNotFoundError('defuddle command not found')
    body = extract_body_from_defuddle(payload)
    title = extract_title_from_defuddle(payload, source_url)
    extra = defuddle_metadata_to_extra(payload, source_url)
    return title, body, extra


def capture_with_jina(source_url: str, llm_title_mode: str) -> tuple[str, str, dict]:
    fetch_url = jina_reader_url(source_url)
    body = fetch_text(fetch_url)
    title, title_candidates, body_candidates = extract_title(body, source_url)
    title = refine_title_with_llm(title, source_url, title_candidates, body_candidates, llm_title_mode)
    extra = {
        'capture_method': 'jina-reader',
        'fetch_url': fetch_url,
    }
    return title, body, extra


def capture_with_baoyu_backend(source_url: str, llm_title_mode: str) -> tuple[str, str, dict]:
    payload = capture_with_baoyu(source_url)
    title = sanitize_title(payload['title']).strip() or slug_from_url(source_url)
    if should_use_llm_title(title, source_url):
        title = refine_title_with_llm(title, source_url, [payload['title']], payload['body'].splitlines()[:30], llm_title_mode)
    return title, payload['body'], payload['extra']


def main():
    parser = argparse.ArgumentParser(description='Capture a generic public webpage into Obsidian markdown.')
    parser.add_argument('url')
    parser.add_argument('--llm-title', choices=['auto', 'on', 'off'], default='auto')
    parser.add_argument('--translation-choice', choices=['ask', 'translate', 'original', 'both'], default='ask')
    parser.add_argument('--web-backend', choices=['auto', 'baoyu', 'legacy'], default='auto')
    args = parser.parse_args()

    source_url = args.url.strip()
    parsed = urlparse(source_url)
    if parsed.scheme not in ('http', 'https'):
        print(json.dumps({'status': 'error', 'error': 'only http(s) URLs are supported'}, ensure_ascii=False))
        sys.exit(1)

    fetch_url = jina_reader_url(source_url)
    output = output_settings_for_source('web')
    target_dir = output['target_dir']
    os.makedirs(target_dir, exist_ok=True)

    try:
        capture_method = None
        capture_backend = None
        capture_fallback_reason = None
        title = ''
        body = ''
        extra = {}

        if args.web_backend in {'auto', 'baoyu'}:
            try:
                title, body, extra = capture_with_baoyu_backend(source_url, args.llm_title)
                capture_method = extra.get('capture_method') or 'baoyu-cdp'
                fetch_url = extra.get('fetch_url') or source_url
                capture_backend = extra.get('capture_backend') or 'baoyu-url-to-markdown'
                capture_fallback_reason = extra.get('capture_fallback_reason')
            except Exception as exc:
                if args.web_backend == 'baoyu':
                    raise
                capture_fallback_reason = str(exc)

        if not body:
            try:
                title, body, extra = capture_with_defuddle(source_url)
                capture_method = 'defuddle'
                fetch_url = source_url
                capture_backend = 'public-post-to-obsidian:defuddle'
            except Exception as first_error:
                title, body, extra = capture_with_jina(source_url, args.llm_title)
                capture_method = 'jina-reader'
                fetch_url = extra['fetch_url']
                capture_backend = 'public-post-to-obsidian:jina-reader'
                if capture_fallback_reason is None:
                    capture_fallback_reason = str(first_error)

        date_str = datetime.now().strftime('%Y%m%d')
        basename = f"{date_str}--{sanitize_filename_title(title)}__web"
        body, asset_dir, images_ok, images_fail = localize_images(body, basename, target_dir, referer=source_url)
        base_markdown = (
            f"# {title}\n\n"
            f"原文链接: {source_url}\n"
            f"抓取方式: {capture_method}\n"
            f"抓取链接: {fetch_url}\n"
            f"抓取时间: {datetime.now().isoformat()}\n\n"
            f"---\n\n{body}\n"
        )
        detected_lang = detect_language(base_markdown, extra.get('language'))
        choice = args.translation_choice
        if not is_simplified_chinese(detected_lang) and choice == 'ask':
            choice = prompt_translation_choice('web', detected_lang, title)

        note_path = note_path_for(target_dir, basename, output['file_format'])
        md = render_note_content(
            title=title,
            source_url=source_url,
            source_type='web',
            base_markdown=base_markdown,
            extra={
                **extra,
                'source_language': detected_lang,
                'translated': False,
                'capture_backend': capture_backend,
                'capture_fallback_reason': capture_fallback_reason,
            },
            include_frontmatter=output['include_frontmatter'],
            file_format=output['file_format'],
        )
        with open(note_path, 'w', encoding='utf-8') as f:
            f.write(md)
        translated_note_path = None
        if not is_simplified_chinese(detected_lang) and choice in {'translate', 'both'}:
            translated = translate_markdown(base_markdown, model_label='kimi 2.5')
            zh_title = translated['translated_title'] or f'中文译文 {title}'
            zh_basename = f"{date_str}--{sanitize_filename_title(zh_title)}__web"
            translated_note_path = note_path_for(target_dir, zh_basename, output['file_format'])
            translated_md = render_note_content(
                title=zh_title,
                source_url=source_url,
                source_type='web',
                base_markdown=translated['translated_markdown'],
                extra={
                    **extra,
                    'source_language': detected_lang,
                    'translated': True,
                    'translation_model': translated['model'],
                    'translation_strategy': translated['strategy'],
                    'original_title': title,
                    'capture_backend': capture_backend,
                    'capture_fallback_reason': capture_fallback_reason,
                },
                include_frontmatter=output['include_frontmatter'],
                file_format=output['file_format'],
            )
            with open(translated_note_path, 'w', encoding='utf-8') as f:
                f.write(translated_md)
            if choice == 'translate':
                if os.path.exists(note_path):
                    os.remove(note_path)
                note_path = translated_note_path
        result = build_result(
            'web',
            'baoyu-generic-web' if capture_backend == 'baoyu-url-to-markdown' else ('defuddle-generic-web' if capture_method == 'defuddle' else 'jina-reader-generic-web'),
            target_dir,
            note_path=translated_note_path if choice == 'translate' and translated_note_path else note_path,
            asset_dir=asset_dir,
            fetch_url=fetch_url,
            capture_method=capture_method,
            capture_backend=capture_backend,
            capture_fallback_reason=capture_fallback_reason,
            images_ok=images_ok,
            images_fail=images_fail,
            source_language=detected_lang,
            translation_choice=choice,
            translated_note_path=translated_note_path,
            file_format=output['file_format'],
            storage_mode=output['storage_mode'],
        )
    except Exception as e:
        result = build_result('web', 'generic-web', target_dir, status='error', error=str(e), fetch_url=fetch_url)

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
