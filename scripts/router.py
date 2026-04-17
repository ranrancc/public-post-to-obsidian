#!/usr/bin/env python3
import json
import sys
from urllib.parse import urlparse

from common import build_result, target_dir_for_source


def detect_source(url: str) -> str:
    u = url.lower()
    parsed = urlparse(url)
    if any(x in u for x in ['meeting.tencent.com/crm/', 'meeting.tencent.com/cw/']):
        return 'tencent_meeting'
    if 'mp.weixin.qq.com' in u:
        return 'wechat'
    if any(x in u for x in ['feishu.cn/wiki', 'feishu.cn/docx', 'larksuite.com/wiki', 'larksuite.com/docx']):
        return 'feishu'
    if any(x in u for x in ['x.com/', 'twitter.com/']):
        return 'x'
    if parsed.scheme in ('http', 'https') and parsed.netloc:
        return 'web'
    return 'unknown'


def x_jina_url(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if host.endswith('twitter.com'):
        host = host.replace('twitter.com', 'x.com')
    path = parsed.path or ''
    query = f'?{parsed.query}' if parsed.query else ''
    return f'https://r.jina.ai/http://{host}{path}{query}'


def main():
    if len(sys.argv) != 2:
        print(json.dumps({'status': 'error', 'error': 'usage: router.py <url>'}, ensure_ascii=False))
        sys.exit(1)

    url = sys.argv[1].strip()
    source = detect_source(url)

    if source == 'x':
        use_opencli = any(x in url.lower() for x in ['/status/', '/article/'])
        result = build_result(
            'x',
            'x_api_executor.py' if use_opencli else 'x_executor.py',
            target_dir_for_source('x', interactive=False),
            fetch_url=x_jina_url(url),
            notes='Prefer x_api_executor.py for X long-form/status URLs when X_BEARER_TOKEN is available; fall back to opencli twitter article, then r.jina.ai for legacy cases.',
        )
    elif source == 'wechat':
        result = build_result(
            'wechat',
            'wechat_executor.py',
            target_dir_for_source('wechat', interactive=False),
            notes='Use the bundled wechat_executor.py so output follows current Obsidian directory and __weixin naming rules.',
        )
    elif source == 'tencent_meeting':
        result = build_result(
            'tencent_meeting',
            'tencent_meeting_executor.py',
            target_dir_for_source('tencent_meeting', interactive=False),
            notes='Use the bundled tencent_meeting_executor.py wrapper to extract transcript Markdown from the Tencent Meeting replay page and optionally download the replay video.',
        )
    elif source == 'feishu':
        result = build_result(
            'feishu',
            'feishu_executor.py',
            target_dir_for_source('feishu', interactive=False),
            notes=(
                'Use the bundled feishu_executor.py wrapper around the stable exporter. '
                'Use client_vars pagination, continue with data.cursor when '
                'has_more=true but next_cursors is empty, decrypt images via '
                'secret+nonce, and treat meta.json as optional.'
            ),
        )
    elif source == 'web':
        result = build_result(
            'web',
            'generic_web_executor.py',
            target_dir_for_source('web', interactive=False),
            fetch_url=x_jina_url(url),
            notes='Use generic_web_executor.py with baoyu-url-to-markdown as the preferred backend for generic public web pages; keep the existing defuddle/Jina chain as fallback.',
        )
    else:
        result = build_result('unknown', None, None, status='error', error='unsupported URL for public-post-to-obsidian')

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
