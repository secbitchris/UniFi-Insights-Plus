"""Compatibility endpoint on the existing Netwatch listener.

Keep the existing /json summary route and its restricted SSH reader. Retire
HTML rendering by redirecting to UniFi Insights. No new listener or privilege.
"""
import http.server
import json
import sys
from pathlib import Path
sys.path.insert(0, '/opt/netwatch')
from netwatch_web import collect, S, PORT


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/json':
            body = json.dumps({'vantages': [{'source': n, 'data': d} for n, _, _, d in collect()]}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            target = json.loads(Path('/opt/netwatch/insights-redirect.json').read_text())['url']
            self.send_response(303)
            self.send_header('Location', target)
            self.end_headers()

    def log_message(self, *args):
        pass


if __name__ == '__main__':
    with S(('0.0.0.0', PORT), Handler) as server:
        server.serve_forever()
