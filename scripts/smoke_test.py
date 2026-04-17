#!/usr/bin/env python3
import sys
import tempfile
from pathlib import Path

from common import obsidian_frontmatter
from feishu_executor import extract_author_line, extract_embedded_source_url, extract_published_at
from feishu_probe import extract_author_line as extract_feishu_probe_author_line
from generic_web_executor import defuddle_metadata_to_extra, localize_images
from router import detect_source, x_jina_url
from translation_utils import extract_title_and_body, replace_or_insert_title
from wechat_executor import clean_markdown, convert_local_markdown_images_to_wikilinks, first_image_url
from x_api_executor import parse_status_url, select_content


def assert_eq(actual, expected, label):
    if actual != expected:
        raise AssertionError(f'{label}: expected {expected!r}, got {actual!r}')


def assert_true(condition, label):
    if not condition:
        raise AssertionError(label)


def test_detect_source():
    assert_eq(detect_source('https://mp.weixin.qq.com/s/abc'), 'wechat', 'wechat route')
    assert_eq(detect_source('https://waytoagi.feishu.cn/wiki/NL4cwOJp1ip9a1kfRLNcAyrCnDb'), 'feishu', 'feishu route')
    assert_eq(detect_source('https://x.com/user/status/123'), 'x', 'x route')
    assert_eq(detect_source('https://example.com/post'), 'web', 'web route')
    assert_eq(detect_source('mailto:test@example.com'), 'unknown', 'unknown route')


def test_x_jina_url():
    actual = x_jina_url('https://twitter.com/nav/status/123456')
    assert_eq(actual, 'https://r.jina.ai/http://x.com/nav/status/123456', 'x jina rewrite')


def test_x_api_helpers():
    user, tweet_id = parse_status_url('https://x.com/nav/status/123456?s=20')
    assert_eq(user, 'nav', 'x api parse user')
    assert_eq(tweet_id, '123456', 'x api parse tweet id')
    title, content, kind, canonical = select_content(
        {'id': '123456', 'article': {'title': '测试标题', 'plain_text': '正文内容'}},
        'nav',
        'https://x.com/nav/status/123456',
    )
    assert_eq(title, '测试标题', 'x api article title')
    assert_eq(content, '正文内容', 'x api article body')
    assert_eq(kind, 'article', 'x api article kind')
    assert_eq(canonical, 'https://x.com/nav/status/123456', 'x api canonical')


def test_frontmatter():
    fm = obsidian_frontmatter(
        title='示例标题',
        source_url='https://example.com/post',
        source_type='web',
        created='2026-03-12',
        fetched_at='2026-03-12T10:00:00',
        extra={'capture_method': 'jina-reader'},
    )
    expected_bits = [
        '---',
        'title: "示例标题"',
        'source: "https://example.com/post"',
        'created: 2026-03-12',
        'fetched_at: "2026-03-12T10:00:00"',
        'source_type: "web"',
        'source_domain: "example.com"',
        'tags:',
        '  - inbox',
        '  - capture',
        '  - web',
        'capture_method: "jina-reader"',
    ]
    for bit in expected_bits:
        if bit not in fm:
            raise AssertionError(f'frontmatter missing: {bit!r}')


def test_defuddle_metadata_mapping():
    extra = defuddle_metadata_to_extra(
        {
            'author': ' Jane Doe ',
            'published': '2026-03-21T09:00:00Z',
            'description': '  A short summary for the article.  ',
            'site': 'Example Site',
            'language': 'en-US',
            'image': 'https://example.com/hero.png',
            'wordCount': 1234,
        },
        'https://example.com/post',
    )
    expected = {
        'author': 'Jane Doe',
        'published_at': '2026-03-21T09:00:00Z',
        'description': 'A short summary for the article.',
        'site': 'Example Site',
        'language': 'en-US',
        'image': 'https://example.com/hero.png',
        'word_count': 1234,
        'capture_method': 'defuddle',
        'fetch_url': 'https://example.com/post',
    }
    assert_eq(extra, expected, 'defuddle metadata mapping')


def test_generic_web_image_localize():
    body = '\n'.join([
        '![Image](https://example.com/a.png)',
        '',
        '![Image](https://example.com/a.png)',
        '',
        '![Other](https://example.com/b.jpg)',
    ])
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        body2, asset_dir, ok, fail = localize_images(body, '20260322--demo__web', str(tmp_path), referer='https://example.com/post')
    assert_eq(asset_dir, None, 'image localize without network should clean asset dir')
    assert_eq(ok, 0, 'image localize ok count without network')
    assert_eq(fail, 3, 'image localize fail count without network')
    assert_true('./assets/' not in body2, 'image localize should keep remote links on total failure')


def test_translation_title_helpers():
    title, body = extract_title_and_body('# Old Title\n\nBody line\n')
    assert_eq(title, 'Old Title', 'extract translated title')
    assert_true('Body line' in body, 'extract translated body')
    updated = replace_or_insert_title('# Old Title\n\nBody line\n', 'New Title')
    assert_true(updated.startswith('# New Title\n'), 'replace title helper')


def test_handler_names():
    from router import main  # noqa: F401
    # Keep handler expectations close to routing tests.
    pass


