"""Local dashboard server: JSON API + static page, with a background file watcher."""
from __future__ import annotations

import json
import logging
import threading
import time
import webbrowser
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from . import __version__, analysis, names, paths, store
from .paths import WEB_DIR, names_file_for

log = logging.getLogger(__name__)


class App:
    """Shared state: the watched file plus background ingest / name lookups."""

    def __init__(self, auctionator_file: Path | None, web_names: bool = False, poll_seconds: int = 20):
        self.file = None
        self.names_file = None
        self.set_file(auctionator_file)
        self.web_names = web_names
        self.poll_seconds = poll_seconds
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.status = {"last_check": None, "last_ingest": None, "message": "starting", "names_running": False}
        self._seen = {}

    def set_file(self, auctionator_file: Path | None):
        self.file = Path(auctionator_file) if auctionator_file else None
        self.names_file = names_file_for(self.file) if self.file else None

    def _mtime(self, p: Path):
        try:
            st = p.stat()
            return (st.st_mtime_ns, st.st_size)
        except OSError:
            return None

    def refresh(self, force=False) -> list[dict]:
        """Ingest Auctionator data and addon names if either file changed."""
        if self.file is None:
            self.status["message"] = "setup needed"
            return []
        with self.lock:
            results = []
            conn = store.connect()
            try:
                for p in (self.file, self.names_file):
                    sig = self._mtime(p)
                    if sig is None or (not force and self._seen.get(p) == sig):
                        continue
                    if p == self.file:
                        results += store.ingest(conn, p)
                    else:
                        n = names.import_addon_names(conn, p)
                        results.append({"file": str(p), "status": "names", "count": n})
                    self._seen[p] = sig
                if results:
                    names.harvest_links(conn, self.file.parent.parent)
                    self.status["last_ingest"] = int(time.time())
                self.status["message"] = "ok"
            except Exception as e:  # keep the server alive; report in the UI
                log.exception("refresh failed")
                self.status["message"] = f"refresh failed: {e}"
            finally:
                conn.close()
            self.status["last_check"] = int(time.time())
        if results:
            self.start_name_lookup()
        return results

    def start_name_lookup(self):
        if not self.web_names or self.status["names_running"]:
            return

        def run():
            self.status["names_running"] = True
            conn = store.connect()
            try:
                missing = names.missing_item_ids(conn)
                if missing:
                    log.info("looking up %d item names on Wowhead", len(missing))
                    names.fetch_wowhead(conn, missing, stop=self.stop)
            finally:
                conn.close()
                self.status["names_running"] = False

        threading.Thread(target=run, daemon=True, name="names").start()

    def watch(self):
        while not self.stop.wait(self.poll_seconds):
            self.refresh()


def _int(qs, name, default):
    try:
        return int(qs.get(name, [default])[0])
    except (TypeError, ValueError):
        return default


