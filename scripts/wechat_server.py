#!/usr/bin/env python3
"""Receive extracted WeChat article JSON and persist it under /tmp/wechat_articles."""

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

SAVE_DIR = '/tmp/wechat_articles'


class ArticleHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length)
        data = json.loads(body)

        fname = data.get('filename', 'unnamed') + '.json'
        fname = fname.replace('/', '_').replace('\\', '_')
        fpath = os.path.join(SAVE_DIR, fname)

        with open(fpath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps({'status': 'ok', 'file': fpath}).encode())

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def log_message(self, format, *args):
        pass


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 18888
    os.makedirs(SAVE_DIR, exist_ok=True)
    server = HTTPServer(('127.0.0.1', port), ArticleHandler)
    server.serve_forever()


if __name__ == '__main__':
    main()
