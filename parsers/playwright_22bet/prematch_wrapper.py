# -*- coding: utf-8 -*-
"""Tiny wrapper to run prematch_football_12h with sane defaults.

Usage:
  python prematch_wrapper.py --url "https://22betluck.com/ru/line/football" --tz Europe/Paris --interval 60 --hours 18

This file lives in: D:\Inforadar_Pro\parsers\playwright_22bet
"""

import argparse
import runpy
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="https://22betluck.com/ru/line/football")
    ap.add_argument("--tz", default="Europe/Paris")
    ap.add_argument("--interval", type=int, default=60)
    ap.add_argument("--hours", type=int, default=18)
    args = ap.parse_args()

    target = Path(__file__).with_name("prematch_football_12h.py")
    if not target.exists():
        raise SystemExit(f"Target script not found: {target}")

    # Pass args to child script via sys.argv-like globals
    runpy.run_path(str(target), run_name="__main__", init_globals={
        "CLI_ARGS": {
            "url": args.url,
            "tz": args.tz,
            "interval": args.interval,
            "hours": args.hours,
        }
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
