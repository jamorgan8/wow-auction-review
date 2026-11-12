"""Minimal CBOR (RFC 8949) decoder - enough for WoW's C_EncodingUtil.SerializeCBOR output.

Text and byte strings are returned as ``str`` when they are valid UTF-8 (WoW
serializes Lua strings as byte strings), otherwise as ``bytes``. Maps become
dicts, arrays become lists.
"""
from __future__ import annotations

import struct


class CBORError(ValueError):
    pass


_BREAK = object()


def _decode(b: bytes, i: int):
    if i >= len(b):
        raise CBORError("truncated CBOR data")
    ib = b[i]
    major, info = ib >> 5, ib & 31
    i += 1

    if major == 7:
        if info == 20:
            return False, i
        if info == 21:
            return True, i
        if info in (22, 23):
            return None, i
        if info == 25:
            return struct.unpack(">e", b[i:i + 2])[0], i + 2
        if info == 26:
            return struct.unpack(">f", b[i:i + 4])[0], i + 4
        if info == 27:
            return struct.unpack(">d", b[i:i + 8])[0], i + 8
        if info == 31:
            return _BREAK, i
        if info < 24:
            return info, i  # unassigned simple value
        raise CBORError(f"unsupported simple value {info}")

    indefinite = info == 31
    if info < 24:
        arg = info
    elif info == 24:
        arg = b[i]; i += 1
    elif info == 25:
        arg = struct.unpack(">H", b[i:i + 2])[0]; i += 2
    elif info == 26:
        arg = struct.unpack(">I", b[i:i + 4])[0]; i += 4
    elif info == 27:
        arg = struct.unpack(">Q", b[i:i + 8])[0]; i += 8
    elif indefinite and major in (2, 3, 4, 5):
        arg = None
    else:
        raise CBORError(f"bad additional info {info} for major type {major}")

    if major == 0:
        return arg, i
    if major == 1:
        return -1 - arg, i
    if major in (2, 3):
        if indefinite:
            parts = []
            while True:
                part, i = _decode(b, i)
                if part is _BREAK:
                    return "".join(parts), i
                parts.append(part)
        raw = b[i:i + arg]
        try:
            return raw.decode("utf-8"), i + arg
        except UnicodeDecodeError:
            return bytes(raw), i + arg  # binary payload (e.g. a nested CBOR blob)
    if major == 4:
        out = []
        while indefinite or len(out) < arg:
            v, i = _decode(b, i)
            if v is _BREAK:
                break
            out.append(v)
        return out, i
    if major == 5:
        out = {}
        count = 0
        while indefinite or count < arg:
            k, i = _decode(b, i)
            if k is _BREAK:
                break
            v, i = _decode(b, i)
            out[k] = v
            count += 1
        return out, i
    if major == 6:  # tag: ignore and return the tagged value
        return _decode(b, i)
    raise CBORError(f"unknown major type {major}")


def loads(data: bytes):
    value, end = _decode(data, 0)
    if end != len(data):
        raise CBORError(f"trailing data: decoded {end} of {len(data)} bytes")
    return value
