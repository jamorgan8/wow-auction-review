"""Parser for WoW SavedVariables files (a restricted subset of Lua).

SavedVariables files contain only top-level assignments of literal values:
tables, strings, numbers, booleans and nil. Strings are returned as ``bytes``
because Auctionator stores binary CBOR blobs inside Lua strings; use
:func:`text` to turn a value into ``str``.
"""
from __future__ import annotations

import re

_ESCAPES = {
    ord("a"): 7, ord("b"): 8, ord("f"): 12, ord("n"): 10, ord("r"): 13,
    ord("t"): 9, ord("v"): 11, ord("\\"): 92, ord('"'): 34, ord("'"): 39,
    10: 10, 13: 10,  # backslash followed by a real newline
}
_IDENT = re.compile(rb"[A-Za-z_][A-Za-z0-9_]*")
_NUMBER = re.compile(rb"-?(?:0[xX][0-9a-fA-F]+|(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?|inf|nan)")
_NAME_ASSIGN = re.compile(rb"([A-Za-z_][A-Za-z0-9_]*)\s*=(?!=)")
_STR_SPECIAL ={q: re.compile(rb"[\\" + q + rb"]") for q in (b'"', b"'")}


class LuaParseError(ValueError):
    pass


def text(value) -> str:
    """Decode a parsed Lua string (bytes) to str; pass other values through."""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return value


def as_list(table):
    """Return a Lua array table (dict with keys 1..n) as a list."""
    if isinstance(table, list):
        return table
    if not isinstance(table, dict):
        return []
    return [table[k] for k in sorted(k for k in table if isinstance(k, int))]


class _Parser:
    def __init__(self, data: bytes):
        self.s = data
        self.i = 0
        self.n = len(data)

    def error(self, msg):
        line = self.s.count(b"\n", 0, self.i) + 1
        raise LuaParseError(f"{msg} at line {line}")

    def skip(self):
        s, n = self.s, self.n
        while self.i < n:
            c = s[self.i]
            if c in b" \t\r\n":
                self.i += 1
            elif s.startswith(b"--", self.i):
                if s.startswith(b"--[[", self.i):
                    end = s.find(b"]]", self.i)
                    self.i = n if end < 0 else end + 2
                else:
                    end = s.find(b"\n", self.i)
                    self.i = n if end < 0 else end + 1
            else:
                break

    def expect(self, ch: bytes):
        self.skip()
        if not self.s.startswith(ch, self.i):
            self.error(f"expected {ch!r}")
        self.i += len(ch)

    def file(self) -> dict:
        out = {}
        while True:
            self.skip()
            if self.i >= self.n:
                return out
            m = _IDENT.match(self.s, self.i)
            if not m:
                self.error("expected variable name")
            self.i = m.end()
            self.expect(b"=")
            out[m.group().decode()] = self.value()

    def value(self):
        self.skip()
        s, i = self.s, self.i
        if i >= self.n:
            self.error("unexpected end of file")
        c = s[i]
        if c == 0x7B:  # {
            return self.table()
        if c in (0x22, 0x27):  # " '
            return self.string()
        for word, val in ((b"true", True), (b"false", False), (b"nil", None)):
            if s.startswith(word, i) and not _IDENT.match(s, i + len(word)):
                self.i += len(word)
                return val
        m = _NUMBER.match(s, i)
        if m:
            self.i = m.end()
            tok = m.group().decode()
            if tok.lstrip("-").lower().startswith("0x"):
                return int(tok, 16)
            if any(ch in tok for ch in ".eEn"):
                return float(tok)
            return int(tok)
        self.error(f"unexpected character {chr(c)!r}")

    def string(self) -> bytes:
        s = self.s
        quote = s[self.i:self.i + 1]
        special = _STR_SPECIAL[quote]
        self.i += 1
        out = bytearray()
        while True:
            m = special.search(s, self.i)
            if not m:
                self.error("unterminated string")
            out += s[self.i:m.start()]
            self.i = m.start()
            if s[self.i:self.i + 1] == quote:
                self.i += 1
                return bytes(out)
            # backslash escape
            nxt = s[self.i + 1]
            if 48 <= nxt <= 57:
                j = self.i + 1
                while j < self.i + 4 and 48 <= s[j] <= 57:
                    j += 1
                out.append(int(s[self.i + 1:j]) & 0xFF)
                self.i = j
            elif nxt == 13 and s[self.i + 2:self.i + 3] == b"\n":
                out.append(10)
                self.i += 3
            elif nxt in _ESCAPES:
                out.append(_ESCAPES[nxt])
                self.i += 2
            else:
                self.error(f"bad escape \\{chr(nxt)}")

    def table(self) -> dict:
        self.i += 1  # {
        out = {}
        pos = 1
        while True:
            self.skip()
            if self.s.startswith(b"}", self.i):
                self.i += 1
                return out
            if self.s.startswith(b"[", self.i):
                self.i += 1
                key = self.value()
                self.expect(b"]")
                self.expect(b"=")
                if isinstance(key, bytes):
                    key = text(key)
                out[key] = self.value()
            else:
                m = _NAME_ASSIGN.match(self.s, self.i)
                if m:
                    self.i = m.end()
                    out[m.group(1).decode()] = self.value()
                else:
                    out[pos] = self.value()
                    pos += 1
            self.skip()
            if self.i < self.n and self.s[self.i] in b",;":
                self.i += 1


def parse(data: bytes) -> dict:
    """Parse SavedVariables file content into {variable_name: value}."""
    return _Parser(data).file()


def load(path) -> dict:
    with open(path, "rb") as f:
        return parse(f.read())