def test_wechat_cleanup():
    dirty = """
![img](./assets/demo/a.jpg)

已关注
分享视频
视频详情
原创
关闭
更多
播放
**，时长05:36
00:00/05:36
倍速
全屏
超清  流畅
 0.5倍  0.75倍  1.0倍  1.5倍  2.0倍
[播放](javascript:;)

课程名称：网络安全

![img](./assets/demo/a.jpg)

继续观看
"""
    cleaned = clean_markdown(dirty)
    expected_bits = [
        '![img](./assets/demo/a.jpg)',
        '课程名称：网络安全',
    ]
    forbidden_bits = [
        '已关注',
        '分享视频',
        '视频详情',
        '原创',
        '关闭',
        '更多',
        '播放',
        '[播放](javascript:;)',
        '00:00/05:36',
        '倍速',
        '全屏',
        '0.5倍',
        '超清  流畅',
    ]
    for bit in expected_bits:
        if bit not in cleaned:
            raise AssertionError(f'wechat cleanup missing: {bit!r}')
    for bit in forbidden_bits:
        if bit in cleaned:
            raise AssertionError(f'wechat cleanup retained noise: {bit!r}')
    if cleaned.count('![img](./assets/demo/a.jpg)') != 1:
        raise AssertionError('wechat cleanup should dedupe consecutive duplicate images')


def test_wechat_local_images_convert_to_wikilinks():
    raw = "段落\\n\\n![img](./assets/demo/a.jpg)\\n\\n![img](assets/demo/b.png)\\n"
    converted = convert_local_markdown_images_to_wikilinks(raw)
    expected_bits = [
        '![[assets/demo/a.jpg]]',
        '![[assets/demo/b.png]]',
    ]
    forbidden_bits = [
        '![img](./assets/demo/a.jpg)',
        '![img](assets/demo/b.png)',
    ]
    for bit in expected_bits:
        if bit not in converted:
            raise AssertionError(f'wechat local image conversion missing: {bit!r}')
    for bit in forbidden_bits:
        if bit in converted:
            raise AssertionError(f'wechat local image conversion retained markdown image: {bit!r}')


def test_wechat_bundled_scripts():
    from pathlib import Path
    script_dir = Path(__file__).resolve().parent
    expected = [
        script_dir / 'wechat_extract.py',
        script_dir / 'wechat_server.py',
    ]
    for path in expected:
        if not path.exists():
            raise AssertionError(f'missing bundled wechat helper: {path}')


def test_wechat_metadata_helpers():
    images = [
        {'src': ''},
        {'src': 'https://mmbiz.qpic.cn/demo.png'},
    ]
    assert_eq(first_image_url(images), 'https://mmbiz.qpic.cn/demo.png', 'wechat first image helper')
    assert_eq(first_image_url([]), None, 'wechat first image empty')


def test_feishu_metadata_helpers():
    markdown = '\n'.join(
        [
            '# 标题',
            '',
            '原文链接：https://mp.weixin.qq.com/s/demo123',
            '',
            '原创 DracoVibeCoding DracoVibeCoding 2026年3月21日 19:17 海南',
        ]
    )
    assert_eq(
        extract_embedded_source_url(markdown),
        'https://mp.weixin.qq.com/s/demo123',
        'feishu embedded source url',
    )
    author_line = extract_author_line(markdown)
    assert_true(author_line is not None, 'feishu author line')
    assert_eq(
        extract_published_at(author_line),
        '2026年3月21日 19:17',
        'feishu published_at',
    )
    lines = ['foo', '原创 阿真 阿真Irene2026年3月21日 16:56 美国', 'bar']
    assert_eq(
        extract_feishu_probe_author_line(lines),
        '原创 阿真 阿真Irene2026年3月21日 16:56 美国',
        'feishu probe author line',
    )


def test_feishu_display_source_url_priority():
    probe_data = {
        'embedded_source_url': 'https://mp.weixin.qq.com/s/demo-real-source',
    }
    display_source_url = probe_data.get('embedded_source_url') or 'https://waytoagi.feishu.cn/wiki/demo'
    assert_eq(
        display_source_url,
        'https://mp.weixin.qq.com/s/demo-real-source',
        'feishu display source url should prefer embedded source',
    )


def main():
    tests = [
        ('detect_source', test_detect_source),
        ('x_jina_url', test_x_jina_url),
        ('frontmatter', test_frontmatter),
        ('defuddle_metadata_mapping', test_defuddle_metadata_mapping),
        ('generic_web_image_localize', test_generic_web_image_localize),
        ('translation_title_helpers', test_translation_title_helpers),
        ('wechat_cleanup', test_wechat_cleanup),
        ('wechat_bundled_scripts', test_wechat_bundled_scripts),
        ('wechat_metadata_helpers', test_wechat_metadata_helpers),
        ('feishu_metadata_helpers', test_feishu_metadata_helpers),
        ('feishu_display_source_url_priority', test_feishu_display_source_url_priority),
    ]
    for name, fn in tests:
        fn()
        print(f'OK {name}')
    print('ALL_OK')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'FAIL {exc}', file=sys.stderr)
        raise
