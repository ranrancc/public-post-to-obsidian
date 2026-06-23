#!/usr/bin/env python3
import json
import os
import subprocess
import sys
import tempfile
import urllib.error
from pathlib import Path

from common import atomic_replace_directory, atomic_write_text, build_result, load_workspace_env
from run_public_capture import parse_result, run_fallback_chain
import x_api_executor

SCRIPT_DIR = Path(__file__).resolve().parent
ROUTER = SCRIPT_DIR / 'router.py'
RUNNER = SCRIPT_DIR / 'run_public_capture.py'
TEST_OUTPUT_ROOT = Path(tempfile.gettempdir()) / 'public-post-to-obsidian-integration'


def assert_true(condition, label):
    if not condition:
        raise AssertionError(label)


def assert_eq(actual, expected, label):
    if actual != expected:
        raise AssertionError(f'{label}: expected {expected!r}, got {actual!r}')


def router_result(url: str) -> dict:
    env = os.environ.copy()
    env['PUBLIC_POST_OUTPUT_ROOT'] = str(TEST_OUTPUT_ROOT)
    cp = subprocess.run(
        [sys.executable, str(ROUTER), url],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    return json.loads(cp.stdout)


def runner_dry_run(url: str, extra: list[str] | None = None) -> dict:
    cmd = [sys.executable, str(RUNNER), '--dry-run']
    if extra:
        cmd.extend(extra)
    cmd.append(url)
    env = os.environ.copy()
    env['PUBLIC_POST_OUTPUT_ROOT'] = str(TEST_OUTPUT_ROOT)
    cp = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    return json.loads(cp.stdout)


def test_router_contracts():
    cases = [
        (
            'https://x.com/nav/status/123',
            {
                'source_type': 'x',
                'handler_used': 'x_api_executor.py',
                'target_subdir': 'X',
                'status': 'ready',
                'fetch_url': 'https://r.jina.ai/http://x.com/nav/status/123',
            },
        ),
        (
            'https://mp.weixin.qq.com/s/abc',
            {
                'source_type': 'wechat',
                'handler_used': 'wechat_executor.py',
                'target_subdir': '微信剪藏',
                'status': 'ready',
            },
        ),
        (
            'https://waytoagi.feishu.cn/wiki/NL4cwOJp1ip9a1kfRLNcAyrCnDb',
            {
                'source_type': 'feishu',
                'handler_used': 'feishu_executor.py',
                'target_subdir': '飞书',
                'status': 'ready',
            },
        ),
        (
            'https://example.com/post',
            {
                'source_type': 'web',
                'handler_used': 'generic_web_executor.py',
                'target_subdir': '网页剪藏',
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
        assert_eq(Path(result.get('target_dir') or ''), TEST_OUTPUT_ROOT / expected['target_subdir'], f'route {url} target_dir')
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
    assert_true(any(part.endswith(('x_api_executor.py', 'x_fxtwitter_executor.py', 'x_opencli_executor.py')) for part in x['command']), 'runner x command')
    assert_true('--translation-choice' in x['command'], 'runner x should pass translation-choice')
    x_handlers = [Path(command[1]).name for command in x['commands']]
    assert_true('x_fxtwitter_executor.py' in x_handlers, 'runner X chain should include FxTwitter')
    assert_true(x_handlers[-1] == 'x_executor.py', 'runner X chain should end with Jina')
    x_original = runner_dry_run('https://x.com/nav/status/123', ['--translation-choice', 'original'])
    assert_true('original' in x_original['command'], 'runner X should respect explicit translation choice')

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


def test_portable_env_precedence():
    key = 'PUBLIC_POST_TEST_VALUE'
    old_env_file = os.environ.get('PUBLIC_POST_ENV_FILE')
    old_value = os.environ.pop(key, None)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / '.env'
            env_file.write_text(f'{key}=explicit\n', encoding='utf-8')
            os.environ['PUBLIC_POST_ENV_FILE'] = str(env_file)
            loaded = load_workspace_env()
            assert_true(str(env_file.resolve()) in loaded, 'explicit env file should be loaded')
            assert_eq(os.environ.get(key), 'explicit', 'explicit env should have first-file precedence')
    finally:
        if old_env_file is None:
            os.environ.pop('PUBLIC_POST_ENV_FILE', None)
        else:
            os.environ['PUBLIC_POST_ENV_FILE'] = old_env_file
        if old_value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = old_value


def test_runner_fallback_contract():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        fail = root / 'fail.py'
        success = root / 'success.py'
        fail.write_text("import json,sys; print(json.dumps({'status':'error','handler_used':'first','error':'nope'})); sys.exit(1)\n", encoding='utf-8')
        success.write_text("import json; print(json.dumps({'status':'ready','handler_used':'second','note_path':'ok.md'}))\n", encoding='utf-8')
        result, code = run_fallback_chain(
            [[sys.executable, str(fail)], [sys.executable, str(success)]],
            os.environ.copy(),
        )
        assert_eq(code, 0, 'fallback chain exit code')
        assert_eq(result['handler_used'], 'second', 'fallback should return first successful executor')
        assert_eq(len(result['fallback_chain']), 2, 'fallback diagnostics should retain both attempts')
        assert_eq(parse_result('prefix\n{"status":"ready"}\nsuffix')['status'], 'ready', 'result parser should tolerate wrapper output')


def test_auth_error_is_not_retried():
    original_urlopen = x_api_executor.urllib.request.urlopen
    original_sleep = x_api_executor.time.sleep
    calls = []
    sleeps = []

    def fail_auth(*args, **kwargs):
        calls.append(1)
        raise urllib.error.HTTPError('https://api.x.com', 401, 'Unauthorized', {}, None)

    x_api_executor.urllib.request.urlopen = fail_auth
    x_api_executor.time.sleep = lambda delay: sleeps.append(delay)
    try:
        try:
            x_api_executor.fetch_tweet('123', 'invalid')
        except urllib.error.HTTPError:
            pass
        else:
            raise AssertionError('401 should propagate')
    finally:
        x_api_executor.urllib.request.urlopen = original_urlopen
        x_api_executor.time.sleep = original_sleep
    assert_eq(len(calls), 1, '401 should not be retried')
    assert_eq(sleeps, [], '401 should not sleep')


def test_atomic_output_helpers():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        note = root / 'note.md'
        atomic_write_text(note, 'new\n')
        assert_eq(note.read_text(encoding='utf-8'), 'new\n', 'atomic note write')
        destination = root / 'assets'
        staging = root / 'staging'
        destination.mkdir()
        staging.mkdir()
        (destination / 'old').write_text('old', encoding='utf-8')
        (staging / 'new').write_text('new', encoding='utf-8')
        atomic_replace_directory(staging, destination)
        assert_true((destination / 'new').exists(), 'atomic directory should install staging')
        assert_true(not (destination / 'old').exists(), 'atomic directory should remove old version after success')


def main():
    tests = [
        ('router_contracts', test_router_contracts),
        ('validate_result_success_and_assets', test_validate_result_success_and_assets),
        ('validate_result_missing_note', test_validate_result_missing_note),
        ('unified_runner_routes', test_unified_runner_routes),
        ('portable_env_precedence', test_portable_env_precedence),
        ('runner_fallback_contract', test_runner_fallback_contract),
        ('auth_error_is_not_retried', test_auth_error_is_not_retried),
        ('atomic_output_helpers', test_atomic_output_helpers),
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
