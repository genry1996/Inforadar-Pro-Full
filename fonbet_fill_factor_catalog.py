#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fill/repair fonbet_factor_catalog names from Fonbet listBase.

What it does:
- Fetches listBase JSON (prematch) from Fonbet resources endpoint
- Extracts factors list and writes factor_id + name + raw_json to MySQL
- Stores ONLY per-factor JSON (small) to avoid max_allowed_packet issues

Typical use (PowerShell):
  python .\fonbet_fill_factor_catalog.py --env .\.env --hours 12

Optional:
  setx FONBET_PREMATCH_PROXY "http://user:pass@ip:port"
  python .\fonbet_fill_factor_catalog.py --env .\.env --hours 12 --use-proxy
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pymysql
import requests


def load_env_file(path: Path) -> None:
    """Very small .env loader (KEY=VALUE, ignores comments)."""
    if not path.exists():
        raise SystemExit(f".env not found: {path}")
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


def mysql_connect_with_retry(max_tries: int = 10, sleep_s: float = 1.5) -> pymysql.connections.Connection:
    host = os.getenv("MYSQL_HOST", "127.0.0.1").strip()
    port = int(os.getenv("MYSQL_PORT", "3307") or "3307")
    user = os.getenv("MYSQL_USER", "root").strip()
    password = os.getenv("MYSQL_PASSWORD", "").strip()
    db = os.getenv("MYSQL_DB", "inforadar").strip()

    last_err: Optional[Exception] = None
    for i in range(1, max_tries + 1):
        try:
            conn = pymysql.connect(
                host=host,
                port=port,
                user=user,
                password=password,
                database=db,
                charset="utf8mb4",
                autocommit=True,
                connect_timeout=10,
                read_timeout=60,
                write_timeout=60,
                cursorclass=pymysql.cursors.DictCursor,
            )
            # quick sanity query
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
            return conn
        except Exception as e:
            last_err = e
            time.sleep(sleep_s)

    raise SystemExit(f"MySQL connect failed after {max_tries} tries: {last_err}")


def guess_factor_name(f: Dict[str, Any]) -> str:
    for key in ("name", "title", "caption", "text", "value", "label", "n"):
        v = f.get(key)
        if v is None:
            continue
        s = str(v).strip()
        if s and s.lower() not in {"none", "null"}:
            return s
    return ""


def fetch_list_base(base: str, lang: str, sys_id: int, proxies: Optional[Dict[str, str]]) -> Dict[str, Any]:
    # In Fonbet resources, listBase is usually /line/listBase
    url = base.rstrip("/") + "/line/listBase"
    params = {"lang": lang, "sysId": sys_id}
    r = requests.get(url, params=params, timeout=40, proxies=proxies)
    r.raise_for_status()
    return r.json()


def extract_factors(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    # listBase variants: factors may be payload['factors'] or payload['data']['factors'] etc.
    for path in (
        ("factors",),
        ("data", "factors"),
        ("result", "factors"),
    ):
        node: Any = payload
        ok = True
        for k in path:
            if isinstance(node, dict) and k in node:
                node = node[k]
            else:
                ok = False
                break
        if ok and isinstance(node, list):
            return [x for x in node if isinstance(x, dict)]
    return []


def upsert_factors(conn: pymysql.connections.Connection, factors: List[Dict[str, Any]], chunk: int = 500) -> Tuple[int, int]:
    """Returns (inserted_or_updated, skipped)."""
    sql = (
        "INSERT INTO fonbet_factor_catalog (factor_id, name, raw_json) "
        "VALUES (%s,%s,%s) "
        "ON DUPLICATE KEY UPDATE name=VALUES(name), raw_json=VALUES(raw_json), updated_at=CURRENT_TIMESTAMP"
    )

    rows: List[Tuple[int, str, str]] = []
    skipped = 0
    for f in factors:
        fid = f.get("id")
        if fid is None:
            fid = f.get("factorId")
        try:
            fid_i = int(fid)
        except Exception:
            skipped += 1
            continue
        name = guess_factor_name(f)
        raw = json.dumps(f, ensure_ascii=False, separators=(",", ":"))
        rows.append((fid_i, name, raw))

    total = 0
    with conn.cursor() as cur:
        for i in range(0, len(rows), chunk):
            part = rows[i : i + chunk]
            cur.executemany(sql, part)
            total += len(part)
    return total, skipped


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", default=".env", help="Path to .env")
    ap.add_argument("--base", default="", help="Base resources URL, e.g. https://line01.cy8cff-resources.com")
    ap.add_argument("--lang", default="ru")
    ap.add_argument("--sysid", type=int, default=None)
    ap.add_argument("--use-proxy", action="store_true", help="Use FONBET_PREMATCH_PROXY for HTTP(S)")
    args = ap.parse_args()

    load_env_file(Path(args.env))

    base = args.base.strip() or os.getenv("FONBET_BASE", "https://line01.cy8cff-resources.com").strip()
    sys_id = args.sysid if args.sysid is not None else int(os.getenv("FONBET_SYS_ID", "1") or "1")

    proxies = None
    if args.use_proxy:
        p = os.getenv("FONBET_PREMATCH_PROXY", "").strip()
        if p:
            proxies = {"http": p, "https": p}

    print(f"[fetch] base={base} lang={args.lang} sysId={sys_id} proxy={'yes' if proxies else 'no'}")
    payload = fetch_list_base(base=base, lang=args.lang, sys_id=sys_id, proxies=proxies)
    factors = extract_factors(payload)
    print(f"[parse] factors={len(factors)}")
    if not factors:
        raise SystemExit("No factors found in listBase payload (structure changed?)")

    conn = mysql_connect_with_retry()
    n, skipped = upsert_factors(conn, factors)
    conn.close()
    print(f"[db] upserted={n} skipped={skipped}")


if __name__ == "__main__":
    main()
