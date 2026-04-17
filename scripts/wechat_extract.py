#!/usr/bin/env python3
"""Extract WeChat article content with Playwright and persist JSON locally."""

import asyncio
import json
import sys
from pathlib import Path

from playwright.async_api import async_playwright

EXTRACT_JS = """
(() => {
    const t = document.querySelector('#activity-name')?.innerText.trim();
    const a = document.querySelector('#js_name')?.innerText.trim();
    const d = document.querySelector('#publish_time')?.innerText.trim();

    function domToMd(node) {
        let r = '';
        for (const c of node.childNodes) {
            if (c.nodeType === 3) { r += c.textContent; }
            else if (c.nodeType === 1) {
                const tag = c.tagName;
                if (tag === 'IMG') {
                    const s = c.getAttribute('data-src') || c.src;
                    if (s && !s.startsWith('data:')) r += '\\n\\n![img](' + s + ')\\n\\n';
                }
                else if (tag === 'BR') { r += '\\n'; }
                else if (tag === 'HR') { r += '\\n\\n---\\n\\n'; }
                else if (tag === 'TABLE') { r += '\\n\\n' + tableToMd(c) + '\\n\\n'; }
                else if (['TR', 'TD', 'TH', 'TBODY', 'THEAD', 'TFOOT'].includes(tag)) { r += domToMd(c); }
                else if (tag === 'A') {
                    const href = c.getAttribute('href');
                    const text = c.textContent.trim();
                    if (href && text) r += '[' + text + '](' + href + ')';
                    else r += domToMd(c);
                }
                else if (tag === 'STRONG' || tag === 'B') { r += '**' + domToMd(c) + '**'; }
                else if (tag === 'EM' || tag === 'I') { r += '*' + domToMd(c) + '*'; }
                else if (tag === 'CODE') { r += '`' + domToMd(c) + '`'; }
                else if (tag === 'PRE') { r += '\\n```\\n' + domToMd(c) + '\\n```\\n'; }
                else if (tag === 'UL') { r += '\\n' + listToMd(c, false) + '\\n'; }
                else if (tag === 'OL') { r += '\\n' + listToMd(c, true) + '\\n'; }
                else {
                    const inner = domToMd(c);
                    if (['P', 'DIV', 'SECTION', 'BLOCKQUOTE'].includes(tag)) r += '\\n' + inner + '\\n';
                    else if (tag.match(/^H[1-6]$/)) r += '\\n' + '#'.repeat(+tag[1]) + ' ' + c.textContent.trim() + '\\n';
                    else r += inner;
                }
            }
        }
        return r;
    }

    function tableToMd(table) {
        let md = '';
        const rows = table.querySelectorAll('tr');
        let isFirstRow = true;
        for (const row of rows) {
            let rowMd = '| ';
            const cells = row.querySelectorAll('td, th');
            for (const cell of cells) {
                let content = cell.textContent.trim().replace(/\\s+/g, ' ');
                rowMd += content + ' | ';
            }
            md += rowMd + '\\n';
            if (isFirstRow && cells.length > 0) {
                let sep = '|';
                for (let i = 0; i < cells.length; i++) sep += ' --- |';
                md += sep + '\\n';
                isFirstRow = false;
            }
        }
        return md.trim();
    }

    function listToMd(list, isOrdered) {
        let md = '';
        let index = 1;
        for (const item of list.children) {
            if (item.tagName === 'LI') {
                const prefix = isOrdered ? (index + '. ') : '- ';
                md += prefix + domToMd(item).trim() + '\\n';
                index++;
            }
        }
        return md.trim();
    }

    const content = document.querySelector('#js_content');
    const body = content ? domToMd(content).replace(/\\n{3,}/g, '\\n\\n').trim() : '';
    const imgs = content ? Array.from(content.querySelectorAll('img')).map((img, i) => ({
        i, src: img.getAttribute('data-src') || img.src, alt: img.alt || ''
    })).filter(x => x.src && !x.src.startsWith('data:')) : [];
    return {title: t, author: a, date: d, body: body, images: imgs};
})()
"""


JSON_DIR = Path('/tmp/wechat_articles')


async def extract_article(url: str, filename: str):
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
            locale='zh-CN',
            viewport={'width': 1440, 'height': 900},
        )
        await context.set_extra_http_headers({
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Upgrade-Insecure-Requests': '1',
        })
        page = await context.new_page()
        try:
            await page.goto(url, wait_until='domcontentloaded', timeout=30000, referer='https://mp.weixin.qq.com/')
            await page.wait_for_selector('#js_content', timeout=10000)
            result = await page.evaluate(EXTRACT_JS)
            await context.close()
            await browser.close()
            if not result or not result.get('title'):
                return None

            data = {
                'filename': filename,
                'url': url,
                'title': result['title'],
                'author': result['author'],
                'date': result['date'],
                'body': result['body'],
                'images': result['images'],
            }
            JSON_DIR.mkdir(parents=True, exist_ok=True)
            json_path = JSON_DIR / f'{filename}.json'
            json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
            return result
        except Exception as exc:
            print(f'wechat_extract error: {type(exc).__name__}: {exc}', file=sys.stderr)
            await context.close()
            await browser.close()
            return None


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print('Usage: python3 wechat_extract.py <url> <filename>')
        sys.exit(1)

    result = asyncio.run(extract_article(sys.argv[1], sys.argv[2]))
    sys.exit(0 if result else 1)
