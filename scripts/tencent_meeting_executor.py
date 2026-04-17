#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from common import build_result, target_dir_for_source


SCRIPT_DIR = Path(__file__).resolve().parent
REPLAY_SCRIPT = SCRIPT_DIR.parents[1] / 'tencent-meeting-replay' / 'scripts' / 'tencent_meeting_replay.py'


def main() -> None:
    parser = argparse.ArgumentParser(description='Tencent Meeting replay wrapper for public-post-to-obsidian.')
    parser.add_argument('url')
    parser.add_argument('--download-video', action='store_true')
    args = parser.parse_args()

    target_dir = target_dir_for_source('tencent_meeting')
    cmd = [
        sys.executable,
        str(REPLAY_SCRIPT),
        args.url,
        '--output-dir',
        target_dir,
    ]
    if not args.download_video:
        cmd.append('--transcript-only')

    cp = subprocess.run(cmd, text=True, capture_output=True)
    if cp.returncode != 0:
        error = cp.stderr.strip() or cp.stdout.strip() or 'tencent meeting replay extraction failed'
        print(json.dumps(build_result('tencent_meeting', 'tencent_meeting_executor.py', target_dir, status='error', error=error), ensure_ascii=False, indent=2))
        sys.exit(cp.returncode)

    payload = json.loads(cp.stdout)
    result = build_result(
        'tencent_meeting',
        'tencent_meeting_executor.py',
        payload.get('resolved_output_dir') or target_dir,
        status='ok',
        note_path=payload.get('transcript_path'),
        asset_dir=None,
        replay_video_path=payload.get('video_path'),
        replay_video_url=payload.get('video_url'),
        meta=payload.get('meta'),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
