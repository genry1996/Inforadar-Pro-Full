#!/usr/bin/env python3
"""Wrapper: run the prematch parser file that exists in this folder.

Why: older repos had different filenames (prematch_parser_with_history.py, prematch_football_12h.py, etc).
This wrapper tries known candidates and runs the first one found.
"""
from __future__ import annotations

import runpy
from pathlib import Path

CANDIDATES = [
    "prematch_football_12h.py",
    "prematch_football_12h_fixed.py",
    "prematch_parser_with_history.py",
    "prematch_parser.py",
    "prematch_simple.py",
]

def main() -> int:
    here = Path(__file__).resolve().parent
    for name in CANDIDATES:
        p = here / name
        if p.exists():
            print(f"[wrapper] running: {p.name}")
            runpy.run_path(str(p), run_name="__main__")
            return 0

    print("[wrapper] ERROR: no parser file found.")
    print("Tried:", ", ".join(CANDIDATES))
    return 2

if __name__ == "__main__":
    raise SystemExit(main())
