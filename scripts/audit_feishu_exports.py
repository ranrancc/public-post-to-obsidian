#!/usr/bin/env python3

import argparse
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser(
        description="Audit Feishu public exports for pagination truncation risk."
    )
    parser.add_argument(
        "--cookie-header",
        required=True,
        help="Cookie header copied from Playwright/browser context.",
    )
    parser.add_argument(
        "--dest-dir",
        help="Directory containing exported .meta.json files.",
    )
    parser.add_argument(
        "--manifest",
        help="Path to a JSON array of export items. Each item needs label/page_id/space_id/container_id.",
    )
    parser.add_argument(
        "--pattern",
        help="Optional substring filter for labels or titles when scanning dest-dir meta files.",
    )
    return parser.parse_args()


def load_items(args):
    items = []
    if args.dest_dir:
        dest_dir = Path(args.dest_dir)
        for meta_path in sorted(dest_dir.glob("*.meta.json")):
            data = json.loads(meta_path.read_text(encoding="utf-8"))
            label = data.get("title") or meta_path.stem
            if args.pattern and args.pattern not in label:
                continue
            items.append(
                {
                    "label": label,
                    "page_id": data["page_id"],
                    "space_id": data["space_id"],
                    "container_id": data["container_id"],
                    "source_url": data.get("source_url"),
                    "meta_path": str(meta_path),
                }
            )
    if args.manifest:
        manifest_items = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
        for item in manifest_items:
            label = item.get("label") or item.get("title") or item["page_id"]
            if args.pattern and args.pattern not in label:
                continue
            items.append(item)
    if not items:
        raise SystemExit("No audit items found. Provide --dest-dir or --manifest.")
    return items


def fetch_json(url, cookie_header):
    req = urllib.request.Request(
        url,
        headers={
            "accept": "application/json, text/plain, */*",
            "cookie": cookie_header,
            "user-agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36"
            ),
        },
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)


def load_blocks(item, cookie_header):
    base_url = (
        "https://waytoagi.feishu.cn/space/api/docx/pages/client_vars"
        f"?id={item['page_id']}&mode=7&limit=239&wiki_space_id={item['space_id']}"
        f"&container_type=wiki2.0&container_id={item['container_id']}"
    )
    blocks = {}
    cursor = None
    seen_cursors = set()
    pages_fetched = 0
    while True:
        url = base_url
        if cursor:
            url += f"&cursor={urllib.parse.quote(cursor)}"
        payload = fetch_json(url, cookie_header)
        data = payload.get("data", {})
        blocks.update(data.get("block_map", {}))
        pages_fetched += 1
        if not data.get("has_more"):
            break
        next_cursor = (data.get("next_cursors") or [None])[0] or data.get("cursor")
        if not next_cursor or next_cursor in seen_cursors:
            break
        seen_cursors.add(next_cursor)
        cursor = next_cursor
    return blocks, pages_fetched


def audit_item(item, cookie_header):
    try:
        blocks, pages_fetched = load_blocks(item, cookie_header)
        root = blocks.get(item["page_id"], {})
        root_children = ((root.get("data") or {}).get("children") or [])
        missing_root_children = [cid for cid in root_children if cid not in blocks]
        return {
            "label": item["label"],
            "pages_fetched": pages_fetched,
            "block_count": len(blocks),
            "root_child_count": len(root_children),
            "missing_root_children": len(missing_root_children),
            "status": "OK" if item["page_id"] in blocks and not missing_root_children else "TRUNCATED_RISK",
            "source_url": item.get("source_url"),
            "meta_path": item.get("meta_path"),
        }
    except Exception as exc:
        return {
            "label": item["label"],
            "status": "ERROR",
            "error": str(exc),
            "source_url": item.get("source_url"),
            "meta_path": item.get("meta_path"),
        }


def main():
    args = parse_args()
    items = load_items(args)
    results = [audit_item(item, args.cookie_header) for item in items]
    for result in results:
        print(json.dumps(result, ensure_ascii=False))
    failed = [r for r in results if r["status"] != "OK"]
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
