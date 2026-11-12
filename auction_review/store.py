"""SQLite history store. Keeps every day ever seen, beyond Auctionator's own pruning."""
from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
import tempfile
import time
from pathlib import Path

from . import auctionator
from .paths import DATA_DIR, DB_FILE

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY,
    sha1 TEXT UNIQUE NOT NULL,
    source TEXT NOT NULL,
    file_mtime INTEGER NOT NULL,
    last_scan INTEGER,
    ingested_at INTEGER NOT NULL,
    item_count INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS daily (
    realm TEXT NOT NULL,
    item_key TEXT NOT NULL,
    day INTEGER NOT NULL,
    low INTEGER,
    high INTEGER,
    available INTEGER,
    PRIMARY KEY (realm, item_key, day)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS daily_by_day ON daily (realm, day);
CREATE TABLE IF NOT EXISTS latest (
    realm TEXT NOT NULL,
    item_key TEXT NOT NULL,
    price INTEGER,
    ts INTEGER NOT NULL,
    PRIMARY KEY (realm, item_key)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS item_keys (
    item_key TEXT PRIMARY KEY,
    item_id INTEGER
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS items (
    item_id INTEGER PRIMARY KEY,
    name TEXT,
    quality INTEGER,
    icon TEXT,
    source TEXT,
    updated_at INTEGER
);
CREATE TABLE IF NOT EXISTS pets (
    species_id INTEGER PRIMARY KEY,
    name TEXT,
    icon TEXT
);
CREATE TABLE IF NOT EXISTS name_lookups (
    item_id INTEGER PRIMARY KEY,
    status TEXT,
    tried_at INTEGER
);
CREATE TABLE IF NOT EXISTS postings (
    item_key TEXT NOT NULL,
    time INTEGER NOT NULL,
    price INTEGER NOT NULL,
    quantity INTEGER NOT NULL,
    PRIMARY KEY (item_key, time, price, quantity)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS vendor_prices (
    item_key TEXT PRIMARY KEY,
    price REAL NOT NULL,
    updated_at INTEGER NOT NULL
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS watchlist (
    item_key TEXT PRIMARY KEY,
    below INTEGER,
    above INTEGER,
    note TEXT,
    added_at INTEGER NOT NULL
) WITHOUT ROWID;
"""


def connect(db_file: Path = DB_FILE) -> sqlite3.Connection:
    db_file.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_file, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(SCHEMA)
    return conn


def _copy_stable(path: Path) -> tuple[Path, int]:
    """Copy the file so we never read it while WoW is mid-write; retry until it is stable."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="sv_", suffix=".lua", dir=DATA_DIR)
    os.close(fd)
    tmp = Path(name)
    for _ in range(10):
        before = path.stat()
        shutil.copyfile(path, tmp)
        after = path.stat()
        if (before.st_mtime_ns, before.st_size) == (after.st_mtime_ns, after.st_size):
            return tmp, int(after.st_mtime)
        time.sleep(1)
    return tmp, int(path.stat().st_mtime)


def ingest_file(conn: sqlite3.Connection, path: Path) -> dict:
    """Merge one Auctionator.lua (or .bak) into the store. Returns a summary."""
    path = Path(path)
    copy, mtime = _copy_stable(path)
    try:
        raw = copy.read_bytes()
        sha1 = hashlib.sha1(raw).hexdigest()
        if conn.execute("SELECT 1 FROM snapshots WHERE sha1=?", (sha1,)).fetchone():
            return {"file": str(path), "status": "unchanged"}
        data = auctionator.read(copy)
    finally:
        copy.unlink(missing_ok=True)

    now = int(time.time())
    ts = data.last_scan or mtime
    item_count = sum(len(items) for items in data.realms.values())
    with conn:
        conn.execute(
            "INSERT INTO snapshots (sha1, source, file_mtime, last_scan, ingested_at, item_count)"
            " VALUES (?,?,?,?,?,?)", (sha1, str(path), mtime, data.last_scan, now, item_count))

        daily_rows, latest_rows, keys = [], [], set()
        for realm, items in data.realms.items():
            for key, prices in items.items():
                keys.add(key)
                if prices.current is not None:
                    latest_rows.append((realm, key, prices.current, ts))
                for day, (low, high, avail) in prices.days.items():
                    daily_rows.append((realm, key, day, low, high, avail))

        conn.executemany(
            """INSERT INTO daily (realm, item_key, day, low, high, available) VALUES (?,?,?,?,?,?)
               ON CONFLICT (realm, item_key, day) DO UPDATE SET
                 low = min(coalesce(low, excluded.low), coalesce(excluded.low, low)),
                 high = max(coalesce(high, excluded.high), coalesce(excluded.high, high)),
                 available = max(coalesce(available, excluded.available),
                                 coalesce(excluded.available, available))""", daily_rows)
        conn.executemany(
            """INSERT INTO latest (realm, item_key, price, ts) VALUES (?,?,?,?)
               ON CONFLICT (realm, item_key) DO UPDATE SET price = excluded.price, ts = excluded.ts
               WHERE excluded.ts >= latest.ts""", latest_rows)

        keys |= set(data.postings) | set(data.vendor_prices)
        conn.executemany("INSERT OR IGNORE INTO item_keys (item_key, item_id) VALUES (?,?)",
                         [(k, auctionator.item_id_from_key(k)) for k in keys])
        conn.executemany(
            "INSERT OR IGNORE INTO postings (item_key, time, price, quantity) VALUES (?,?,?,?)",
            [(k, p["time"], p["price"], p["quantity"]) for k, ps in data.postings.items() for p in ps])
        conn.executemany(
            """INSERT INTO vendor_prices (item_key, price, updated_at) VALUES (?,?,?)
               ON CONFLICT (item_key) DO UPDATE SET price = excluded.price, updated_at = excluded.updated_at
               WHERE excluded.updated_at >= vendor_prices.updated_at""",
            [(k, p, mtime) for k, p in data.vendor_prices.items()])

    return {"file": str(path), "status": "ingested", "items": item_count,
            "day_rows": len(daily_rows), "realms": list(data.realms)}


def ingest(conn: sqlite3.Connection, auctionator_file: Path) -> list[dict]:
    """Ingest the backup first (older), then the live file."""
    results = []
    for p in (auctionator_file.with_name(auctionator_file.name + ".bak"), auctionator_file):
        if p.is_file():
            results.append(ingest_file(conn, p))
    return results
