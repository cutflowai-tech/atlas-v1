"""Run explicitly: python3 web/demo.py (standard library only)."""
from http.server import SimpleHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path.startswith('/api/'):
            if path != '/api/editors/editor-42':
                self.send_error(404, 'Unknown fixture editor')
                return
            body = (ROOT / 'fixtures/editor-profile.json').read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()


if __name__ == '__main__':
    print('Fixture demo: http://127.0.0.1:8080/?editor_id=editor-42', flush=True)
    HTTPServer(('127.0.0.1', 8080), Handler).serve_forever()
