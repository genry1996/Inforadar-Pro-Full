#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fill/repair `fonbet_factor_catalog.name`.

Why you need this:
- If `fonbet_factor_catalog.name` is NULL/''/'None', UI can't classify markets (1X2, totals, handicap).

What this script does (safe & idempotent):
1) Finds factor_ids with missing/invalid name.
2) Tries to load factor catalog from Fonbet `events/listBase` (with multiple fallback paths + multiple bases).
3) Fallback: derives names from `fonbet_odds_history` (best non-empty text among label/other columns).
4) Optional: dumps full catalog + what was fixed to a TXT file so you don't lose output in chat/terminal.

PowerShell examples:
  $env:FONBET_PREMATCH_PROXY = "http://USER:PASS@IP:PORT"
  python .\fonbet_fill_factor_catalog.py --env .\.env --use-proxy --dump

Notes:
- Fonbet endpoints usually work via: https://<line-host>/events/listBase?lang=ru&scopeMarket=1600
  (some scripts mistakenly use /line/listBase -> often 404)
"""

from __future__ import annotations

import argparse
import os
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
        connect_timeout=15,
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
            s = obj[1].strip()
            return s if s.lower() != "none" else None
        return None

    if not isinstance(obj, dict):
        return None

    for k in ("name", "t", "title", "caption", "c", "n", "label", "s", "sname"):
        v = obj.get(k)
        if isinstance(v, str):
            v = v.strip()
            if v and v.lower() != "none":
                return v

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
                if lk in ("factors", "factor", "factorcatalog", "fc") and isinstance(v, list):
                    items.extend(v)
                walk(v)
        elif isinstance(x, list):
            for it in x:
                walk(it)

    walk(tree)
    return items


def _mk_proxies(proxy: Optional[str]) -> Optional[Dict[str, str]]:
    if not proxy:
        return None
    return {"http": proxy, "https": proxy}


def fetch_listbase_factor_map(
    bases: List[str],
    lang: str,
    sysid: int,
    scope_market: int,
    proxy: Optional[str],
) -> Dict[int, str]:
    """Try multiple bases and multiple URL paths until we get JSON."""
    if requests is None:
        return {}

    path_variants = [
        "/events/listBase",
        "/events/listBase/",
        "/line/listBase",
        "/line/listBase/",
        "/listBase",
        "/listBase/",
    ]

    params = {"lang": lang, "sysId": str(sysid), "scopeMarket": str(scope_market)}
    proxies = _mk_proxies(proxy)

    last_err: Optional[Exception] = None
    data: Any = None
    used_url: Optional[str] = None

    for b in bases:
        b0 = b.strip().rstrip("/")
        if not b0:
            continue
        for p in path_variants:
            url = f"{b0}{p}"

            # 1) GET
            try:
                r = requests.get(url, params=params, proxies=proxies, timeout=35)
                if r.status_code in (404, 405):
                    raise requests.HTTPError(f"GET {url} -> {r.status_code}")
                r.raise_for_status()
                data = r.json()
                used_url = str(r.url)
                break
            except Exception as e:
                last_err = e

            # 2) POST
            try:
                payload = {"lang": lang, "sysId": sysid, "scopeMarket": scope_market}
                r = requests.post(url, json=payload, proxies=proxies, timeout=35)
                if r.status_code in (404, 405):
                    raise requests.HTTPError(f"POST {url} -> {r.status_code}")
                r.raise_for_status()
                data = r.json()
                used_url = url
                break
            except Exception as e:
                last_err = e

        if data is not None:
            break

    if data is None:
        raise RuntimeError(
            "listBase failed for all bases/paths. "
            f"bases={bases}. last_err={last_err}"
        )

    mapping: Dict[int, str] = {}
    for item in _find_factor_items(data):
        fid = _pick_id(item)
        nm = _pick_name(item)
        if fid is not None and nm:
            mapping[fid] = nm

    if used_url:
        print(f"[net] listBase OK: {used_url} (factors={len(mapping)})")

    return mapping


# ---------------------- DB helpers ----------------------

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
            name = (name or "").strip()
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


def _get_table_columns(conn: pymysql.connections.Connection, table: str) -> List[str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME=%s",
            (table,),
        )
        rows = cur.fetchall()
    return [str(r["COLUMN_NAME"]) for r in rows]


def derive_from_history_text(
    conn: pymysql.connections.Connection,
    factor_ids: List[int],
    prefer_cols: Optional[List[str]] = None,
) -> Dict[int, str]:
    if not factor_ids:
        return {}

    cols = _get_table_columns(conn, "fonbet_odds_history")
    cols_lc = {c.lower(): c for c in cols}

    candidates_default = [
        "label",
        "factor_name",
        "name",
        "title",
        "caption",
        "t",
        "outcome",
        "outcome_name",
        "market",
        "market_name",
        "kname",
        "vname",
        "text",
    ]

    candidates = prefer_cols or candidates_default
    picked: List[str] = []
    for c in candidates:
        real = cols_lc.get(c.lower())
        if real:
            picked.append(real)

    if not picked:
        print("[db] fonbet_odds_history: no known text columns found (label/title/name/...).")
        return {}

    best: Dict[int, Tuple[str, int]] = {}

    with conn.cursor() as cur:
        for chunk in _chunked(factor_ids, 700):
            placeholders = ",".join(["%s"] * len(chunk))
            for col in picked:
                cur.execute(
                    f"SELECT factor_id, {col} AS val, COUNT(*) c "
                    f"FROM fonbet_odds_history "
                    f"WHERE factor_id IN ({placeholders}) AND {col} IS NOT NULL AND {col}<>'' "
                    f"GROUP BY factor_id, {col}",
                    chunk,
                )
                rows = cur.fetchall()
                for r in rows:
                    fid = int(r["factor_id"])
                    val = str(r["val"]).strip()
                    c = int(r["c"])
                    if not val or val.lower() == "none":
                        continue
                    prev = best.get(fid)
                    if prev is None or c > prev[1]:
                        best[fid] = (val, c)

    return {fid: val for fid, (val, _c) in best.items()}


def dump_txt(path: str, title: str, rows: List[Tuple[str, str]]) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"\n==== {title} ====\n")
        for a, b in rows:
            f.write(f"{a}\t{b}\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", default=".env", help="path to .env")

    ap.add_argument(
        "--base",
        default=os.getenv("FONBET_BASE", "https://line01.cy8cff-resources.com"),
        help="single base host (used if --bases is not provided)",
    )
    ap.add_argument(
        "--bases",
        default=os.getenv("FONBET_BASES", ""),
        help="comma-separated bases to try (overrides --base).",
    )

    ap.add_argument("--lang", default=os.getenv("FONBET_LANG", "ru"))
    ap.add_argument("--sysid", type=int, default=int(os.getenv("FONBET_SYSID", "1")))
    ap.add_argument("--scope-market", type=int, default=int(os.getenv("FONBET_SCOPE_MARKET", "1700")), dest="scope_market")

    ap.add_argument("--use-proxy", action="store_true", help="use FONBET_PREMATCH_PROXY from env")
    ap.add_argument("--proxy", default="", help="proxy URL like http://user:pass@ip:port")
    ap.add_argument("--no-net", action="store_true", help="skip listBase and only use DB")

    ap.add_argument("--limit", type=int, default=0, help="limit number of factor_ids to fix")
    ap.add_argument("--dry-run", action="store_true")

    ap.add_argument("--dump", action="store_true", help="write dump to fonbet_factor_catalog_dump.txt")
    ap.add_argument("--dump-path", default="fonbet_factor_catalog_dump.txt", help="dump file path")

    args = ap.parse_args()

    _load_env_file(args.env)

    proxy = None
    if args.proxy:
        proxy = args.proxy.strip()
    elif args.use_proxy:
        proxy = os.getenv("FONBET_PREMATCH_PROXY", "").strip() or None

    if args.bases.strip():
        bases = [b.strip() for b in args.bases.split(",") if b.strip()]
    else:
        b0 = args.base.strip().rstrip("/")
        bases = [b0]
        if b0.startswith("https://"):
            if "line01" in b0 and "line01w" not in b0:
                bases.append(b0.replace("line01", "line01w"))
            if "line01w" in b0 and "line01" not in b0:
                bases.append(b0.replace("line01w", "line01"))

    conn = _mysql_conn()

    bad_ids = get_bad_factor_ids(conn, limit=args.limit)
    print(f"[db] bad factor_ids: {len(bad_ids)}")
    if not bad_ids:
        print("[ok] Nothing to fix.")
        return 0

    dump_path = args.dump_path
    if args.dump:
        try:
            if os.path.exists(dump_path):
                os.remove(dump_path)
        except Exception:
            pass
        dump_txt(dump_path, "CONFIG", [("bases", ", ".join(bases)), ("proxy", "yes" if proxy else "no")])

    net_mapping: Dict[int, str] = {}
    if not args.no_net:
        try:
            if requests is None:
                raise RuntimeError("requests is not installed")
            net_all = fetch_listbase_factor_map(
                bases=bases, lang=args.lang, sysid=args.sysid, scope_market=args.scope_market, proxy=proxy
            )
            bad_set = set(bad_ids)
            net_mapping = {fid: nm for fid, nm in net_all.items() if fid in bad_set}
            print(f"[net] mapping for bad ids: {len(net_mapping)}")

            if args.dump:
                dump_rows = [(str(fid), nm) for fid, nm in sorted(net_all.items(), key=lambda x: x[0])]
                dump_txt(dump_path, "LISTBASE_FACTORS", dump_rows)

        except Exception as e:
            print(f"[net] listBase failed: {e}")

    updated_net = update_names(conn, net_mapping, dry_run=args.dry_run)

    remaining = get_bad_factor_ids(conn, limit=args.limit)
    remaining_set = set(remaining)

    hist_mapping = derive_from_history_text(conn, remaining)
    hist_mapping = {fid: nm for fid, nm in hist_mapping.items() if fid in remaining_set}
    print(f"[db] history mapping: {len(hist_mapping)}")

    updated_hist = update_names(conn, hist_mapping, dry_run=args.dry_run)

    remaining2 = get_bad_factor_ids(conn, limit=args.limit)

    print(f"[done] updated: {updated_net + updated_hist} (net={updated_net}, history={updated_hist}); remaining bad: {len(remaining2)}")

    if args.dump:
        dump_txt(dump_path, "UPDATED_NET", [(str(k), v) for k, v in sorted(net_mapping.items())])
        dump_txt(dump_path, "UPDATED_HISTORY", [(str(k), v) for k, v in sorted(hist_mapping.items())])
        dump_txt(dump_path, "REMAINING_BAD", [(str(fid), "") for fid in remaining2])
        print(f"[dump] written: {dump_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
