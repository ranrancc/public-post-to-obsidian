#!/usr/bin/env python3
from __future__ import annotations
import re
import subprocess
import tempfile
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
BAOYU_SKILL_DIR = SCRIPT_DIR.parent / 'vendor' / 'baoyu-url-to-markdown'
BAOYU_MAIN = BAOYU_SKILL_DIR / 'scripts' / 'main.ts'

SAVED_RE = re.compile(r'^Saved:\s+(?P<path>.+)$', re.MULTILINE)
SAVED_HTML_RE = re.compile(r'^Saved HTML:\s+(?P<path>.+)$', re.MULTILINE)
CONVERTER_RE = re.compile(r'^Converter:\s+(?P<value>.+)$', re.MULTILINE)
FALLBACK_RE = re.compile(r'^Fallback used:\s+(?P<value>.+)$', re.MULTILINE)
SITE_SUFFIX_RE = re.compile(r'\s+[-|｜—–•]+\s+')
NOISY_AUTHOR_RE = re.compile(r'(?:\breply\b|^\d{4}-\d{2}-\d{2}\b|\n|\\n)', re.IGNORECASE)
NOISY_DESCRIPTION_RE = re.compile(r'(?:\\n|\n|\breply\b)', re.IGNORECASE)


def _detect_bun_command() -> list[str]:
    for cmd in (['bun'], ['npx', '-y', 'bun']):
        try:
            cp = subprocess.run(cmd + ['--version'], capture_output=True, text=True, timeout=15, check=False)
        except (OSError, subprocess.SubprocessError):
            continue
        if cp.returncode == 0:
            return cmd
    raise RuntimeError('bun runtime not found; install bun or make npx available')


def _extract_frontmatter(markdown: str) -> tuple[dict[str, str], str]:
    normalized = markdown.replace('\r\n', '\n')
    if not normalized.startswith('---\n'):
        return {}, normalized

    parts = normalized.split('\n---\n', 1)
    if len(parts) != 2:
        return {}, normalized

    raw_yaml = parts[0][4:]
    body = parts[1]
    meta: dict[str, str] = {}
    for line in raw_yaml.splitlines():
        if ':' not in line:
            continue
        key, value = line.split(':', 1)
        key = key.strip()
        value = value.strip()
        if not key or not value:
            continue
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1].replace('\\"', '"').replace('\\\\', '\\')
        meta[key] = value
    return meta, body.lstrip('\n')


def _extract_output_paths(stdout: str, temp_dir: str) -> tuple[Path, Path | None]:
    markdown_match = SAVED_RE.search(stdout)
    html_match = SAVED_HTML_RE.search(stdout)

    markdown_path = Path(markdown_match.group('path').strip()) if markdown_match else None
    html_path = Path(html_match.group('path').strip()) if html_match else None

    if markdown_path is None or not markdown_path.exists():
        candidates = sorted(Path(temp_dir).rglob('*.md'))
        if not candidates:
            raise RuntimeError('baoyu capture did not produce a markdown file')
        markdown_path = candidates[0]

    if html_path is not None and (not html_path.exists() or 'unavailable' in str(html_path).lower()):
        html_path = None

    return markdown_path, html_path


def _normalize_capture_method(stdout: str) -> tuple[str, str | None]:
    converter = CONVERTER_RE.search(stdout)
    fallback = FALLBACK_RE.search(stdout)
    method = converter.group('value').strip() if converter else 'unknown'
    reason = fallback.group('value').strip() if fallback else None
    return f'baoyu-cdp:{method}', reason


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = re.sub(r'\s+', ' ', value.replace('\\n', ' ')).strip()
    return text or None


def _extract_primary_heading(markdown_body: str) -> str | None:
    for line in markdown_body.splitlines():
        stripped = line.strip()
        if stripped.startswith('# '):
            title = stripped[2:].strip()
            return title or None
        if stripped.startswith('## '):
            title = stripped[3:].strip()
            return title or None
    return None


def _should_replace_title(current_title: str, heading_title: str) -> bool:
    if not current_title or not heading_title:
        return False
    if current_title == heading_title:
        return False
    if heading_title in current_title and SITE_SUFFIX_RE.search(current_title):
        return True
    return False


def _clean_author(value: str | None) -> str | None:
    text = _clean_text(value)
    if not text:
        return None
    if NOISY_AUTHOR_RE.search(value or ''):
        return None
    if len(text) > 40:
        return None
    return text


def _clean_description(value: str | None) -> str | None:
    text = _clean_text(value)
    if not text:
        return None
    if NOISY_DESCRIPTION_RE.search(value or '') and len(text) > 120:
        return None
    return text[:300]


def _normalize_metadata(metadata: dict[str, str], markdown_body: str) -> dict[str, str | None]:
    heading_title = _extract_primary_heading(markdown_body)
    title = _clean_text(metadata.get('title')) or ''
    if heading_title and _should_replace_title(title, heading_title):
        title = heading_title
    return {
        'title': title,
        'author': _clean_author(metadata.get('author')),
        'published': _clean_text(metadata.get('published')),
        'description': _clean_description(metadata.get('description')),
        'language': _clean_text(metadata.get('language')),
        'coverImage': _clean_text(metadata.get('coverImage')),
    }


def capture_with_baoyu(source_url: str) -> dict:
    if not BAOYU_MAIN.exists():
        raise RuntimeError(f'baoyu main.ts not found: {BAOYU_MAIN}')

    bun_cmd = _detect_bun_command()

    with tempfile.TemporaryDirectory(prefix='public-web-baoyu-') as temp_dir:
        cmd = bun_cmd + [str(BAOYU_MAIN), source_url, '--output-dir', temp_dir]
        cp = subprocess.run(
            cmd,
            cwd=str(BAOYU_SKILL_DIR),
            capture_output=True,
            text=True,
            timeout=240,
            check=False,
        )
        combined_output = '\n'.join(part for part in [cp.stdout, cp.stderr] if part).strip()

        if cp.returncode != 0:
            raise RuntimeError(combined_output or f'baoyu capture failed with exit code {cp.returncode}')

        markdown_path, html_path = _extract_output_paths(cp.stdout or '', temp_dir)
        raw_markdown = markdown_path.read_text(encoding='utf-8')
        metadata, markdown_body = _extract_frontmatter(raw_markdown)
        metadata = _normalize_metadata(metadata, markdown_body)
        capture_method, fallback_reason = _normalize_capture_method(combined_output)

        title = (metadata.get('title') or '').strip()
        if not title:
            title = markdown_path.stem

        return {
            'title': title,
            'body': markdown_body.strip(),
            'extra': {
                'author': metadata.get('author'),
                'published_at': metadata.get('published'),
                'description': metadata.get('description'),
                'language': metadata.get('language'),
                'image': metadata.get('coverImage'),
                'capture_method': capture_method,
                'fetch_url': source_url,
                'capture_backend': 'baoyu-url-to-markdown',
                'capture_fallback_reason': fallback_reason,
            },
            'html_snapshot_path': str(html_path) if html_path and html_path.exists() else None,
            'stdout': combined_output,
        }