def make_handler(app: App):
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(WEB_DIR), **kw)

        def log_message(self, fmt, *args):
            log.debug(fmt, *args)

        def end_headers(self):
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

        def _json(self, data, status=HTTPStatus.OK):
            body = json.dumps(data).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _body(self):
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(n) or b"{}")

        def _host_ok(self):
            # Reject requests whose Host isn't a loopback name. This defeats DNS rebinding,
            # where a malicious site points its own domain at 127.0.0.1 to read this server.
            port = self.server.server_address[1]
            allowed = {f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"}
            if self.headers.get("Host", "").lower() in allowed:
                return True
            self._json({"error": "forbidden host"}, HTTPStatus.FORBIDDEN)
            return False

        def _local_only(self):
            # Block cross-site requests from other web pages to this local server.
            if not self._host_ok():
                return False
            origin = self.headers.get("Origin")
            host = self.headers.get("Host", "")
            if origin and urlparse(origin).netloc != host:
                self._json({"error": "forbidden"}, HTTPStatus.FORBIDDEN)
                return False
            return True

        def do_HEAD(self):
            if self._host_ok():
                super().do_HEAD()

        def do_GET(self):
            if not self._host_ok():
                return
            url = urlparse(self.path)
            if not url.path.startswith("/api/"):
                return super().do_GET()
            qs = parse_qs(url.query)
            conn = store.connect()
            try:
                realms = analysis.realms(conn)
                realm = qs.get("realm", [realms[0] if realms else ""])[0]
                route = url.path[len("/api/"):]
                if route == "overview":
                    data = analysis.overview(conn)
                    data["status"] = app.status
                    data["version"] = __version__
                    data["needs_setup"] = app.file is None
                    data["file"] = str(app.file) if app.file else None
                    data["names_file_found"] = bool(app.names_file and app.names_file.is_file())
                    data["addon_installed"] = bool(app.file and paths.addon_installed(app.file))
                    return self._json(data)
                if route == "setup":
                    return self._json({"current": str(app.file) if app.file else None,
                                       "candidates": [str(p) for p in paths.all_candidates()]})
                if route == "movers":
                    return self._json(analysis.movers(
                        conn, realm, window=_int(qs, "window", 7), min_prior_days=_int(qs, "min_days", 1),
                        min_price=_int(qs, "min_price", 0), min_available=_int(qs, "min_available", 0),
                        direction=qs.get("direction", ["both"])[0], limit=_int(qs, "limit", 100)))
                if route == "supply":
                    return self._json(analysis.supply(conn, realm, window=_int(qs, "window", 7),
                                                      min_baseline=_int(qs, "min_baseline", 5)))
                if route == "vendor":
                    return self._json(analysis.vendor_resale(conn, realm))
                if route == "watchlist":
                    return self._json(analysis.watchlist(conn, realm))
                if route == "postings":
                    return self._json(analysis.my_postings(conn, realm))
                if route == "search":
                    return self._json({"rows": analysis.search(conn, qs.get("q", [""])[0], realm)})
                if route.startswith("item/"):
                    detail = analysis.item_detail(conn, realm, unquote(route[len("item/"):]))
                    if detail is None:
                        return self._json({"error": "unknown item"}, HTTPStatus.NOT_FOUND)
                    return self._json(detail)
                return self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            except Exception as e:
                log.exception("API error")
                return self._json({"error": str(e)}, HTTPStatus.INTERNAL_SERVER_ERROR)
            finally:
                conn.close()

        def do_POST(self):
            if not self._local_only():
                return
            route = urlparse(self.path).path
            try:
                if route == "/api/refresh":
                    return self._json({"results": app.refresh(force=True)})
                if route == "/api/setup":
                    raw = str(self._body().get("path") or "").strip().strip('"')
                    found = paths.candidates_under(Path(raw)) if raw else []
                    if not found:
                        return self._json({"error": "No Auctionator data found there. Pick your World of Warcraft "
                                                    "folder, and make sure you've scanned the auction house with "
                                                    "Auctionator and logged out or typed /reload at least once."},
                                          HTTPStatus.BAD_REQUEST)
                    paths.set_auctionator_file(found[0])
                    app.set_file(found[0])
                    return self._json({"file": str(found[0]), "results": app.refresh(force=True)})
                if route == "/api/install-addon":
                    if app.file is None:
                        return self._json({"error": "Set up your WoW folder first."}, HTTPStatus.BAD_REQUEST)
                    dest = paths.install_addon(app.file)
                    return self._json({"installed_to": str(dest)})
                if route == "/api/watchlist":
                    b = self._body()
                    conn = store.connect()
                    try:
                        analysis.set_watch(conn, str(b["item_key"]), b.get("below"), b.get("above"), b.get("note"))
                    finally:
                        conn.close()
                    return self._json({"ok": True})
                return self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            except Exception as e:
                log.exception("API error")
                return self._json({"error": str(e)}, HTTPStatus.BAD_REQUEST)

        def do_DELETE(self):
            if not self._local_only():
                return
            route = urlparse(self.path).path
            if route.startswith("/api/watchlist/"):
                conn = store.connect()
                try:
                    analysis.remove_watch(conn, unquote(route[len("/api/watchlist/"):]))
                finally:
                    conn.close()
                return self._json({"ok": True})
            return self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    return Handler


def serve(auctionator_file: Path | None, port=8765, open_browser=True, web_names=False):
    app = App(auctionator_file, web_names=web_names)
    print(f"Auction Review {__version__}")
    if auctionator_file:
        print(f"Watching {auctionator_file}")
        for r in app.refresh(force=True):
            print(f"  {r['status']}: {r['file']}")
    else:
        print("Couldn't find Auctionator data automatically - choose your WoW folder in the dashboard.")
    print(f"Data folder: {paths.DATA_DIR}")
    url = f"http://127.0.0.1:{port}/"
    try:
        server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(app))
    except OSError:
        print(f"Port {port} is already in use - Auction Review is probably already running. Opening {url}")
        if open_browser:
            webbrowser.open(url)
        return
    threading.Thread(target=app.watch, daemon=True, name="watcher").start()
    print(f"Dashboard running at {url}  (Ctrl+C to stop)")
    if open_browser:
        threading.Timer(0.5, webbrowser.open, (url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        app.stop.set()
        server.server_close()
