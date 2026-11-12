import http.client
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

from auction_review.server import App, make_handler


class HostCheckTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app = App(Path("nonexistent/Auctionator.lua"), web_names=False)
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def request(self, method, path, host, origin=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {"Host": host}
        if origin:
            headers["Origin"] = origin
        conn.request(method, path, headers=headers, body=b"{}" if method == "POST" else None)
        status = conn.getresponse().status
        conn.close()
        return status

    def test_loopback_hosts_allowed(self):
        for host in (f"127.0.0.1:{self.port}", f"localhost:{self.port}", f"LOCALHOST:{self.port}"):
            self.assertEqual(self.request("GET", "/index.html", host), 200, host)

    def test_rebinding_hosts_rejected(self):
        for host in (f"evil.example:{self.port}", "evil.example", "127.0.0.1", f"127.0.0.1:{self.port + 1}", ""):
            self.assertEqual(self.request("GET", "/index.html", host), 403, host)
            self.assertEqual(self.request("GET", "/api/overview", host), 403, host)
            self.assertEqual(self.request("POST", "/api/refresh", host), 403, host)
            self.assertEqual(self.request("DELETE", "/api/watchlist/1", host), 403, host)

    def test_cross_origin_write_rejected(self):
        host = f"127.0.0.1:{self.port}"
        self.assertEqual(self.request("DELETE", "/api/watchlist/x", host, origin="https://evil.example"), 403)


class SetupModeTest(unittest.TestCase):
    """With no Auctionator file the server must still start and ask for the WoW folder."""

    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(App(None, web_names=False)))
        cls.host = f"127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def call(self, method, path, body=None):
        conn = http.client.HTTPConnection(self.host, timeout=10)
        conn.request(method, path, body=json.dumps(body).encode() if body is not None else None,
                     headers={"Host": self.host, "Content-Type": "application/json"})
        resp = conn.getresponse()
        data = json.loads(resp.read() or b"{}")
        conn.close()
        return resp.status, data

    def test_overview_reports_setup_needed(self):
        status, data = self.call("GET", "/api/overview")
        self.assertEqual(status, 200)
        self.assertTrue(data["needs_setup"])
        self.assertIsNone(data["file"])

    def test_setup_rejects_folder_without_data(self):
        with tempfile.TemporaryDirectory() as d:
            status, data = self.call("POST", "/api/setup", {"path": d})
        self.assertEqual(status, 400)
        self.assertIn("No Auctionator data", data["error"])

    def test_install_addon_needs_setup_first(self):
        status, _ = self.call("POST", "/api/install-addon", {})
        self.assertEqual(status, 400)


class PackageDataTest(unittest.TestCase):
    def test_bundled_files_present(self):
        from auction_review import paths
        self.assertTrue((paths.ADDON_SOURCE / "AuctionReviewNames.toc").is_file())
        self.assertTrue((paths.ADDON_SOURCE / "Main.lua").is_file())
        self.assertTrue((paths.WEB_DIR / "index.html").is_file())
        self.assertTrue((paths.WEB_DIR / "vendor" / "chart.umd.min.js").is_file())


if __name__ == "__main__":
    unittest.main()
