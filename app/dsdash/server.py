"""Local web UI. Binds to localhost only, and refuses other Host headers."""
import json
import logging
import socket
import struct
import sys
import threading
from io import BytesIO
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from PIL import Image

from . import layout as layouts, widgets
from .app import App, LayoutConflict

log = logging.getLogger(__name__)

WEB_DIR = Path(__file__).resolve().parent / "web"
UI_FONT = layouts.ASSETS / "fonts" / "fusion-pixel-12px-monospaced-zh_hans.otf"
MAX_UPLOAD = 8 * 1024 * 1024
HANG_UP_SECONDS = .25
SOUNDS = {"select.wav", "back.wav", "launch.wav"}
REVISION_HEADER = "X-Layout-Revision"
STATIC_TYPES = {".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml"}


def make_handler(app: App, port: int):
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    class Handler(BaseHTTPRequestHandler):
        # Reuse connections: the page polls, and a new connection per request
        # left thousands waiting to close, and new ones stuck behind them.
        protocol_version = "HTTP/1.1"
        disable_nagle_algorithm = True
        timeout = 30

        def log_message(self, format, *args):
            log.debug(format, *args)

        def _send(self, body: bytes, content_type: str, status: int = 200, revision=None):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            if revision is not None:
                self.send_header(REVISION_HEADER, str(revision))
            if self.close_connection:
                self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, value, status: int = 200, revision=None):
            self._send(json.dumps(value).encode(), "application/json", status, revision)

        def _sent_revision(self):
            value = self.headers.get(REVISION_HEADER)
            return None if value is None else int(value)

        def _trusted(self) -> bool:
            # Stops other websites reaching this server through the browser.
            if self.headers.get("Host") in allowed_hosts:
                return True
            self.close_connection = True    # Any request body is still unread.
            self._json({"error": "Forbidden host"}, 403)
            return False

        def do_GET(self):
            if not self._trusted():
                return
            path = urlsplit(self.path).path
            if path == "/":
                self._send((WEB_DIR / "index.html").read_bytes(), "text/html; charset=utf-8")
            elif path == "/api/status":
                self._json(app.status())
            elif path == "/api/frame.png":
                self._send(app.frame_png(), "image/png")
            elif path == "/api/layout":
                # Revision first: a save in between then looks stale, which is the safe way round.
                revision = app.revision
                self._json(app.layout, revision=revision)
            elif path == "/api/themes":
                self._json(app.themes.listing())
            elif path == "/api/catalog":
                self._json(app.catalog())
            elif path == "/api/pixel-scale":
                self._send_pixel_scale(parse_qs(urlsplit(self.path).query).get("file", [""])[0])
            elif path.startswith("/web/"):
                self._send_static(path[len("/web/"):])
            elif path == "/font.otf":
                self._send(UI_FONT.read_bytes(), "font/otf")
            elif path in ("/ui/raised.png", "/ui/flat.png"):
                out = BytesIO()
                widgets.button_frame(path[len("/ui/"):-len(".png")]).save(out, "PNG")
                self._send(out.getvalue(), "image/png")
            elif path.startswith("/art/"):
                self._send_art(unquote(path[len("/art/"):]))
            elif path.startswith("/sound/"):
                self._send_sound(path[len("/sound/"):])
            elif path.startswith("/api/file/"):
                self._send_file(unquote(path[len("/api/file/"):]))
            else:
                self._json({"error": "Not found"}, 404)

        def _send_file(self, reference: str):
            try:
                file = layouts.resolve_file(reference)
                self._send(file.read_bytes(), {".gif": "image/gif", ".png": "image/png"}.get(file.suffix.lower(), "image/bmp"))
            except (layouts.LayoutError, OSError):
                self._json({"error": "Not found"}, 404)

        def _send_static(self, name: str):
            file = (WEB_DIR / name).resolve()
            if WEB_DIR.resolve() not in file.parents or not file.is_file():
                self._json({"error": "Not found"}, 404)
                return
            self._send(file.read_bytes(), STATIC_TYPES.get(file.suffix, "application/octet-stream"))

        def _send_art(self, name: str):
            """Art as PNG with its magenta key colour removed, ready for CSS."""
            try:
                image = widgets.load_art(f"art:{name}")
            except (layouts.LayoutError, OSError):
                self._json({"error": "Not found"}, 404)
                return
            out = BytesIO()
            image.save(out, "PNG")
            self._send(out.getvalue(), "image/png")

        def _send_sound(self, name: str):
            if name not in SOUNDS:
                self._json({"error": "Not found"}, 404)
                return
            self._send((layouts.ART_DIR / "sound" / name).read_bytes(), "audio/wav")

        def _send_pixel_scale(self, reference: str):
            try:
                path = layouts.resolve_file(reference)
                with Image.open(path) as image:
                    size = image.size
                self._json({"scale": widgets.pixel_scale(path), "width": size[0], "height": size[1]})
            except (layouts.LayoutError, OSError):
                self._json({"error": "Not found"}, 404)

        def do_POST(self):
            if not self._trusted():
                return
            length = int(self.headers.get("Content-Length", 0))
            if length > MAX_UPLOAD:
                self.close_connection = True
                self._json({"error": "Too large"}, 413)
                return
            body = self.rfile.read(length)
            url = urlsplit(self.path)

            try:
                if url.path == "/api/brightness":
                    app.set_brightness(int(json.loads(body)["level"]))
                    self._json(app.status())
                elif url.path == "/api/layout":
                    saved, revision = app.set_layout(json.loads(body), self._sent_revision())
                    self._json(saved, revision=revision)
                elif url.path == "/api/themes":
                    self._json(app.change_theme(json.loads(body)))
                elif url.path == "/api/layout/reset":
                    saved, revision = app.reset_layout(self._sent_revision())
                    self._json(saved, revision=revision)
                elif url.path == "/api/upload":
                    name = parse_qs(url.query).get("name", [""])[0]
                    self._json({"file": app.save_upload(name, body), "files": layouts.list_files()})
                else:
                    self._json({"error": "Not found"}, 404)
            except LayoutConflict as error:
                self._json({"error": str(error)}, 409, app.revision)
            except (ValueError, KeyError, TypeError, OSError) as error:
                self._json({"error": str(error)}, 400)

    return Handler


