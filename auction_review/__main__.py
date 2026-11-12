"""Command line: auction-review [serve|ingest|status|install-addon]"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from . import __version__, analysis, names, paths, store


def _file(args, required=True) -> Path | None:
    if args.file:
        found = paths.candidates_under(Path(args.file))
        if not found:
            sys.exit(f"No Auctionator.lua found at {args.file}")
        paths.set_auctionator_file(found[0])
        return found[0]
    f = paths.find_auctionator_file()
    if f is None and required:
        sys.exit("Could not find Auctionator data. Pass --file with your World of Warcraft folder, e.g.\n"
                 r'  auction-review --file "C:\Program Files (x86)\World of Warcraft" ' + args.cmd)
    return f


def gold(c):
    if c is None:
        return "-"
    c = int(round(c))
    g, s, cp = c // 10000, c // 100 % 100, c % 100
    return " ".join(p for p in (f"{g}g" if g else "", f"{s}s" if s else "", f"{cp}c" if cp or not c else "") if p)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="auction-review", description="Auctionator price-trend dashboard")
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    ap.add_argument("--file", help="your World of Warcraft folder, or the account-wide Auctionator.lua")
    sub = ap.add_subparsers(dest="cmd")
    s = sub.add_parser("serve", help="run the dashboard (default)")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--no-browser", action="store_true")
    s.add_argument("--web-names", action="store_true",
                   help="also look up missing item names on Wowhead (off by default; the companion addon "
                        "is the recommended name source)")
    s.add_argument("--no-web-names", action="store_true", help=argparse.SUPPRESS)  # old flag, now the default
    sub.add_parser("ingest", help="import the current Auctionator data once")
    sub.add_parser("status", help="show what's in the history database")
    sub.add_parser("install-addon", help="copy the AuctionReviewNames addon into WoW's AddOns folder")
    args = ap.parse_args(argv)
    args.cmd = args.cmd or "serve"
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    paths.migrate_legacy_data()

    if args.cmd == "serve":
        from .server import serve
        serve(_file(args, required=False), port=getattr(args, "port", 8765),
              open_browser=not getattr(args, "no_browser", False),
              web_names=getattr(args, "web_names", False))
        return

    f = _file(args)
    if args.cmd == "ingest":
        conn = store.connect()
        for r in store.ingest(conn, f):
            print(r)
        print("names from addon:", names.import_addon_names(conn, paths.names_file_for(f)))
        print("names from item links:", names.harvest_links(conn, f.parent.parent))
    elif args.cmd == "status":
        conn = store.connect()
        ov = analysis.overview(conn)
        print(f"Source: {f}\nData folder: {paths.DATA_DIR}")
        print(f"Snapshots ingested: {ov['snapshots']}; items named: {ov['items_named']}/{ov['items_total']}")
        for r in ov["realms"]:
            print(f"  {r['realm']}: {r['items']} items, {r['days_tracked']} days ({r['first_date']} .. {r['last_date']})")
            for m in analysis.movers(conn, r["realm"], limit=5)["rows"]:
                print(f"    {m['change']:+.0%}  {m['name']}: {gold(m['price'])} (was ~{gold(m['baseline'])})")
    elif args.cmd == "install-addon":
        try:
            dest = paths.install_addon(f)
        except FileNotFoundError as e:
            sys.exit(str(e))
        print(f"Installed to {dest}\nRestart WoW (or /reload), wait ~1 minute, then /reload or log out to save names.")


if __name__ == "__main__":
    main()
