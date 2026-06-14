"""Static server for the site2 design exploration that sends no-cache headers, so a
browser always picks up the latest index.html/style2.css/app2.js instead of a stale copy.
Mirrors scripts/serve.py but rooted at site2/ on port 4180, localhost only."""

import functools
import http.server
import socketserver

PORT = 4180
DIRECTORY = "/Users/ryan/Coding/tier2/seiche/site2"


class Handler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store, must-revalidate")
        self.send_header("Expires", "0")
        super().end_headers()


socketserver.TCPServer.allow_reuse_address = True
with socketserver.TCPServer(("127.0.0.1", PORT), functools.partial(Handler, directory=DIRECTORY)) as httpd:
    print(f"serving {DIRECTORY} on http://127.0.0.1:{PORT}/ (no-cache)")
    httpd.serve_forever()
