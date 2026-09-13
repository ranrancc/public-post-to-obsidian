#!/usr/bin/env python3
from __future__ import annotations
import json
import os
import re
import urllib.request
import urllib.error

SIMPLIFIED_HINTS = set('这来为们个国时后发说对开现过动还进点样应于与术体龙门书画气')
TRADITIONAL_HINTS = set('這來為們個國時後發說對開現過動還進點樣應於與術體龍門書畫氣')
CHINESE_RE = re.compile(r'[\u4e00-\u9fff]')


def strip_frontmatter(text: str) -> str:
    if text.startswith('---\n'):
        parts = text.split('\n---\n', 1)
        if len(parts) == 2:
            return parts[1]
    return text


def extract_title_and_body(markdown: str) -> tuple[str, str]:
    title = ''
    body_lines = []
    for line in strip_frontmatter(markdown).splitlines():
        stripped = line.strip()
        if not title and stripped.startswith('# '):
            title = stripped[2:].strip()
            continue
        body_lines.append(line)
    return title, '\n'.join(body_lines).strip()


def replace_or_insert_title(markdown: str, title: str) -> str:
    lines = markdown.splitlines()
    for idx, line in enumerate(lines):
        if line.strip().startswith('# '):
            lines[idx] = f'# {title}'
            return '\n'.join(lines).rstrip() + '\n'
    return f'# {title}\n\n{markdown.rstrip()}\n'


def estimate_length(text: str) -> int:
    if not text:
        return 0
    chinese = len(CHINESE_RE.findall(text))
    others = len(re.findall(r'[A-Za-z0-9]+', text))
    return chinese + others


def detect_language(text: str, declared_language: str | None = None) -> str:
    lang = (declared_language or '').lower().strip()
    if lang.startswith('zh-cn') or lang.startswith('zh-hans'):
        return 'zh-Hans'
    if lang.startswith(('zh-tw', 'zh-hk', 'zh-mo', 'zh-hant')):
        return 'zh-Hant'
    if lang.startswith('en'):
        return 'en'

    chinese_chars = CHINESE_RE.findall(text)
    if chinese_chars:
        simp = sum(ch in SIMPLIFIED_HINTS for ch in chinese_chars)
        trad = sum(ch in TRADITIONAL_HINTS for ch in chinese_chars)
        if trad > simp * 1.2 and trad >= 3:
            return 'zh-Hant'
        if simp >= trad:
            return 'zh-Hans'
    latin = re.findall(r'[A-Za-z]', text)
    if latin and len(latin) > max(20, len(chinese_chars) * 2):
        return 'en'
    return 'unknown'


def is_simplified_chinese(lang: str) -> bool:
    return lang == 'zh-Hans'


def choose_translation_strategy(length_hint: int) -> str:
    if length_hint <= 8000:
        return 'single'
    if length_hint <= 20000:
        return 'chunked'
    return 'chunked_merge'


def split_text_for_translation(text: str, target_size: int = 6000, overlap: int = 400) -> list[str]:
    lines = text.splitlines()
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in lines:
        line_len = max(1, estimate_length(line))
        if current and current_len + line_len > target_size:
            chunks.append('\n'.join(current).strip())
            tail = '\n'.join(current)[-overlap:] if overlap > 0 else ''
            current = [tail, line] if tail else [line]
            current_len = estimate_length('\n'.join(current))
        else:
            current.append(line)
            current_len += line_len
    if current:
        chunks.append('\n'.join(current).strip())
    return [chunk for chunk in chunks if chunk.strip()]


# ── Translation API ──────────────────────────────────────────────────

PROVIDERS = {
    'deepseek': {
        'base_url': 'https://api.deepseek.com/v1',
        'api_key_env': 'DEEPSEEK_API_KEY',
    },
    'openrouter': {
        'base_url': 'https://openrouter.ai/api/v1',
        'api_key_env': 'OPENROUTER_API_KEY',
    },
    'openai': {
        'base_url': 'https://api.openai.com/v1',
        'api_key_env': 'OPENAI_API_KEY',
    },
}

DEFAULT_TRANSLATION_MODEL = 'deepseek:deepseek-v4-flash'


def _parse_model(model_spec: str) -> tuple[str, str, str, str]:
    """Parse 'provider:model' into (provider, model, base_url, api_key)."""
    if ':' in model_spec:
        provider, model = model_spec.split(':', 1)
    else:
        provider, model = 'deepseek', model_spec

    cfg = PROVIDERS.get(provider)
    if not cfg:
        raise ValueError(
            f'Unknown translation provider: {provider}. '
            f'Supported: {", ".join(PROVIDERS)}'
        )

    api_key = os.environ.get(cfg['api_key_env'], '').strip()
    if not api_key:
        raise RuntimeError(
            f'API key not found: env var {cfg["api_key_env"]} is not set. '
            f'Set it or use a different provider via TRANSLATION_MODEL.'
        )

    return provider, model, cfg['base_url'], api_key


