#!/usr/bin/env python3
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from common import build_result

SCRIPT_DIR = Path(__file__).resolve().parent
ROUTER = SCRIPT_DIR / 'router.py'
RUNNER = SCRIPT_DIR / 'run_public_capture.py'


def assert_true(condition, label):
    if not condition:
        raise AssertionError(label)


def assert_eq(actual, expected, label):
    if actual != expected:
        raise AssertionError(f'{label}: expected {expected!r}, got {actual!r}')


def router_result(url: str) -> dict:
    cp = subprocess.run(
        [sys.executable, str(ROUTER), url],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(cp.stdout)


def runner_dry_run(url: str, extra: list[str] | None = None) -> dict:
    cmd = [sys.executable, str(RUNNER), '--dry-run']
    if extra:
        cmd.extend(extra)
    cmd.append(url)
    cp = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(cp.stdout)


def test_router_contracts():
    cases = [
        (
            'https://x.com/nav/status/123',
            {
                'source_type': 'x',
                'handler_used': 'x_api_executor.py',
                'target_suffix': '/00-Inbox/X',
                'status': 'ready',
                'fetch_url': 'https://r.jina.ai/http://x.com/nav/status/123',
            },
        ),
        (
            'https://mp.weixin.qq.com/s/abc',
            {
                'source_type': 'wechat',
                'handler_used': 'wechat_executor.py',
                'target_suffix': '/00-Inbox/微信剪藏',
                'status': 'ready',
            },
        ),
        (
            'https://waytoagi.feishu.cn/wiki/NL4cwOJp1ip9a1kfRLNcAyrCnDb',
            {
                'source_type': 'feishu',
                'handler_used': 'feishu_executor.py',
                'target_suffix': '/00-Inbox/飞书',
                'status': 'ready',
            },
        ),
        (
            'https://example.com/post',
            {
                'source_type': 'web',
                'handler_used': 'generic_web_executor.py',
                'target_suffix': '/00-Inbox/网页剪藏',
                'status': 'ready',
                'fetch_url': 'https://r.jina.ai/http://example.com/post',
            },
        ),
    ]

    for url, expected in cases:
        result = router_result(url)
        assert_eq(result['source_type'], expected['source_type'], f'route {url} source_type')
        assert_eq(result['handler_used'], expected['handler_used'], f'route {url} handler')
        assert_eq(result['status'], expected['status'], f'route {url} status')
        assert_true(
            (result.get('target_dir') or '').endswith(expected['target_suffix']),
            f'route {url} target_dir suffix mismatch: {result.get("target_dir")!r}',
        )
        if 'fetch_url' in expected:
            assert_eq(result.get('fetch_url'), expected['fetch_url'], f'route {url} fetch_url')
        assert_eq(result.get('asset_count'), 0, f'route {url} asset_count')
        assert_eq(result.get('error'), None, f'route {url} error')

    feishu = router_result('https://waytoagi.feishu.cn/wiki/NL4cwOJp1ip9a1kfRLNcAyrCnDb')
    notes = feishu.get('notes') or ''
    assert_true('data.cursor' in notes, 'feishu router notes should mention data.cursor fallback')
    assert_true('meta.json as optional' in notes, 'feishu router notes should mention optional meta.json')


def test_validate_result_success_and_assets():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        note = tmp_path / 'ok.md'
        assets = tmp_path / 'assets'
        nested = assets / 'nested'
        note.write_text('# ok\n', encoding='utf-8')
        nested.mkdir(parents=True)
        (assets / 'a.png').write_bytes(b'a')
        (nested / 'b.jpg').write_bytes(b'b')

        result = build_result(
            'web',
            'jina-reader-generic-web',
            str(tmp_path),
            note_path=str(note),
            asset_dir=str(assets),
        )
        assert_eq(result['status'], 'ready', 'validate_result success status')
        assert_eq(result['asset_count'], 2, 'validate_result recursive asset count')
        assert_eq(result['error'], None, 'validate_result success error')


def test_validate_result_missing_note():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        missing = tmp_path / 'missing.md'
        result = build_result(
            'web',
            'jina-reader-generic-web',
            str(tmp_path),
            note_path=str(missing),
        )
        assert_eq(result['status'], 'error', 'missing note should fail')
        assert_true('note_path not found' in (result.get('error') or ''), 'missing note error message')


def test_unified_runner_routes():
    x = runner_dry_run('https://x.com/nav/status/123')
    assert_eq(x['source_type'], 'x', 'runner x source_type')
    assert_true(any(part.endswith(('x_opencli_executor.py', 'x_api_executor.py')) for part in x['command']), 'runner x command')
    assert_true('--translation-choice' in x['command'], 'runner x should pass translation-choice')

    wechat = runner_dry_run('https://mp.weixin.qq.com/s/abc')
    assert_eq(wechat['source_type'], 'wechat', 'runner wechat source_type')
    assert_true(any(part.endswith('wechat_executor.py') for part in wechat['command']), 'runner wechat command')

    web = runner_dry_run('https://example.com/post')
    assert_eq(web['source_type'], 'web', 'runner web source_type')
    assert_true('--llm-title' in web['command'], 'runner web should pass llm-title')
    assert_true('--translation-choice' in web['command'], 'runner web should pass translation-choice')
    assert_true(any(part.endswith('generic_web_executor.py') for part in web['command']), 'runner web command')

    feishu = runner_dry_run(
        'https://waytoagi.feishu.cn/wiki/NL4cwOJp1ip9a1kfRLNcAyrCnDb',
    )
    assert_eq(feishu['source_type'], 'feishu', 'runner feishu source_type')
    assert_true(any(part.endswith('feishu_executor.py') for part in feishu['command']), 'runner feishu command')


def main():
    tests = [
        ('router_contracts', test_router_contracts),
        ('validate_result_success_and_assets', test_validate_result_success_and_assets),
        ('validate_result_missing_note', test_validate_result_missing_note),
        ('unified_runner_routes', test_unified_runner_routes),
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
