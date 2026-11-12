# Auction Review

A local dashboard for spotting price trends in the World of Warcraft (Forever) Auction House, built on
the data the **Auctionator** addon already saves.

Auctionator only keeps 21 days of daily prices and prunes the rest. This tool copies every snapshot
into its own SQLite database (`data/auction_review.db`), so history keeps growing for as long as you use it.

## Start

Double-click `start_dashboard.bat`, or:

```
python -m auction_review
```

The dashboard opens at http://127.0.0.1:8765. Keep it running: it checks `Auctionator.lua` every
20 seconds and imports new data automatically. Python 3.10+ only, no packages to install.

**WoW only writes the file when you log out or type `/reload`.** Scan the AH with Auctionator, `/reload`,
and the dashboard updates within a minute.

## Item names

Auctionator stores item IDs only. Names come from, in order:

1. **The companion addon** (recommended, covers WoW Forever's new items):
   `python -m auction_review install-addon` copies `companion_addon/AuctionReviewNames` into WoW's
   AddOns folder. Log in, wait about a minute, then `/reload`. `/arnames` in game shows progress.
2. Item links found in your other SavedVariables files.
3. Wowhead lookups in the background (classic-era items only; disable with `--no-web-names`).

## Dashboard tabs

| Tab | What it shows |
| --- | --- |
| Price movers | Latest day's lowest price vs. the median of the previous N days. Drops = possible deals, rises = selling chances. |
| Supply | Units listed today vs. usual. Shrinking supply often comes before a price rise. |
| Vendor resale | Items a vendor sells for less than the AH price after the 5% cut. |
| Watchlist | Items you chose, with "alert below / above" targets and a 30-day sparkline. |
| My postings | Your Auctionator posting history vs. the current market. |

Click any item for its full history chart (daily low/high band, units listed, your postings).

## Commands

```
python -m auction_review serve [--port 8765] [--no-browser] [--no-web-names]
python -m auction_review ingest         # import once, no server
python -m auction_review status         # summary + top movers in the terminal
python -m auction_review install-addon
python -m auction_review --file "<path>\Auctionator.lua" ...   # use a specific file (remembered in config.json)
```

## How the data is read

`Auctionator.lua` → `AUCTIONATOR_PRICE_DATABASE[realm]` is a CBOR blob (`C_EncodingUtil.SerializeCBOR`).
Each item key (`"2589"`, `"g:<itemID>:<ilvl>"` for gear, `"p:<speciesID>"` for pets) holds:

- `m`: cheapest buyout seen in the most recent scan
- `l[day]` / `h[day]`: lowest / highest "cheapest listing" seen that day
- `a[day]`: most units seen listed that day

Days are counted from 2020-01-01. Prices are copper. The tool never writes to WoW's files; it copies
them before reading.

## Tests

```
python -m unittest discover -s tests
```