def _api_chat(base_url: str, api_key: str, model: str, messages: list[dict]) -> str:
    """Single call to OpenAI-compatible /v1/chat/completions."""
    url = f'{base_url.rstrip("/")}/chat/completions'
    body = json.dumps({
        'model': model,
        'messages': messages,
        'temperature': 0.3,
        'max_tokens': 4096,
    }).encode('utf-8')

    req = urllib.request.Request(url, data=body, method='POST')
    req.add_header('Content-Type', 'application/json')
    req.add_header('Authorization', f'Bearer {api_key}')

    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            data = json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        raise RuntimeError(f'Translation API error {e.code}: {body[:500]}')
    except Exception as e:
        raise RuntimeError(f'Translation API request failed: {e}')

    choice = data.get('choices', [{}])[0]
    content = choice.get('message', {}).get('content', '')
    if choice.get('finish_reason') == 'length':
        raise RuntimeError(
            'Translation output truncated at max_tokens; '
            'split the document into smaller chunks.'
        )
    if not content:
        raise RuntimeError(f'Empty response from translation API: {json.dumps(data)[:300]}')
    return content


def _resolve_model_label() -> str:
    """Resolve translation model from env, with default fallback."""
    return os.environ.get('TRANSLATION_MODEL', DEFAULT_TRANSLATION_MODEL).strip()


def _translate_via_api(prompt: str, model_spec: str | None = None) -> str:
    """Translate via OpenAI-compatible API. Raises RuntimeError on failure."""
    spec = model_spec or _resolve_model_label()
    provider, model, base_url, api_key = _parse_model(spec)
    return _api_chat(base_url, api_key, model, [
        {'role': 'user', 'content': prompt},
    ])


def translate_chunk(text: str, *, model_label: str | None = None) -> str:
    prompt = (
        '请将下面的内容完整翻译为自然、准确、通顺的简体中文。\n'
        '要求：\n'
        '1. 保留 Markdown 结构、标题层级、列表、链接和图片链接不变。\n'
        '2. 只翻译自然语言内容，不要解释，不要摘要，不要补充。\n'
        '3. 如果原文中有术语，优先使用自然的中文说法，必要时保留英文原词。\n'
        f'4. 当前翻译通道：{model_label or _resolve_model_label()}。\n\n'
        f'{text}'
    )
    return _translate_via_api(prompt, model_label)


def translate_title(title: str, *, model_label: str | None = None) -> str:
    prompt = (
        '请把下面这个标题翻译成自然、准确、可做文章标题的简体中文。\n'
        '只输出标题，不要加引号，不要解释。\n'
        f'当前翻译通道：{model_label or _resolve_model_label()}\n\n{title}'
    )
    return _translate_via_api(prompt, model_label).strip()


def translate_markdown(markdown: str, *, model_label: str | None = None) -> dict:
    """Translate full markdown document. Returns dict with translated_markdown, etc."""
    spec = model_label or _resolve_model_label()

    try:
        original_title, body = extract_title_and_body(markdown)
        length_hint = estimate_length(body or markdown)
        strategy = choose_translation_strategy(length_hint)

        if strategy == 'single':
            translated_body = translate_chunk(markdown, model_label=spec)
        else:
            chunks = split_text_for_translation(markdown)
            translated_parts = [
                translate_chunk(chunk, model_label=spec)
                for chunk in chunks
            ]
            translated_body = '\n\n'.join(part.strip() for part in translated_parts if part.strip())

        translated_title, _ = extract_title_and_body(translated_body)
        if original_title and not translated_title:
            translated_title = translate_title(original_title, model_label=spec)
            translated_body = replace_or_insert_title(translated_body, translated_title)

        return {
            'translated_markdown': translated_body,
            'translated_title': translated_title,
            'strategy': strategy,
            'length_hint': length_hint,
            'model': spec,
        }
    except Exception as e:
        raise RuntimeError(f'Translation failed ({spec}): {e}') from e


def prompt_translation_choice(source_type: str, lang: str, title: str) -> str:
    print(
        json.dumps(
            {
                'status': 'needs_input',
                'source_type': source_type,
                'language': lang,
                'title': title,
                'message': '检测到抓取内容不是简体中文，请选择后续操作：1=翻译 2=保存原文 3=原文和翻译（两篇）',
                'options': {
                    '1': 'translate',
                    '2': 'original',
                    '3': 'both',
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    while True:
        choice = input('请输入 1 / 2 / 3: ').strip()
        if choice in {'1', '2', '3'}:
            return {'1': 'translate', '2': 'original', '3': 'both'}[choice]
        print('无效输入，请输入 1 / 2 / 3。')
