"""Locate WoW SavedVariables and the tool's own data directory."""
from __future__ import annotations

import json
import os
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_DIR / "data"
CONFIG_FILE = PROJECT_DIR / "config.json"
DB_FILE = DATA_DIR / "auction_review.db"

_WOW_ROOTS = [
    r"D:\Program Files (x86)\World of Warcraft",
    r"C:\Program Files (x86)\World of Warcraft",
    r"C:\Program Files\World of Warcraft",
    r"D:\World of Warcraft",
    r"E:\World of Warcraft",
]
_FLAVORS = ["_forever_", "_retail_", "_classic_", "_classic_era_", "_anniversary_"]


def load_config() -> dict:
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_config(cfg: dict) -> None:
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def _candidates():
    roots = [os.environ.get("AUCTION_REVIEW_WOW_DIR")] + _WOW_ROOTS
    for root in filter(None, roots):
        for flavor in _FLAVORS:
            account_dir = Path(root) / flavor / "WTF" / "Account"
            if account_dir.is_dir():
                yield from account_dir.glob("*/SavedVariables/Auctionator.lua")


def find_auctionator_file() -> Path | None:
    """Configured path first, else the largest account-wide Auctionator.lua found."""
    cfg = load_config()
    if cfg.get("auctionator_file") and Path(cfg["auctionator_file"]).is_file():
        return Path(cfg["auctionator_file"])
    found = sorted(_candidates(), key=lambda p: p.stat().st_size, reverse=True)
    if found:
        cfg["auctionator_file"] = str(found[0])
        save_config(cfg)
        return found[0]
    return None


def addons_dir_for(auctionator_file: Path) -> Path:
    # <flavor>/WTF/Account/<acct>/SavedVariables/Auctionator.lua -> <flavor>/Interface/AddOns
    return auctionator_file.parents[4] / "Interface" / "AddOns"


def names_file_for(auctionator_file: Path) -> Path:
    return auctionator_file.with_name("AuctionReviewNames.lua")
