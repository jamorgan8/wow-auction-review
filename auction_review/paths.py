"""Locate WoW SavedVariables and the tool's own data directory."""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
ADDON_SOURCE = PACKAGE_DIR / "addon" / "AuctionReviewNames"
WEB_DIR = PACKAGE_DIR / "web"


def _user_data_dir() -> Path:
    override = os.environ.get("AUCTION_REVIEW_HOME")
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return base / "AuctionReview"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "AuctionReview"
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "auction-review"


DATA_DIR = _user_data_dir()
CONFIG_FILE = DATA_DIR / "config.json"
DB_FILE = DATA_DIR / "auction_review.db"

_WOW_ROOTS = [
    r"C:\Program Files (x86)\World of Warcraft",
    r"C:\Program Files\World of Warcraft",
    r"D:\Program Files (x86)\World of Warcraft",
    r"D:\Program Files\World of Warcraft",
    r"C:\World of Warcraft",
    r"D:\World of Warcraft",
    r"E:\World of Warcraft",
    r"C:\Games\World of Warcraft",
    r"D:\Games\World of Warcraft",
    "/Applications/World of Warcraft",
]
_FLAVORS = ["_forever_", "_retail_", "_classic_", "_classic_era_", "_anniversary_", "_ptr_"]


def migrate_legacy_data() -> None:
    """Move data from the old in-repo location (<checkout>/data, <checkout>/config.json)."""
    legacy_root = PACKAGE_DIR.parent
    legacy_db = legacy_root / "data" / "auction_review.db"
    legacy_cfg = legacy_root / "config.json"
    if not legacy_db.is_file() and not legacy_cfg.is_file():
        return
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if legacy_db.is_file() and not DB_FILE.exists():
        import sqlite3
        src = sqlite3.connect(legacy_db)
        dst = sqlite3.connect(DB_FILE)
        with dst:
            src.backup(dst)  # consistent copy, includes anything still in the WAL
        src.close()
        dst.close()
        print(f"Moved price history to {DB_FILE}")
    if legacy_cfg.is_file() and not CONFIG_FILE.exists():
        shutil.copyfile(legacy_cfg, CONFIG_FILE)


def load_config() -> dict:
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_config(cfg: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def _account_files(flavor_dir: Path):
    account_dir = flavor_dir / "WTF" / "Account"
    if account_dir.is_dir():
        yield from account_dir.glob("*/SavedVariables/Auctionator.lua")


def candidates_under(path: Path) -> list[Path]:
    """Auctionator.lua files under a WoW folder, a flavor folder (_retail_ etc.) or the file itself."""
    path = Path(path)
    if path.is_file() and path.name == "Auctionator.lua":
        return [path]
    found = []
    if path.is_dir():
        found += _account_files(path)  # a flavor folder
        for flavor in _FLAVORS:
            found += _account_files(path / flavor)  # the WoW root
        if path.name == "Account":
            found += path.glob("*/SavedVariables/Auctionator.lua")
        if path.name == "SavedVariables" and (path / "Auctionator.lua").is_file():
            found.append(path / "Auctionator.lua")
    unique = {p.resolve(): p for p in found}
    return sorted(unique.values(), key=lambda p: p.stat().st_size, reverse=True)


def all_candidates() -> list[Path]:
    roots = [os.environ.get("AUCTION_REVIEW_WOW_DIR")] + _WOW_ROOTS
    found = []
    for root in filter(None, roots):
        if Path(root).is_dir():
            found += candidates_under(Path(root))
    unique = {p.resolve(): p for p in found}
    return sorted(unique.values(), key=lambda p: p.stat().st_size, reverse=True)


def set_auctionator_file(path: Path) -> None:
    cfg = load_config()
    cfg["auctionator_file"] = str(path)
    save_config(cfg)


def find_auctionator_file(autodetect: bool = True) -> Path | None:
    """Configured path first, else the largest account-wide Auctionator.lua found."""
    cfg = load_config()
    if cfg.get("auctionator_file") and Path(cfg["auctionator_file"]).is_file():
        return Path(cfg["auctionator_file"])
    if not autodetect:
        return None
    found = all_candidates()
    if found:
        set_auctionator_file(found[0])
        return found[0]
    return None


def addons_dir_for(auctionator_file: Path) -> Path:
    # <flavor>/WTF/Account/<acct>/SavedVariables/Auctionator.lua -> <flavor>/Interface/AddOns
    return auctionator_file.parents[4] / "Interface" / "AddOns"


def names_file_for(auctionator_file: Path) -> Path:
    return auctionator_file.with_name("AuctionReviewNames.lua")


def install_addon(auctionator_file: Path) -> Path:
    dest = addons_dir_for(auctionator_file) / "AuctionReviewNames"
    if not dest.parent.is_dir():
        raise FileNotFoundError(f"AddOns folder not found: {dest.parent}")
    shutil.copytree(ADDON_SOURCE, dest, dirs_exist_ok=True)
    return dest


def addon_installed(auctionator_file: Path) -> bool:
    return (addons_dir_for(auctionator_file) / "AuctionReviewNames" / "AuctionReviewNames.toc").is_file()
