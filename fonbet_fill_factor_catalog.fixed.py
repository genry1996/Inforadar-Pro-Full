#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Repair `fonbet_factor_catalog.name` so UI can display 1X2 / Totals / Handicap.

Problem you're seeing:
- `fonbet_odds_history` has rows (raw_rows>0), but UI shows "No data".
- In your DB, `fonbet_factor_catalog.name` for key factors is literally "None".
  UI relies on the factor name to classify markets -> it can't classify -> shows nothing.

What this script does (safe, idempotent):
1) Finds factor_ids with missing/invalid name (NULL / '' / 'None')
2) Tries to fill names from Fonbet listBase (optional)
3) Fallback: fills names from the most common non-empty `label` in `fonbet_odds_history`

Usage examples:
  python fonbet_fill_factor_catalog.fixed.py --env .\.env --use-proxy
  python fonbet_fill_factor_catalog.fixed.py --env .\.env --proxy $env:FONBET_PREMATCH_PROXY
  python fonbet_fill_factor_catalog.fixed.py --env .\.env --no-net
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pymysql

try:
    import requests
except Exception:
    requests = None  # type: ignore


# ---------------------- env helpers ----------------------

def _load_env_file(path: str) -> None:
    """Simple .env loader: KEY=VALUE per line. Does not override existing env."""
    if not path:
        return
    if not os.path.exists(path):
        raise FileNotFoundError(path)

    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
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


