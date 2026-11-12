"""Trend analysis over the history store. All prices are in copper."""
from __future__ import annotations

import statistics
import time
from collections import defaultdict

from .auctionator import day_to_date, item_id_from_key

AH_CUT = 0.05  # auction house fee taken from the sale price


# ---------------------------------------------------------------- helpers
def realms(conn) -> list[str]:
    return [r[0] for r in conn.execute("SELECT DISTINCT realm FROM daily ORDER BY realm")]


def latest_day(conn, realm) -> int | None:
    return conn.execute("SELECT max(day) FROM daily WHERE realm=?", (realm,)).fetchone()[0]


def _labels(conn, keys) -> dict[str, dict]:
    """item_key -> {name, quality, icon, item_id} for display."""
    keys = list(keys)
    out = {}
    for start in range(0, len(keys), 500):
        chunk = keys[start:start + 500]
        q = f"""SELECT k.item_key, k.item_id, coalesce(i.name, p.name) AS name, i.quality,
                       coalesce(i.icon, p.icon) AS icon
                FROM item_keys k
                LEFT JOIN items i ON i.item_id = k.item_id
                LEFT JOIN pets p ON k.item_key = 'p:' || p.species_id
                WHERE k.item_key IN ({','.join('?' * len(chunk))})"""
        for r in conn.execute(q, chunk):
            out[r["item_key"]] = dict(r)
    for key in keys:
        info = out.setdefault(key, {"item_key": key, "item_id": None, "name": None,
                                    "quality": None, "icon": None})
        name = info["name"]
        if key.startswith("g:"):
            parts = key.split(":")
            ilvl = f" (ilvl {parts[2]})" if len(parts) > 2 else ""
            info["name"] = (name or f"Item {parts[1]}") + ilvl
        elif key.startswith("p:"):
            info["name"] = name or f"Pet species {key[2:]}"
        elif not name:
            info["name"] = f"Item {key}"
        info["named"] = name is not None
    return out


def _window_rows(conn, realm, first_day, last_day):
    """item_key -> {day: (low, high, available)}"""
    out = defaultdict(dict)
    for r in conn.execute(
            "SELECT item_key, day, low, high, available FROM daily WHERE realm=? AND day BETWEEN ? AND ?",
            (realm, first_day, last_day)):
        out[r["item_key"]][r["day"]] = (r["low"], r["high"], r["available"])
    return out


def _median(values):
    values = [v for v in values if v is not None]
    return statistics.median(values) if values else None


def _attach_labels(conn, rows):
    labels = _labels(conn, [r["item_key"] for r in rows])
    for r in rows:
        r.update({k: v for k, v in labels[r["item_key"]].items() if k != "item_key"})
    return rows


# ---------------------------------------------------------------- views
def overview(conn) -> dict:
    out = {"realms": []}
    for realm in realms(conn):
        row = conn.execute(
            """SELECT count(DISTINCT item_key) items, min(day) first_day, max(day) last_day,
                      count(DISTINCT day) days FROM daily WHERE realm=?""", (realm,)).fetchone()
        out["realms"].append({
            "realm": realm, "items": row["items"], "days_tracked": row["days"],
            "first_date": str(day_to_date(row["first_day"])), "last_date": str(day_to_date(row["last_day"])),
            "last_day": row["last_day"]})
    snap = conn.execute("SELECT count(*) n, max(file_mtime) last_mtime, max(last_scan) last_scan"
                        " FROM snapshots").fetchone()
    names = conn.execute(
        """SELECT count(*) total, sum(i.item_id IS NOT NULL OR p.species_id IS NOT NULL) named
           FROM item_keys k LEFT JOIN items i ON i.item_id = k.item_id
           LEFT JOIN pets p ON k.item_key = 'p:' || p.species_id""").fetchone()
    out.update({"snapshots": snap["n"], "last_file_update": snap["last_mtime"],
                "last_scan": snap["last_scan"], "items_total": names["total"],
                "items_named": names["named"] or 0})
    return out


