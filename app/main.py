"""
app/main.py — single entry point for the whole system.

Usage
-----
    python -m app.main collect
        (--date <YYYY-MM-DD> | --start <YYYY-MM-DD> --end <YYYY-MM-DD>)
        [--skip-users]

    python -m app.main analyze
        (--date <YYYY-MM-DD> | --start <YYYY-MM-DD> --end <YYYY-MM-DD>)

    python -m app.main all
        (--date <YYYY-MM-DD> | --start <YYYY-MM-DD> --end <YYYY-MM-DD>)
        [--skip-users]

    python -m app.main migrate

    python -m app.main dashboard
"""

import sys
from app.run_dashboard import main as run_dashboard
from app.run_pipeline import main as run_pipeline

def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "dashboard":
        run_dashboard()
        return

    run_pipeline()

if __name__ == "__main__":
    main()