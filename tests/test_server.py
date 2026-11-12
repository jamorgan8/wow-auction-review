import http.client
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


if __name__ == "__main__":
    unittest.main()
