"""Item name resolution.

Sources, best first:
  1. the AuctionReviewNames companion addon's SavedVariables (exact, covers WoW Forever items)
  2. item links found in any SavedVariables file ("|Hitem:2589:...|h[Linen Cloth]|h")
  3. Wowhead tooltip lookups (only knows items that exist on Wowhead)
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
import urllib.error
import urllib.request
from pathlib import Path

from .lua_sv import load, text

log = logging.getLogger(__name__)
_LINK = re.compile(rb"Hitem:(\d+)[^|]*\|h\[([^\]]+)\]")
_WOWHEAD = "https://nether.wowhead.com/tooltip/item/{}"
_SOURCE_RANK = {"addon": 3, "link": 2, "wowhead": 1}
RETRY_FAILED_AFTER = 7 * 86400


def _upsert(conn, rows, source):
    """rows: (item_id, name, quality, icon). Never let a weaker source overwrite a stronger one."""
    now = int(time.time())
    existing = {r["item_id"]: r["source"] for r in conn.execute("SELECT item_id, source FROM items")}
    rank = _SOURCE_RANK[source]
    # quality ends up in an HTML class name on the dashboard, so only ever store a plain integer
    todo = [(i, n, q if type(q) is int else None, ic, source, now) for i, n, q, ic in rows
            if _SOURCE_RANK.get(existing.get(i), 0) <= rank]
    conn.executemany(
        """INSERT INTO items (item_id, name, quality, icon, source, updated_at) VALUES (?,?,?,?,?,?)
           ON CONFLICT (item_id) DO UPDATE SET name=excluded.name,
             quality=coalesce(excluded.quality, items.quality), icon=coalesce(excluded.icon, items.icon),
             source=excluded.source, updated_at=excluded.updated_at""", todo)
    return len(todo)


def import_addon_names(conn: sqlite3.Connection, names_file: Path) -> int:
    if not names_file.is_file():
        return 0
    sv = load(names_file)
    rows = []
    for item_id, info in (sv.get("AUCTION_REVIEW_ITEM_NAMES") or {}).items():
        if isinstance(item_id, int) and isinstance(info, dict) and info.get("name"):
            icon = info.get("icon")
            rows.append((item_id, text(info["name"]), info.get("quality"),
                         str(icon) if icon is not None else None))
    pets = []
    for species, info in (sv.get("AUCTION_REVIEW_PET_NAMES") or {}).items():
        if isinstance(species, int) and isinstance(info, dict) and info.get("name"):
            icon = info.get("icon")
            pets.append((species, text(info["name"]), str(icon) if icon is not None else None))
    with conn:
        n = _upsert(conn, rows, "addon")
        conn.executemany("INSERT OR REPLACE INTO pets (species_id, name, icon) VALUES (?,?,?)", pets)
    return n + len(pets)


def harvest_links(conn: sqlite3.Connection, account_dir: Path) -> int:
    """Scan every SavedVariables .lua under the account folder for item links."""
    found = {}
    for f in account_dir.rglob("*.lua"):
        try:
            for m in _LINK.finditer(f.read_bytes()):
                found[int(m.group(1))] = m.group(2).decode("utf-8", "replace")
        except OSError:
            continue
    with conn:
        return _upsert(conn, [(i, n, None, None) for i, n in found.items()], "link")


def missing_item_ids(conn: sqlite3.Connection) -> list[int]:
    cutoff = int(time.time()) - RETRY_FAILED_AFTER
    return [r[0] for r in conn.execute(
        """SELECT DISTINCT k.item_id FROM item_keys k
           LEFT JOIN items i ON i.item_id = k.item_id
           LEFT JOIN name_lookups l ON l.item_id = k.item_id
           WHERE k.item_id IS NOT NULL AND i.item_id IS NULL
             AND (l.item_id IS NULL OR l.tried_at < ?)
           ORDER BY k.item_id""", (cutoff,))]


def fetch_wowhead(conn: sqlite3.Connection, item_ids, delay=0.25, stop=None) -> int:
    """Look up names on Wowhead, one request at a time. Returns names found."""
    found = 0
    for item_id in item_ids:
        if stop is not None and stop.is_set():
            break
        status, row = "missing", None
        try:
            req = urllib.request.Request(_WOWHEAD.format(item_id),
                                         headers={"User-Agent": "auction-review/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                d = json.load(resp)
            if d.get("name"):
                row = (item_id, d["name"], d.get("quality"), d.get("icon"))
                status = "ok"
        except urllib.error.HTTPError as e:
            status = "missing" if e.code == 404 else f"http {e.code}"
        except (urllib.error.URLError, OSError, ValueError) as e:
            log.info("wowhead lookup stopped: %s", e)
            break  # offline: try again on a later run
        with conn:
            if row:
                found += _upsert(conn, [row], "wowhead")
            conn.execute("INSERT OR REPLACE INTO name_lookups (item_id, status, tried_at) VALUES (?,?,?)",
                         (item_id, status, int(time.time())))
        time.sleep(delay)
    return found
