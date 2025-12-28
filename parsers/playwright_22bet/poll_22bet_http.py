#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
poll_22bet_http.py — lightweight HTTP poller for 22bet LineFeed 1x2.

- No Playwright required.
- Saves raw response and parsed JSON (if possible) into outdir.
- Uses proxy from:
    1) PROXY (full URL like http://user:pass@host:port)
    2) PROXY_SERVER + PROXY_USERNAME + PROXY_PASSWORD
"""

from __future__ import annotations
import argparse
import datetime as dt
import json
import os
import re
import sys
import time
from pathlib import Path

import requests

def build_proxy() -> str | None:
    p = os.getenv("PROXY")
    if p:
        return p
    server = os.getenv("PROXY_SERVER")
    user = os.getenv("PROXY_USERNAME")
    pwd = os.getenv("PROXY_PASSWORD")
    if server and user and pwd:
        # server like http://ip:port
        m = re.match(r'^(https?://)(.+)$', server.strip())
        if m:
            return f"{m.group(1)}{user}:{pwd}@{m.group(2)}"
        return f"http://{user}:{pwd}@{server.strip()}"
    return None

def try_json_from_bytes(b: bytes):
    # 1) direct utf-8 json
    try:
        return json.loads(b.decode("utf-8", errors="strict"))
    except Exception:
        pass
    # 2) utf-8 with replacement
    try:
        return json.loads(b.decode("utf-8", errors="replace"))
    except Exception:
        pass
    return None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="https://22betluck.com/LineFeed/Get1x2_VZip?sports=1&count=50&lng=en_GB&tf=3000000&tz=3&mode=4&country=207&partner=151&getEmpty=true&gr=151")
    ap.add_argument("--interval", type=int, default=10)
    ap.add_argument("--outdir", default="netdump_http")
    ap.add_argument("--timeout", type=int, default=30)
    args = ap.parse_args()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    proxy = build_proxy()
    proxies = {"http": proxy, "https": proxy} if proxy else None

    hdr = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "en,ru;q=0.9",
        "Referer": "https://22betluck.com/line/football/",
        "Origin": "https://22betluck.com",
        "X-Requested-With": "XMLHttpRequest",
    }

    print(f"[poll] url={args.url}")
    print(f"[poll] interval={args.interval}s outdir={outdir}")
    print(f"[poll] proxy={'ON' if proxy else 'OFF'}")

    while True:
        ts = dt.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        try:
            r = requests.get(args.url, headers=hdr, timeout=args.timeout, proxies=proxies)
            raw_path = outdir / f"{ts}_status{r.status_code}.bin"
            raw_path.write_bytes(r.content)

            j = try_json_from_bytes(r.content)
            if j is not None:
                (outdir / f"{ts}_status{r.status_code}.json").write_text(
                    json.dumps(j, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                print(f"[poll] {ts} ok status={r.status_code} json=YES bytes={len(r.content)}")
            else:
                print(f"[poll] {ts} ok status={r.status_code} json=NO bytes={len(r.content)} (saved raw)")
        except Exception as e:
            print(f"[poll] {ts} ERROR: {e}", file=sys.stderr)

        time.sleep(args.interval)

if __name__ == "__main__":
    main()