def movers(conn, realm, window=7, min_prior_days=1, min_price=0, min_available=0,
           direction="both", limit=100) -> dict:
    """Latest day's low price vs the median low of the previous `window` days."""
    today = latest_day(conn, realm)
    if today is None:
        return {"day": None, "rows": []}
    data = _window_rows(conn, realm, today - window, today)
    rows = []
    for key, days in data.items():
        if today not in days:
            continue
        low, high, avail = days[today]
        prior = [days[d][0] for d in days if d < today]
        prior = [p for p in prior if p is not None]
        if low is None or len(prior) < min_prior_days:
            continue
        base = _median(prior)
        if not base or base < min_price or (avail or 0) < min_available:
            continue
        change = low / base - 1
        if (direction == "up" and change <= 0) or (direction == "down" and change >= 0):
            continue
        prior_avail = _median([days[d][2] for d in days if d < today])
        rows.append({"item_key": key, "price": low, "high": high, "baseline": round(base),
                     "change": change, "available": avail, "baseline_available": prior_avail,
                     "prior_days": len(prior)})
    rows.sort(key=lambda r: abs(r["change"]), reverse=True)
    return {"day": today, "date": str(day_to_date(today)), "window": window,
            "rows": _attach_labels(conn, rows[:limit])}


def supply(conn, realm, window=7, min_prior_days=1, min_baseline=5, limit=100) -> dict:
    """Latest day's listing count vs the median of the previous `window` days."""
    today = latest_day(conn, realm)
    if today is None:
        return {"day": None, "rows": []}
    data = _window_rows(conn, realm, today - window, today)
    rows = []
    for key, days in data.items():
        if today not in days or days[today][2] is None:
            continue
        prior = [days[d][2] for d in days if d < today and days[d][2] is not None]
        if len(prior) < min_prior_days:
            continue
        base = _median(prior)
        if not base or base < min_baseline:
            continue
        avail = days[today][2]
        rows.append({"item_key": key, "available": avail, "baseline_available": round(base),
                     "change": avail / base - 1, "price": days[today][0],
                     "baseline_price": _median([days[d][0] for d in days if d < today])})
    rows.sort(key=lambda r: abs(r["change"]), reverse=True)
    return {"day": today, "date": str(day_to_date(today)), "rows": _attach_labels(conn, rows[:limit])}


def vendor_resale(conn, realm, limit=100) -> dict:
    """Items a vendor sells for less than they go for on the AH (after the 5% cut)."""
    today = latest_day(conn, realm)
    rows = []
    for r in conn.execute(
            """SELECT v.item_key, v.price AS vendor, d.low, d.available, d.day
               FROM vendor_prices v
               JOIN daily d ON d.item_key = v.item_key AND d.realm = ?
               WHERE d.day = (SELECT max(day) FROM daily WHERE realm = ? AND item_key = v.item_key)""",
            (realm, realm)):
        if r["low"] is None:
            continue
        profit = r["low"] * (1 - AH_CUT) - r["vendor"]
        if profit <= 0:
            continue
        rows.append({"item_key": r["item_key"], "vendor_price": r["vendor"], "price": r["low"],
                     "profit": profit, "margin": profit / r["vendor"] if r["vendor"] else None,
                     "available": r["available"], "date": str(day_to_date(r["day"])),
                     "days_old": (today - r["day"]) if today is not None else None})
    rows.sort(key=lambda r: r["profit"], reverse=True)
    return {"rows": _attach_labels(conn, rows[:limit])}


def search(conn, query, realm, limit=40) -> list[dict]:
    query = (query or "").strip()
    if not query:
        return []
    if query.isdigit():
        keys = [r[0] for r in conn.execute(
            "SELECT item_key FROM item_keys WHERE item_key = ? OR item_id = ? OR item_key LIKE ? LIMIT ?",
            (query, int(query), query + "%", limit))]
    else:
        like = f"%{query}%"
        keys = [r[0] for r in conn.execute(
            """SELECT k.item_key FROM item_keys k
               LEFT JOIN items i ON i.item_id = k.item_id
               LEFT JOIN pets p ON k.item_key = 'p:' || p.species_id
               WHERE coalesce(i.name, p.name) LIKE ?
               ORDER BY length(coalesce(i.name, p.name)), coalesce(i.name, p.name) LIMIT ?""",
            (like, limit))]
    prices = {r["item_key"]: r for r in conn.execute(
        f"""SELECT d.item_key, d.low, d.day FROM daily d
            WHERE d.realm = ? AND d.item_key IN ({','.join('?' * len(keys))})
              AND d.day = (SELECT max(day) FROM daily WHERE realm = d.realm AND item_key = d.item_key)""",
        [realm, *keys])} if keys else {}
    rows = [{"item_key": k, "price": prices[k]["low"] if k in prices else None,
             "date": str(day_to_date(prices[k]["day"])) if k in prices else None} for k in keys]
    return _attach_labels(conn, rows)


