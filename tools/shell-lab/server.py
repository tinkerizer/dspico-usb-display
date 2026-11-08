"""Live preview for hand-editing the DS shells. See tools/shell-lab/README.md."""
import http.server
import json
import sys
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
WEB = HERE.parent.parent / "app" / "dsdash" / "web"
REFS = HERE / "refs"
SHELLS = {"lite": WEB / "shell.svg", "dsi": WEB / "shell-dsi.svg"}
IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}


class Handler(http.server.BaseHTTPRequestHandler):
    def _send(self, body, kind, status=200):
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/":
            self._send((HERE / "index.html").read_bytes(), "text/html; charset=utf-8")
        elif path == "/api/state":
            # The page polls this and reloads a shell when its file changes.
            state = {
                "shells": {name: file.stat().st_mtime for name, file in SHELLS.items()},
                "refs": sorted(p.name for p in REFS.glob("*") if p.suffix.lower() in IMAGE_TYPES),
            }
            self._send(json.dumps(state).encode(), "application/json")
        elif path.startswith("/shell/") and path[7:] in SHELLS:
            self._send(SHELLS[path[7:]].read_bytes(), "image/svg+xml")
        elif path.startswith("/refs/"):
            file = REFS / Path(path[6:]).name
            if file.suffix.lower() in IMAGE_TYPES and file.is_file():
                self._send(file.read_bytes(), IMAGE_TYPES[file.suffix.lower()])
            elif file.suffix == ".json" and file.is_file():   # A starting alignment, as {s, x, y}
                self._send(file.read_bytes(), "application/json")
            else:
                self._send(b"Not found", "text/plain", 404)
        else:
            self._send(b"Not found", "text/plain", 404)

    def log_message(self, *args):
        pass


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8770
    REFS.mkdir(exist_ok=True)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"Shell lab at {url}  (Ctrl+C to stop)")
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
