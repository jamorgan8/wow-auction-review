"""Build dist/AuctionReview.exe and the release zip.

Usage (needs PyInstaller):  python packaging/build_exe.py
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "auction_review"
DIST = ROOT / "dist"
sys.path.insert(0, str(ROOT))
from auction_review import __version__  # noqa: E402


def build_exe() -> Path:
    sep = os.pathsep
    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--console",
        "--name", "AuctionReview",
        "--distpath", str(DIST), "--workpath", str(ROOT / "build"), "--specpath", str(ROOT / "build"),
        "--add-data", f"{PKG / 'web'}{sep}auction_review/web",
        "--add-data", f"{PKG / 'addon'}{sep}auction_review/addon",
        str(ROOT / "packaging" / "launcher.py"),
    ], check=True, cwd=ROOT)
    return DIST / ("AuctionReview.exe" if sys.platform == "win32" else "AuctionReview")


def build_zip(exe: Path) -> Path:
    out = DIST / f"AuctionReview-{__version__}-windows.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(exe, exe.name)
        z.write(ROOT / "packaging" / "QUICKSTART.txt", "QUICKSTART.txt")
        for f in sorted((PKG / "addon" / "AuctionReviewNames").iterdir()):
            z.write(f, f"AuctionReviewNames/{f.name}")
    return out


if __name__ == "__main__":
    shutil.rmtree(DIST, ignore_errors=True)
    exe = build_exe()
    print(f"Built {exe}")
    print(f"Built {build_zip(exe)}")