def item_detail(conn, realm, item_key) -> dict | None:
    hist = [dict(r) for r in conn.execute(
        "SELECT day, low, high, available FROM daily WHERE realm=? AND item_key=? ORDER BY day",
        (realm, item_key))]
    if not hist and not conn.execute("SELECT 1 FROM item_keys WHERE item_key=?", (item_key,)).fetchone():
        return None
    for h in hist:
        h["date"] = str(day_to_date(h["day"]))
    latest = conn.execute("SELECT price, ts FROM latest WHERE realm=? AND item_key=?",
                          (realm, item_key)).fetchone()
    vendor = conn.execute("SELECT price FROM vendor_prices WHERE item_key=?", (item_key,)).fetchone()
    postings = [dict(r) for r in conn.execute(
        "SELECT time, price, quantity FROM postings WHERE item_key=? ORDER BY time", (item_key,))]
    watch = conn.execute("SELECT below, above, note FROM watchlist WHERE item_key=?", (item_key,)).fetchone()

    def stats(days):
        last = hist[-1]["day"] if hist else 0
        lows = [h["low"] for h in hist if h["day"] > last - days and h["low"] is not None]
        if not lows:
            return None
        return {"median": round(statistics.median(lows)), "min": min(lows), "max": max(lows), "days": len(lows)}

    info = _labels(conn, [item_key])[item_key]
    return {**info, "realm": realm, "history": hist,
            "current": latest["price"] if latest else None, "current_ts": latest["ts"] if latest else None,
            "vendor_price": vendor["price"] if vendor else None, "postings": postings,
            "stats": {"7": stats(7), "30": stats(30), "all": stats(10 ** 6)},
            "watch": dict(watch) if watch else None}


def watchlist(conn, realm) -> dict:
    today = latest_day(conn, realm)
    rows = []
    for w in conn.execute("SELECT * FROM watchlist ORDER BY added_at"):
        key = w["item_key"]
        hist = conn.execute(
            "SELECT day, low, available FROM daily WHERE realm=? AND item_key=? AND day > ? ORDER BY day",
            (realm, key, (today or 0) - 30)).fetchall()
        last = hist[-1] if hist else None
        price = last["low"] if last else None
        base = _median([h["low"] for h in hist[:-1]]) if len(hist) > 1 else None
        alert = None
        if price is not None and w["below"] is not None and price <= w["below"]:
            alert = "below"
        elif price is not None and w["above"] is not None and price >= w["above"]:
            alert = "above"
        rows.append({"item_key": key, "below": w["below"], "above": w["above"], "note": w["note"],
                     "price": price, "available": last["available"] if last else None,
                     "date": str(day_to_date(last["day"])) if last else None,
                     "baseline": round(base) if base else None,
                     "change": (price / base - 1) if price and base else None,
                     "spark": [h["low"] for h in hist], "alert": alert})
    return {"rows": _attach_labels(conn, rows)}


def set_watch(conn, item_key, below=None, above=None, note=None):
    with conn:
        conn.execute("INSERT OR IGNORE INTO item_keys (item_key, item_id) VALUES (?, ?)",
                     (item_key, item_id_from_key(item_key)))
        conn.execute(
            """INSERT INTO watchlist (item_key, below, above, note, added_at) VALUES (?,?,?,?,?)
               ON CONFLICT (item_key) DO UPDATE SET below=excluded.below, above=excluded.above,
                 note=excluded.note""", (item_key, below, above, note, int(time.time())))


def remove_watch(conn, item_key):
    with conn:
        conn.execute("DELETE FROM watchlist WHERE item_key=?", (item_key,))


def my_postings(conn, realm, limit=200) -> dict:
    rows = []
    for p in conn.execute("SELECT * FROM postings ORDER BY time DESC LIMIT ?", (limit,)):
        cur = conn.execute(
            """SELECT low, day FROM daily WHERE realm=? AND item_key=? ORDER BY day DESC LIMIT 1""",
            (realm, p["item_key"])).fetchone()
        rows.append({"item_key": p["item_key"], "time": p["time"], "posted_price": p["price"],
                     "quantity": p["quantity"], "price": cur["low"] if cur else None,
                     "change": (cur["low"] / p["price"] - 1) if cur and cur["low"] and p["price"] else None})
    return {"rows": _attach_labels(conn, rows)}
