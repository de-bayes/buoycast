"""Static server for the dashboard that sends no-cache headers, so a browser
always picks up the latest data.json/app.js instead of holding a stale copy."""

import functools
import http.server
import socketserver

PORT = 4175
DIRECTORY = "/Users/ryan/Coding/tier2/seiche/site"


class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        # clean URL: /ml -> /ml.html
        path = self.path.split("?", 1)[0]
        if path in ("/ml", "/ml/"):
            self.path = "/ml.html"
        super().do_GET()

    def end_headers(self):
        self.send_header("Cache-Control", "no-store, must-revalidate")
        self.send_header("Expires", "0")
        super().end_headers()


socketserver.TCPServer.allow_reuse_address = True
with socketserver.TCPServer(("127.0.0.1", PORT), functools.partial(Handler, directory=DIRECTORY)) as httpd:
    print(f"serving {DIRECTORY} on http://127.0.0.1:{PORT}/ (no-cache)")
    httpd.serve_forever()
