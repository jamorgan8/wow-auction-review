"""Command line: python -m auction_review [serve|ingest|status|install-addon]"""
from __future__ import annotations

import argparse
import logging
import shutil
import sys
from pathlib import Path

from . import analysis, names, paths, store


def _file(args) -> Path:
    if args.file:
        f = Path(args.file)
        cfg = paths.load_config()
        cfg["auctionator_file"] = str(f)
        paths.save_config(cfg)
    else:
        f = paths.find_auctionator_file()
    if not f or not f.is_file():
        sys.exit("Could not find Auctionator.lua. Pass --file "
                 r'"<WoW>\_forever_\WTF\Account\<ACCOUNT>\SavedVariables\Auctionator.lua"')
    return f


def gold(c):
    if c is None:
        return "-"
    c = int(round(c))
    g, s, cp = c // 10000, c // 100 % 100, c % 100
    return " ".join(p for p in (f"{g}g" if g else "", f"{s}s" if s else "", f"{cp}c" if cp or not c else "") if p)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="auction_review", description="Auctionator price-trend dashboard")
    ap.add_argument("--file", help="path to the account-wide Auctionator.lua")
    sub = ap.add_subparsers(dest="cmd")
    s = sub.add_parser("serve", help="run the dashboard (default)")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--no-browser", action="store_true")
    s.add_argument("--no-web-names", action="store_true", help="don't look up item names on Wowhead")
    sub.add_parser("ingest", help="import the current Auctionator data once")
    sub.add_parser("status", help="show what's in the history database")
    sub.add_parser("install-addon", help="copy the AuctionReviewNames addon into WoW's AddOns folder")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    f = _file(args)
    cmd = args.cmd or "serve"

    if cmd == "serve":
        from .server import serve
        serve(f, port=getattr(args, "port", 8765), open_browser=not getattr(args, "no_browser", False),
              web_names=not getattr(args, "no_web_names", False))
    elif cmd == "ingest":
        conn = store.connect()
        for r in store.ingest(conn, f):
            print(r)
        print("names from addon:", names.import_addon_names(conn, paths.names_file_for(f)))
        print("names from item links:", names.harvest_links(conn, f.parent.parent))
    elif cmd == "status":
        conn = store.connect()
        ov = analysis.overview(conn)
        print(f"Source: {f}")
        print(f"Snapshots ingested: {ov['snapshots']}; items named: {ov['items_named']}/{ov['items_total']}")
        for r in ov["realms"]:
            print(f"  {r['realm']}: {r['items']} items, {r['days_tracked']} days ({r['first_date']} .. {r['last_date']})")
            for m in analysis.movers(conn, r["realm"], limit=5)["rows"]:
                print(f"    {m['change']:+.0%}  {m['name']}: {gold(m['price'])} (was ~{gold(m['baseline'])})")
    elif cmd == "install-addon":
        src = paths.PROJECT_DIR / "companion_addon" / "AuctionReviewNames"
        dest = paths.addons_dir_for(f) / "AuctionReviewNames"
        if not dest.parent.is_dir():
            sys.exit(f"AddOns folder not found: {dest.parent}")
        shutil.copytree(src, dest, dirs_exist_ok=True)
        print(f"Installed to {dest}\nRestart WoW (or /reload), wait ~1 minute, then /reload or log out to save names.")


if __name__ == "__main__":
    main()
