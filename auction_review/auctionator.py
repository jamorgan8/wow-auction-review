"""Read Auctionator's SavedVariables into plain Python structures."""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field

from . import cbor
from .lua_sv import as_list, load, text

# Auctionator.Constants.SCAN_DAY_0 = time({year=2020, month=1, day=1, hour=0})
DAY0 = dt.date(2020, 1, 1)
_KEY_ITEM_ID = re.compile(r"^(?:g:)?(\d+)")


def day_to_date(day: int) -> dt.date:
    return DAY0 + dt.timedelta(days=int(day))


def date_to_day(date: dt.date) -> int:
    return (date - DAY0).days


def item_id_from_key(key: str) -> int | None:
    """'2589' -> 2589, 'g:12345:200' -> 12345, 'p:123' (pet species) -> None."""
    m = _KEY_ITEM_ID.match(key)
    return int(m.group(1)) if m else None


@dataclass
class ItemPrices:
    current: int | None                       # Auctionator's "m": last lowest buyout seen
    days: dict[int, tuple[int | None, int | None, int | None]]  # day -> (low, high, available)


@dataclass
class AuctionatorData:
    realms: dict[str, dict[str, ItemPrices]] = field(default_factory=dict)
    postings: dict[str, list[dict]] = field(default_factory=dict)  # key -> [{price, quantity, time}]
    vendor_prices: dict[str, float] = field(default_factory=dict)  # key -> vendor buy price per unit
    last_scan: int | None = None


def _as_dict(value) -> dict:
    # Empty Lua tables serialize as CBOR arrays.
    return value if isinstance(value, dict) else {}


def _int_or_none(v):
    return None if v is None else int(round(v))


def _parse_item(raw) -> ItemPrices | None:
    if isinstance(raw, (bytes, str)) and raw:  # older per-item CBOR format
        raw = cbor.loads(raw if isinstance(raw, bytes) else raw.encode("utf-8"))
    if not isinstance(raw, dict):
        return None
    lows, highs, avail = (_as_dict(raw.get(k)) for k in ("l", "h", "a"))
    days = {}
    for d in set(lows) | set(highs) | set(avail):
        try:
            day = int(d)
        except (TypeError, ValueError):
            continue
        high = _int_or_none(highs.get(d))
        low = _int_or_none(lows.get(d))
        if low is None:
            low = high  # Auctionator: minSeen = l[day] or h[day]
        days[day] = (low, high, _int_or_none(avail.get(d)))
    return ItemPrices(current=_int_or_none(raw.get("m")), days=days)


def _parse_realm(raw) -> dict[str, ItemPrices]:
    if isinstance(raw, bytes):
        raw = cbor.loads(raw)
    items = {}
    for key, value in _as_dict(raw).items():
        if key in ("version", "__dbversion"):
            continue
        parsed = _parse_item(value)
        if parsed is not None:
            items[str(key)] = parsed
    return items


def read(path) -> AuctionatorData:
    sv = load(path)
    data = AuctionatorData()

    for realm, raw in _as_dict(sv.get("AUCTIONATOR_PRICE_DATABASE")).items():
        if realm == "__dbversion":
            continue
        data.realms[str(realm)] = _parse_realm(raw)

    for key, entries in _as_dict(sv.get("AUCTIONATOR_POSTING_HISTORY")).items():
        if key == "__dbversion":
            continue
        rows = []
        for e in as_list(entries):
            if isinstance(e, dict) and e.get("price") is not None:
                rows.append({"price": int(e["price"]), "quantity": int(e.get("quantity") or 1),
                             "time": int(e.get("time") or 0)})
        if rows:
            data.postings[str(key)] = rows

    for key, price in _as_dict(sv.get("AUCTIONATOR_VENDOR_PRICE_CACHE")).items():
        if key != "__dbversion" and isinstance(price, (int, float)):
            data.vendor_prices[str(key)] = float(price)

    saved = _as_dict(sv.get("AUCTIONATOR_SAVEDVARS"))
    if isinstance(saved.get("TimeOfLastBrowseScan"), (int, float)):
        data.last_scan = int(saved["TimeOfLastBrowseScan"])
    return data


__all__ = ["AuctionatorData", "ItemPrices", "read", "day_to_date", "date_to_day",
           "item_id_from_key", "text"]
