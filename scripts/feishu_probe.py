#!/usr/bin/env python3
from __future__ import annotations
import asyncio
import json
import sys
from datetime import datetime, timezone
from urllib.parse import urlparse

from playwright.async_api import async_playwright


def extract_author_line(lines: list[str]) -> str | None:
    for line in lines:
        if '原创' in line and '年' in line and '月' in line and '日' in line:
            return line.strip()
    return None


def unix_to_iso8601(value) -> str | None:
    if value in (None, ''):
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc).isoformat()
    except Exception:
        return None


async def probe_page(url: str) -> dict:
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
            locale='zh-CN',
            viewport={'width': 1440, 'height': 900},
        )
        page = await context.new_page()
        try:
            await page.goto(url, wait_until='domcontentloaded', timeout=30000)
            node = None
            for _ in range(10):
                node = await page.evaluate(
                    """async () => {
                        const reqs = performance.getEntriesByType('resource').map(r => r.name);
                        const nodeUrl = reqs.find(u => u.includes('/space/api/wiki/v2/tree/get_node/?wiki_token='));
                        if (!nodeUrl) return null;
                        const res = await fetch(nodeUrl, { credentials: 'include' });
                        if (!res.ok) return null;
                        const json = await res.json();
                        return json?.data || null;
                    }"""
                )
                if node:
                    break
                await page.wait_for_timeout(500)

            if not node:
                raise RuntimeError('Failed to detect Feishu runtime metadata from public page')

            body_text = await page.locator('body').inner_text()
            lines = [line.strip() for line in body_text.splitlines() if line.strip()]
            source_links = await page.locator('a[href^="http"]').evaluate_all(
                """nodes => nodes
                    .map(a => ({text: (a.textContent || '').trim(), href: a.href}))
                    .filter(item => item.href && item.href.startsWith('http'))
                """
            )

            cookies = await context.cookies(url)
            cookie_header = '; '.join(
                f"{cookie['name']}={cookie['value']}"
                for cookie in cookies
                if cookie.get('value')
            )

            embedded_source_url = None
            page_host = urlparse(url).netloc.lower()
            preferred_links = []
            for item in source_links:
                href = item.get('href') or ''
                text = item.get('text') or ''
                host = urlparse(href).netloc.lower()
                if 'mp.weixin.qq.com' in href:
                    preferred_links.append((0, href))
                elif '原文链接' in text and host and host != page_host:
                    preferred_links.append((1, href))
                elif host and host != page_host:
                    preferred_links.append((2, href))
            if preferred_links:
                preferred_links.sort(key=lambda item: item[0])
                embedded_source_url = preferred_links[0][1]

            detail_info = node.get('detail_info') or {}

            result = {
                'url': url,
                'title': node.get('title') or '',
                'page_id': node.get('obj_token') or '',
                'space_id': node.get('space_id') or '',
                'container_id': node.get('wiki_token') or urlparse(url).path.rstrip('/').split('/')[-1],
                'cookie_header': cookie_header,
                'embedded_source_url': embedded_source_url,
                'author_line': extract_author_line(lines),
                'source_created_at': unix_to_iso8601(detail_info.get('create_time')),
                'source_updated_at': unix_to_iso8601(detail_info.get('edit_time')),
                'node': {
                    'obj_type': node.get('obj_type'),
                    'url': node.get('url'),
                    'detail_info': detail_info,
                },
            }
            return result
        finally:
            await context.close()
            await browser.close()


def main():
    if len(sys.argv) != 2:
        print('Usage: python3 feishu_probe.py <public_feishu_url>', file=sys.stderr)
        sys.exit(1)

    result = asyncio.run(probe_page(sys.argv[1]))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
