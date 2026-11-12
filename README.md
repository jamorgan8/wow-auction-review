# Auction Review

A local dashboard for spotting price trends in the World of Warcraft auction house, built on
the data the **Auctionator** addon already saves. Everything runs on your own PC.

Auctionator only keeps 21 days of daily prices and prunes the rest. Auction Review copies every
snapshot into its own database, so history keeps growing for as long as you use it.

## Install

You need the **Auctionator** addon, at least one AH scan, and a logout or `/reload`
(WoW only writes addon data to disk then).

### Windows app (no Python needed)

1. Download `AuctionReview-<version>-windows.zip` from the
   [latest release](https://github.com/jamorgan8/wow-auction-review/releases/latest) and unzip it.
2. Double-click `AuctionReview.exe`. The dashboard opens in your browser.
   Windows may say it "protected your PC" because the app isn't code-signed: click
   **More info → Run anyway**. Some antivirus tools also flag unsigned Python-built apps by
   mistake. To confirm your download is the file GitHub built, compare its SHA-256 with the
   one in the release notes: `certutil -hashfile AuctionReview-<version>-windows.zip SHA256`.
   If you'd rather not run an exe, use the Python install below.
3. If WoW isn't found automatically, the dashboard asks for your World of Warcraft folder.
4. Click **Install addon** on the dashboard to add the companion name addon (see below).

Leave the console window open while you play; close it to stop.

### With Python 3.10+ (any OS)

```
pipx install git+https://github.com/jamorgan8/wow-auction-review
auction-review
```

(`pip install git+https://...` also works.) There are no third-party dependencies.

### From a checkout

```
python -m auction_review
```

or double-click `start_dashboard.bat`.

## Item names

Auctionator stores item IDs only. Names come from, best first:

1. **The companion addon** `AuctionReviewNames`. It reads names from the game client, so it
   covers every item, including WoW Forever's new ones. Install it with the dashboard's
   **Install addon** button, `auction-review install-addon`, or by copying the folder from the
   release zip into `Interface\AddOns`. Log in, wait about a minute, then `/reload`.
   `/arnames` in game shows progress.
2. Item links found in your other SavedVariables files.
3. Optional: Wowhead lookups for items still unnamed, if you start with `--web-names`. Off by
   default; it only knows items that exist on Wowhead, and sends nothing but item IDs.

## Dashboard tabs

| Tab | What it shows |
| --- | --- |
| Price movers | Latest day's lowest price vs. the median of the previous N days. Drops = possible deals, rises = selling chances. |
| Supply | Units listed today vs. usual. Shrinking supply often comes before a price rise. |
| Vendor resale | Items a vendor sells for less than the AH price after the 5% cut. |
| Watchlist | Items you chose, with "alert below / above" targets and a 30-day sparkline. |
| My postings | Your Auctionator posting history vs. the current market. |

Click any item for its full history chart (daily low/high band, units listed, your postings).

## Where data is kept

| OS | Folder |
| --- | --- |
| Windows | `%LOCALAPPDATA%\AuctionReview` |
| macOS | `~/Library/Application Support/AuctionReview` |
| Linux | `~/.local/share/auction-review` |

It holds `auction_review.db` (price history, names, watchlist) and `config.json` (which WoW
folder to read). Set `AUCTION_REVIEW_HOME` to use a different folder. The tool never writes to
WoW's SavedVariables; it copies them before reading. The only files it adds to WoW are the
companion addon's, and only when you ask it to install them.

## Commands

```
auction-review [serve] [--port 8765] [--no-browser] [--web-names]
auction-review ingest            # import once, no server
auction-review status            # summary + top movers in the terminal
auction-review install-addon
auction-review --file "<World of Warcraft folder>" serve   # pick the WoW install (remembered)
```

From a checkout, use `python -m auction_review` in place of `auction-review`.

## How the data is read

`Auctionator.lua` → `AUCTIONATOR_PRICE_DATABASE[realm]` is a CBOR blob (`C_EncodingUtil.SerializeCBOR`).
Each item key (`"2589"`, `"g:<itemID>:<ilvl>"` for gear, `"p:<speciesID>"` for pets) holds:

- `m`: cheapest buyout seen in the most recent scan
- `l[day]` / `h[day]`: lowest / highest "cheapest listing" seen that day
- `a[day]`: most units seen listed that day

Days are counted from 2020-01-01. Prices are in copper.

## Development

```
python -m unittest discover -s tests       # tests
pip install pyinstaller==6.11.1
python packaging/build_exe.py              # builds dist/AuctionReview.exe and the release zip
```

### Releasing

1. Bump `__version__` in `auction_review/__init__.py` and commit.
2. Tag and push: `git tag v1.0.1 && git push origin v1.0.1`.

GitHub Actions runs the tests, builds the exe on Windows, and publishes a GitHub Release with the
zip attached. The workflow fails if the tag doesn't match `__version__`.

Bundled: [Chart.js](https://www.chartjs.org) 4.4.1 (MIT, see `auction_review/web/vendor/LICENSE-chartjs.txt`).

## Disclaimer

Auction Review is an unofficial fan project, provided as-is. It is not made, endorsed or supported
by Blizzard Entertainment, the authors of Auctionator, or Wowhead. World of Warcraft and Blizzard
Entertainment are trademarks or registered trademarks of Blizzard Entertainment, Inc.
