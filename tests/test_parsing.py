import struct
import tempfile
import unittest
from pathlib import Path

from auction_review import auctionator, cbor, lua_sv, store


def enc(v) -> bytes:
    """Tiny CBOR encoder for tests (WoW-style: Lua strings as byte strings)."""
    def head(major, n):
        if n < 24:
            return bytes([major << 5 | n])
        if n < 256:
            return bytes([major << 5 | 24, n])
        if n < 65536:
            return bytes([major << 5 | 25]) + struct.pack(">H", n)
        return bytes([major << 5 | 26]) + struct.pack(">I", n)
    if isinstance(v, bool):
        return b"\xf5" if v else b"\xf4"
    if isinstance(v, int):
        return head(0, v) if v >= 0 else head(1, -1 - v)
    if isinstance(v, float):
        return b"\xfb" + struct.pack(">d", v)
    if isinstance(v, str):
        b = v.encode()
        return head(2, len(b)) + b
    if isinstance(v, list):
        return head(4, len(v)) + b"".join(enc(x) for x in v)
    if isinstance(v, dict):
        return head(5, len(v)) + b"".join(enc(k) + enc(x) for k, x in v.items())
    raise TypeError(v)


def lua_quote(b: bytes) -> bytes:
    out = bytearray(b'"')
    for c in b:
        if c == 34:
            out += b'\\"'
        elif c == 92:
            out += b"\\\\"
        elif c == 10:
            out += b"\\n"
        elif c == 13:
            out += b"\\r"
        elif c == 0:
            out += b"\\0"
        else:
            out.append(c)
    return bytes(out + b'"')


class LuaParserTest(unittest.TestCase):
    def test_tables_strings_numbers(self):
        src = (b'A = {\r\n["x"] = 1,\r\n["y"] = -2.5,\r\n["s"] = "a\\"b\\\\c\\n\\065",\r\n'
               b'[3] = true,\r\n{ ["p"] = 1, }, -- [1]\r\nname = nil,\r\n}\r\nB = "z"\r\n')
        sv = lua_sv.parse(src)
        a = sv["A"]
        self.assertEqual(a["x"], 1)
        self.assertEqual(a["y"], -2.5)
        self.assertEqual(a["s"], b'a"b\\c\nA')
        self.assertEqual(a[3], True)
        self.assertEqual(a[1], {"p": 1})
        self.assertIsNone(a["name"])
        self.assertEqual(sv["B"], b"z")


class CborTest(unittest.TestCase):
    def test_roundtrip(self):
        value = {"m": 900, "l": {"2506": 900}, "h": {"2506": 1000}, "a": [], "f": 1.5, "n": -3}
        self.assertEqual(cbor.loads(enc(value)), value)


class AuctionatorTest(unittest.TestCase):
    def write(self, d, name, realm_items, last_scan):
        blob = enc({**realm_items, "version": 2})
        content = (b"AUCTIONATOR_SAVEDVARS = {\n[\"TimeOfLastBrowseScan\"] = " + str(last_scan).encode() + b",\n}\n"
                   b"AUCTIONATOR_PRICE_DATABASE = {\n[\"__dbversion\"] = 8,\n[\"PvE\"] = " + lua_quote(blob) + b",\n}\n"
                   b"AUCTIONATOR_POSTING_HISTORY = {\n[\"__dbversion\"] = 1,\n[\"2589\"] = {\n{\n[\"price\"] = 26,\n"
                   b"[\"quantity\"] = 49,\n[\"time\"] = 1794433614,\n},\n},\n}\n")
        p = Path(d) / name
        p.write_bytes(content)
        return p

    def test_read_and_merge(self):
        with tempfile.TemporaryDirectory() as d:
            import auction_review.store as st
            st.DATA_DIR = Path(d)
            p1 = self.write(d, "one.lua", {
                "10940": {"m": 94, "l": [], "h": {"2505": 87}, "a": {"2505": 6067}},
                "g:123:200": {"m": 5, "l": {"2506": 5}, "h": {"2506": 6}, "a": {"2506": 1}},
            }, 100)
            data = auctionator.read(p1)
            item = data.realms["PvE"]["10940"]
            self.assertEqual(item.days[2505], (87, 87, 6067))  # empty low falls back to high
            self.assertEqual(data.postings["2589"][0]["quantity"], 49)
            self.assertEqual(auctionator.item_id_from_key("g:123:200"), 123)
            self.assertIsNone(auctionator.item_id_from_key("p:55"))

            conn = store.connect(Path(d) / "t.db")
            store.ingest_file(conn, p1)
            p2 = self.write(d, "two.lua", {
                "10940": {"m": 87, "l": {"2505": 80, "2506": 20}, "h": {"2505": 90, "2506": 95},
                          "a": {"2505": 100, "2506": 7050}},
            }, 200)
            store.ingest_file(conn, p2)
            self.assertEqual(store.ingest_file(conn, p2)["status"], "unchanged")
            rows = {r["day"]: tuple(r)[3:] for r in conn.execute(
                "SELECT * FROM daily WHERE item_key='10940' ORDER BY day")}
            self.assertEqual(rows[2505], (80, 90, 6067))  # min low, max high, max available
            self.assertEqual(rows[2506], (20, 95, 7050))
            self.assertEqual(conn.execute("SELECT price FROM latest WHERE item_key='10940'").fetchone()[0], 87)
            conn.close()


if __name__ == "__main__":
    unittest.main()