def _mysql_conn() -> pymysql.connections.Connection:
    host = os.getenv("MYSQL_HOST", "127.0.0.1")
    port = int(os.getenv("MYSQL_PORT", "3307"))
    user = os.getenv("MYSQL_USER", "root")
    password = os.getenv("MYSQL_PASSWORD", "")
    db = os.getenv("MYSQL_DB", "inforadar")

    if not password:
        raise RuntimeError("MYSQL_PASSWORD is empty. Check your .env")

    return pymysql.connect(
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


# ---------------------- Fonbet parsing ----------------------

def _pick_name(obj: Any) -> Optional[str]:
    """Try to extract a human readable name from a factor dict/tuple."""
    if obj is None:
        return None

    # common shapes:
    # {"id": 921, "name": "1"}
    # {"f": 921, "t": "П1"}
    # [921, "1"]
    if isinstance(obj, (list, tuple)):
        if len(obj) >= 2 and isinstance(obj[1], str) and obj[1].strip():
            return obj[1].strip()
        return None

    if not isinstance(obj, dict):
        return None

    for k in ("name", "t", "title", "caption", "c", "n", "label"):
        v = obj.get(k)
        if isinstance(v, str):
            v = v.strip()
            if v and v.lower() != "none":
                return v

    # localized dicts: {"ru":"..."}
    for k in ("ru", "en"):
        v = obj.get(k)
        if isinstance(v, str) and v.strip() and v.strip().lower() != "none":
            return v.strip()

    return None


def _pick_id(obj: Any) -> Optional[int]:
    if obj is None:
        return None
    if isinstance(obj, (list, tuple)):
        if len(obj) >= 1 and isinstance(obj[0], int):
            return obj[0]
        if len(obj) >= 1 and isinstance(obj[0], str) and obj[0].isdigit():
            return int(obj[0])
        return None
    if isinstance(obj, dict):
        for k in ("factor_id", "factorId", "id", "f"):
            v = obj.get(k)
            if isinstance(v, int):
                return v
            if isinstance(v, str) and v.isdigit():
                return int(v)
    return None


def _find_factor_items(tree: Any) -> List[Any]:
    """Recursively find lists under keys like factors/factorCatalog etc."""
    items: List[Any] = []

    def walk(x: Any) -> None:
        if isinstance(x, dict):
            for k, v in x.items():
                lk = str(k).lower()
                if lk in ("factors", "factor", "factorcatalog", "fc", "f") and isinstance(v, list):
                    items.extend(v)
                walk(v)
        elif isinstance(x, list):
            for it in x:
                walk(it)

    walk(tree)
    return items


def fetch_listbase_factor_map(
    base: str,
    lang: str,
    sysid: int,
    scope_market: int,
    proxy: Optional[str],
) -> Dict[int, str]:
    if requests is None:
        return {}

    url = f"{base.rstrip('/')}/line/listBase"
    params = {"lang": lang, "sysId": str(sysid), "scopeMarket": str(scope_market)}

    proxies = None
    if proxy:
        proxies = {"http": proxy, "https": proxy}

    r = requests.get(url, params=params, proxies=proxies, timeout=30)
    r.raise_for_status()
    data = r.json()

    mapping: Dict[int, str] = {}
    for item in _find_factor_items(data):
        fid = _pick_id(item)
        nm = _pick_name(item)
        if fid is not None and nm:
            mapping[fid] = nm

    return mapping


# ---------------------- DB update logic ----------------------

def _chunked(seq: List[int], size: int = 900) -> Iterable[List[int]]:
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def get_bad_factor_ids(conn: pymysql.connections.Connection, limit: int = 0) -> List[int]:
    q = (
        "SELECT factor_id FROM fonbet_factor_catalog "
        "WHERE name IS NULL OR name='' OR name='None' "
        "ORDER BY factor_id"
    )
    if limit and limit > 0:
        q += f" LIMIT {int(limit)}"

    with conn.cursor() as cur:
        cur.execute(q)
        rows = cur.fetchall()
    return [int(r["factor_id"]) for r in rows]


def update_names(conn: pymysql.connections.Connection, mapping: Dict[int, str], dry_run: bool) -> int:
    if not mapping:
        return 0

    updated = 0
    with conn.cursor() as cur:
        for fid, name in mapping.items():
            name = name.strip()
            if not name or name.lower() == "none":
                continue
            if dry_run:
                updated += 1
                continue
            cur.execute(
                "UPDATE fonbet_factor_catalog SET name=%s WHERE factor_id=%s",
                (name, fid),
            )
            updated += 1
    return updated


def derive_from_history_labels(
    conn: pymysql.connections.Connection, factor_ids: List[int]
) -> Dict[int, str]:
    if not factor_ids:
        return {}

    best: Dict[int, Tuple[str, int]] = {}  # fid -> (label, count)

    with conn.cursor() as cur:
        for chunk in _chunked(factor_ids, 800):
            placeholders = ",".join(["%s"] * len(chunk))
            cur.execute(
                f"SELECT factor_id, label, COUNT(*) c "
                f"FROM fonbet_odds_history "
                f"WHERE factor_id IN ({placeholders}) AND label IS NOT NULL AND label<>'' "
                f"GROUP BY factor_id, label",
                chunk,
            )
            rows = cur.fetchall()

            for r in rows:
                fid = int(r["factor_id"])
                label = str(r["label"]).strip()
                c = int(r["c"])
                if not label or label.lower() == "none":
                    continue
                prev = best.get(fid)
                if prev is None or c > prev[1]:
                    best[fid] = (label, c)

    return {fid: lab for fid, (lab, _c) in best.items()}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", default=".env", help="path to .env")
    ap.add_argument("--base", default=os.getenv("FONBET_BASE", "https://line01.cy8cff-resources.com"))
    ap.add_argument("--lang", default="ru")
    ap.add_argument("--sysid", type=int, default=int(os.getenv("FONBET_SYSID", "1")))
    ap.add_argument("--scope-market", type=int, default=int(os.getenv("FONBET_SCOPE_MARKET", "1700")))

    ap.add_argument("--use-proxy", action="store_true", help="use FONBET_PREMATCH_PROXY from env")
    ap.add_argument("--proxy", default="", help="proxy URL like http://user:pass@ip:port")
    ap.add_argument("--no-net", action="store_true", help="skip listBase request and only use DB labels")

    ap.add_argument("--limit", type=int, default=0, help="limit number of factor_ids to process")
    ap.add_argument("--dry-run", action="store_true")

    args = ap.parse_args()

    _load_env_file(args.env)

    proxy = None
    if args.proxy:
        proxy = args.proxy.strip()
    elif args.use_proxy:
        proxy = os.getenv("FONBET_PREMATCH_PROXY", "").strip() or None

    conn = _mysql_conn()

    bad_ids = get_bad_factor_ids(conn, limit=args.limit)
    print(f"[db] bad factor_ids: {len(bad_ids)}")
    if not bad_ids:
        return 0

    # 1) listBase mapping
    net_mapping: Dict[int, str] = {}
    if not args.no_net:
        try:
            if requests is None:
                raise RuntimeError("requests is not installed")
            net_mapping = fetch_listbase_factor_map(
                base=args.base,
                lang=args.lang,
                sysid=args.sysid,
                scope_market=args.scope_market,
                proxy=proxy,
            )
            # keep only bad ids
            net_mapping = {fid: nm for fid, nm in net_mapping.items() if fid in bad_ids}
            print(f"[net] listBase mapping: {len(net_mapping)}")
        except Exception as e:
            print(f"[net] listBase failed: {e}")

    updated1 = update_names(conn, net_mapping, dry_run=args.dry_run)

    # recompute remaining
    remaining = get_bad_factor_ids(conn, limit=args.limit)
    remaining_set = set(remaining)

    # 2) fallback from labels
    label_mapping = derive_from_history_labels(conn, remaining)
    label_mapping = {fid: nm for fid, nm in label_mapping.items() if fid in remaining_set}
    print(f"[db] label mapping: {len(label_mapping)}")

    updated2 = update_names(conn, label_mapping, dry_run=args.dry_run)

    remaining2 = get_bad_factor_ids(conn, limit=args.limit)

    print(f"[done] updated: {updated1 + updated2} (net={updated1}, label={updated2}); remaining bad: {len(remaining2)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