class Server(ThreadingHTTPServer):
    # A page load opens many connections at once. Windows refuses any that overflow
    # the default queue of 5, which can leave the page without its scripts.
    request_queue_size = 128
    ipv6 = None     # Its sibling on ::1, as `localhost` tries that first.

    def shutdown(self):
        if self.ipv6:
            self.ipv6.shutdown()
        super().shutdown()

    def server_close(self):
        if self.ipv6:
            self.ipv6.server_close()
        super().server_close()

    def shutdown_request(self, request):
        # Closing normally leaves a TIME_WAIT here. Windows can stop expiring those, and
        # a new connection that lands on one hangs. A reset leaves nothing, but it drops
        # anything unread, so the client gets time to finish and hang up first.
        try:
            request.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("hh", 1, 0))
            request.settimeout(HANG_UP_SECONDS)
            while request.recv(4096):
                pass
        except OSError:
            pass
        self.close_request(request)

    def handle_error(self, request, client_address):
        # Closing a tab drops its connection, which is normal.
        if not isinstance(sys.exc_info()[1], ConnectionError):
            super().handle_error(request, client_address)


class ServerV6(Server):
    address_family = socket.AF_INET6


def create_server(app: App, port: int) -> ThreadingHTTPServer:
    """Raises OSError if the port is taken, which usually means already running."""
    handler = make_handler(app, port)
    server = Server(("127.0.0.1", port), handler)
    try:
        server.ipv6 = ServerV6(("::1", port), handler)
        threading.Thread(target=server.ipv6.serve_forever, name="web-ipv6", daemon=True).start()
    except OSError:     # No IPv6 here. `localhost` then only takes longer.
        server.ipv6 = None
    return server


def serve(app: App, port: int):
    server = create_server(app, port)
    log.info("Open http://127.0.0.1:%d", port)
    server.serve_forever()
