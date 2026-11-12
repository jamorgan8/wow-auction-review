"""Entry point for the bundled Windows executable."""
import sys
import traceback

from auction_review.__main__ import main


def run():
    try:
        main()
    except SystemExit as e:
        if e.code not in (None, 0):
            print(e.code if isinstance(e.code, str) else f"Exited with code {e.code}")
            input("\nPress Enter to close this window...")
        raise
    except Exception:
        traceback.print_exc()
        input("\nAuction Review hit an error. Press Enter to close this window...")
        sys.exit(1)


if __name__ == "__main__":
    run()
