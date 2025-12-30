#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Compatibility wrapper.

This repo historically used prematch_simple_api_markets_fixed.py.
The actual prematch parser code lives in other files in this folder.
This wrapper executes the best available candidate so old run commands keep working.

No secrets are stored here. Proxy/DB settings must come from environment variables.
"""
from __future__ import annotations
import runpy
import sys
from pathlib import Path

def main() -> int:
    here = Path(__file__).resolve().parent
    candidates = [
        # New unified wrapper / recommended entry point
        here / "prematch_wrapper.py",
        # Current maintained parser
        here / "prematch_football_12h.py",
        here / "prematch_parser_with_history.py",
        here / "prematch_simple_HISTORY.py",
        here / "prematch_simple.py",
        here / "prematch_parser.py",
    ]
    for p in candidates:
        if p.exists():
            print(f"[wrapper] running: {p.name}")
            runpy.run_path(str(p), run_name="__main__")
            return 0

    print("[wrapper] ERROR: no prematch parser found in this folder.", file=sys.stderr)
    print("[wrapper] looked for: " + ", ".join(x.name for x in candidates), file=sys.stderr)
    return 2

if __name__ == "__main__":
    raise SystemExit(main())
