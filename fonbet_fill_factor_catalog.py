#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fill/repair `fonbet_factor_catalog.name`.

Your run showed:
- proxy works (ipify 200)
- listBase endpoint returns 200
- but extracted factors=0

Reason:
Fonbet `events/listBase` JSON shape varies; factor catalog can be a dict/map or nested differently.

What this script does (safe & idempotent):
1) Finds factor_ids where `name` is NULL/''/'None' in `fonbet_factor_catalog`.
2) Tries to fetch factor_id -> name from Fonbet `listBase` using multiple paths/bases.
   - Extraction scans the whole JSON and supports dict-maps too.
   - If extracted=0, saves raw JSON (when --dump is used).
3) If listBase gives nothing, tries `eventView` for a handful of event_ids from your DB.
4) Final fallback: derive names from `fonbet_odds_history` text columns (if present).
5) Optional: writes a detailed dump file so you don't lose "pages" in terminal.

PowerShell (recommended):
  Remove-Item Env:FONBET_PREMATCH_PROXY -ErrorAction SilentlyContinue
  $line = (Select-String -Path .\\.env -Pattern '^FONBET_PREMATCH_PROXY=').Line
  $env:FONBET_PREMATCH_PROXY = $line.Split('=',2)[1].Trim().Trim('"')
  python .\\fonbet_fill_factor_catalog.py --env .\\.env --use-proxy --dump

"""

from __future__ import annotations

import argparse
import json
import os
import time
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

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


# ---------------------- extraction helpers ----------------------

def _clean_name(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    s2 = str(s).strip()
    if not s2 or s2.lower() == "none":
        return None
    return s2


def _pick_name(obj: Any) -> Optional[str]:
    if obj is None:
        return None

    if isinstance(obj, (list, tuple)):
        if len(obj) >= 2 and isinstance(obj[1], str):
            return _clean_name(obj[1])
        return None

    if not isinstance(obj, dict):
        return None

    for k in ("name", "t", "title", "caption", "c", "n", "label", "s", "sname"):
        v = obj.get(k)
        if isinstance(v, str):
            v2 = _clean_name(v)
            if v2:
                return v2

    for k in ("ru", "en"):
        v = obj.get(k)
        if isinstance(v, str):
            v2 = _clean_name(v)
            if v2:
                return v2

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


def _add_mapping(mapping: Dict[int, str], fid: int, name: str) -> None:
    name2 = _clean_name(name)
    if not name2:
        return
    prev = mapping.get(fid)
    # prefer longer/non-trivial text
    if prev is None:
        mapping[fid] = name2
        return
    if len(name2) > len(prev):
        mapping[fid] = name2


def collect_factor_pairs(tree: Any, wanted: Optional[Set[int]] = None) -> Dict[int, str]:
    """Scan entire JSON and collect factor_id -> name.

    Supports:
    - list items like {id:..., name:...} or [id, name]
    - dict maps like {"910": "П1"} or {910: {name:...}}
    - deeply nested structures

    If `wanted` is provided, only collects those ids.
    """

    out: Dict[int, str] = {}

    def add(fid: Optional[int], name: Optional[str]) -> None:
        if fid is None:
            return
        if wanted is not None and fid not in wanted:
            return
        n = _clean_name(name)
        if not n:
            return
        _add_mapping(out, fid, n)

    def walk(x: Any) -> None:
        if x is None:
            return

        # direct pair from object
        fid = _pick_id(x)
        nm = _pick_name(x)
        if fid is not None and nm:
            add(fid, nm)

        if isinstance(x, list):
            # list of [id,name] or dicts
            for it in x:
                walk(it)
            return

        if isinstance(x, dict):
            # dict might be a direct map id->name
            for k, v in x.items():
                if isinstance(k, int) or (isinstance(k, str) and k.isdigit()):
                    fid2 = int(k)
                    if isinstance(v, str):
                        add(fid2, v)
                    else:
                        add(fid2, _pick_name(v))
                        walk(v)
                else:
                    # sometimes factor blocks are inside keys with "factor" substring
                    lk = str(k).lower()
                    if "factor" in lk or lk in ("factors", "factor", "factorcatalog", "fc", "customfactors"):
                        if isinstance(v, dict):
                            # could be id->obj or nested groups
                            walk(v)
                        elif isinstance(v, list):
                            walk(v)
                        else:
                            walk(v)
                    else:
                        walk(v)
            return

    walk(tree)
    return out


# ---------------------- network helpers ----------------------

def _mk_proxies(proxy: Optional[str]) -> Optional[Dict[str, str]]:
    if not proxy:
        return None
    return {"http": proxy, "https": proxy}


def _default_headers(base: str) -> Dict[str, str]:
    # Some Fonbet edges behave better with a browser-like UA
    origin = base.rstrip("/")
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": origin + "/",
        "Origin": origin,
        "Connection": "keep-alive",
    }


def _request_json(
    method: str,
    url: str,
    params: Optional[Dict[str, str]] = None,
    payload: Optional[Dict[str, Any]] = None,
    proxies: Optional[Dict[str, str]] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: int = 35,
) -> Any:
    if requests is None:
        raise RuntimeError("requests is not installed")

    method = method.upper().strip()
    if method == "GET":
        r = requests.get(url, params=params, proxies=proxies, headers=headers, timeout=timeout)
    elif method == "POST":
        r = requests.post(url, params=params, json=payload, proxies=proxies, headers=headers, timeout=timeout)
    else:
        raise ValueError(f"Unsupported method: {method}")

    r.raise_for_status()
    return r.json(), getattr(r, "url", url)


def fetch_listbase(
    bases: List[str],
    lang: str,
    sysid: int,
    scope_market: int,
    proxy: Optional[str],
    wanted: Optional[Set[int]] = None,
    dump_raw_path: Optional[str] = None,
    try_scopes: bool = True,
    try_sysids: bool = True,
) -> Tuple[Dict[int, str], str, Dict[str, Any]]:
    """Fetch listBase and return (mapping, used_url, meta).

    If mapping is empty and dump_raw_path is set, saves raw JSON with meta.
    """

    path_variants = [
        "/events/listBase",
        "/events/listBase/",
        "/listBase",
        "/listBase/",
        "/line/listBase",
        "/line/listBase/",
    ]

    scopes = [scope_market]
    if try_scopes:
        for s in (1700, 1600, 1500, 1800, 1400, 1300):
            if s not in scopes:
                scopes.append(s)

    sysids = [sysid]
    if try_sysids:
        for sid in (1, 2, 3):
            if sid not in sysids:
                sysids.append(sid)

    proxies = _mk_proxies(proxy)

    last_err: Optional[Exception] = None
    last_raw: Any = None
    last_used_url = ""
    last_meta: Dict[str, Any] = {}

    for b in bases:
        b0 = b.strip().rstrip("/")
        if not b0:
            continue
        headers = _default_headers(b0)

        for sid in sysids:
            for sc in scopes:
                params = {"lang": lang, "sysId": str(sid), "scopeMarket": str(sc)}

                for p in path_variants:
                    url = f"{b0}{p}"

                    # Try GET first, then POST
                    for method in ("GET", "POST"):
                        try:
                            payload = {"lang": lang, "sysId": sid, "scopeMarket": sc} if method == "POST" else None
                            raw, used = _request_json(
                                method=method,
                                url=url,
                                params=params if method == "GET" else None,
                                payload=payload,
                                proxies=proxies,
                                headers=headers,
                            )
                            last_raw = raw
                            last_used_url = used
                            last_meta = {"base": b0, "path": p, "method": method, "params": params}

                            mapping = collect_factor_pairs(raw, wanted=wanted)

                            # If we extracted something - success
                            if mapping:
                                return mapping, used, last_meta

                            # mapping empty: keep trying other scope/sys/path but remember last success raw
                            last_err = None

                        except Exception as e:
                            last_err = e
                            continue

    # Nothing extracted
    if dump_raw_path and last_raw is not None:
        try:
            with open(dump_raw_path, "w", encoding="utf-8") as f:
                json.dump({"meta": last_meta, "used_url": last_used_url, "data": last_raw}, f, ensure_ascii=False)
        except Exception:
            pass

    raise RuntimeError(
        "listBase returned no extractable factors for all bases/paths/sysId/scopeMarket. "
        f"bases={bases}. last_err={last_err}"
    )


def fetch_eventview(
    bases: List[str],
    event_id: int,
    lang: str,
    proxy: Optional[str],
    wanted: Optional[Set[int]] = None,
    dump_raw_path: Optional[str] = None,
) -> Dict[int, str]:
    if requests is None:
        return {}

    path_variants = [
        "/events/eventView",
        "/line/eventView",
        "/eventView",
    ]

    proxies = _mk_proxies(proxy)

    last_raw: Any = None
    last_meta: Dict[str, Any] = {}

    for b in bases:
        b0 = b.strip().rstrip("/")
        if not b0:
            continue
        headers = _default_headers(b0)

        for p in path_variants:
            url = f"{b0}{p}"
            params = {"lang": lang, "eventId": str(event_id)}

            for method in ("GET", "POST"):
                try:
                    payload = {"lang": lang, "eventId": event_id} if method == "POST" else None
                    raw, used = _request_json(
                        method=method,
                        url=url,
                        params=params if method == "GET" else None,
                        payload=payload,
                        proxies=proxies,
                        headers=headers,
                    )
                    last_raw = raw
                    last_meta = {"base": b0, "path": p, "method": method, "used_url": used, "params": params}

                    mapping = collect_factor_pairs(raw, wanted=wanted)
                    if mapping:
                        return mapping

                except Exception:
                    continue

    if dump_raw_path and last_raw is not None:
        try:
            with open(dump_raw_path, "w", encoding="utf-8") as f:
                json.dump({"meta": last_meta, "data": last_raw}, f, ensure_ascii=False)
        except Exception:
            pass

    return {}


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
            name2 = _clean_name(name)
            if not name2:
                continue
            if dry_run:
                updated += 1
                continue
            cur.execute(
                "UPDATE fonbet_factor_catalog SET name=%s WHERE factor_id=%s",
                (name2, fid),
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


def pick_event_ids_for_factors(
    conn: pymysql.connections.Connection,
    factor_ids: List[int],
    limit_events: int,
) -> List[int]:
    if not factor_ids or limit_events <= 0:
        return []

    cols = _get_table_columns(conn, "fonbet_odds_history")
    cols_lc = {c.lower(): c for c in cols}
    if "event_id" not in cols_lc or "factor_id" not in cols_lc:
        return []

    ev_col = cols_lc["event_id"]
    fac_col = cols_lc["factor_id"]

    # choose events with most records for these factor_ids
    placeholders = ",".join(["%s"] * len(factor_ids))
    q = (
        f"SELECT {ev_col} AS event_id, COUNT(*) AS c "
        f"FROM fonbet_odds_history "
        f"WHERE {fac_col} IN ({placeholders}) "
        f"GROUP BY {ev_col} "
        f"ORDER BY c DESC "
        f"LIMIT %s"
    )

    with conn.cursor() as cur:
        cur.execute(q, factor_ids + [int(limit_events)])
        rows = cur.fetchall()

    out: List[int] = []
    for r in rows:
        try:
            out.append(int(r["event_id"]))
        except Exception:
            continue
    return out


def derive_from_history_text(
    conn: pymysql.connections.Connection,
    factor_ids: List[int],
) -> Dict[int, str]:
    if not factor_ids:
        return {}

    cols = _get_table_columns(conn, "fonbet_odds_history")
    cols_lc = {c.lower(): c for c in cols}

    candidates = [
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

    picked: List[str] = []
    for c in candidates:
        real = cols_lc.get(c.lower())
        if real:
            picked.append(real)

    if not picked:
        print("[db] fonbet_odds_history: no known text columns found.")
        print("[db] fonbet_odds_history columns:", ", ".join(cols))
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
                    val = _clean_name(r["val"])
                    c = int(r["c"])
                    if not val:
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


# ---------------------- main ----------------------

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
    ap.add_argument(
        "--scope-market",
        type=int,
        default=int(os.getenv("FONBET_SCOPE_MARKET", "1700")),
        dest="scope_market",
    )

    ap.add_argument("--use-proxy", action="store_true", help="use FONBET_PREMATCH_PROXY from env")
    ap.add_argument("--proxy", default="", help="proxy URL like http://user:pass@ip:port")

    ap.add_argument("--limit", type=int, default=0, help="limit number of factor_ids to fix")
    ap.add_argument("--dry-run", action="store_true")

    ap.add_argument("--dump", action="store_true", help="write dump to fonbet_factor_catalog_dump.txt")
    ap.add_argument("--dump-path", default="fonbet_factor_catalog_dump.txt", help="dump file path")

    ap.add_argument(
        "--scan-events",
        type=int,
        default=40,
        help="if listBase yields nothing, try eventView for up to N event_ids from DB",
    )

    ap.add_argument(
        "--no-fallback",
        action="store_true",
        help="disable fallback sysId/scopeMarket bruteforce for listBase",
    )

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
        # common alt host
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

    wanted = set(bad_ids)

    dump_path = args.dump_path
    listbase_raw_path = "fonbet_listbase_raw.json" if args.dump else None
    eventview_raw_path = "fonbet_eventview_sample.json" if args.dump else None

    if args.dump:
        try:
            if os.path.exists(dump_path):
                os.remove(dump_path)
        except Exception:
            pass
        dump_txt(dump_path, "CONFIG", [("bases", ", ".join(bases)), ("proxy", "yes" if proxy else "no")])

    # 1) listBase
    net_mapping: Dict[int, str] = {}
    try:
        start = time.time()
        mapping, used_url, meta = fetch_listbase(
            bases=bases,
            lang=args.lang,
            sysid=args.sysid,
            scope_market=args.scope_market,
            proxy=proxy,
            wanted=wanted,
            dump_raw_path=listbase_raw_path,
            try_scopes=not args.no_fallback,
            try_sysids=not args.no_fallback,
        )
        dt = time.time() - start
        net_mapping = mapping
        print(f"[net] listBase OK: {used_url} (mapped={len(net_mapping)}) in {dt:.1f}s")
        if args.dump:
            dump_txt(dump_path, "LISTBASE_META", [(k, str(v)) for k, v in meta.items()])
            dump_txt(dump_path, "UPDATED_NET", [(str(k), v) for k, v in sorted(net_mapping.items())])
    except Exception as e:
        print(f"[net] listBase failed/empty: {e}")

    updated_net = update_names(conn, net_mapping, dry_run=args.dry_run)

    # Remaining after listBase
    remaining = get_bad_factor_ids(conn, limit=args.limit)
    remaining_set = set(remaining)

    # 2) eventView fallback (only if listBase didn't help)
    eventview_mapping: Dict[int, str] = {}
    if remaining and args.scan_events > 0:
        ev_ids = pick_event_ids_for_factors(conn, remaining, limit_events=args.scan_events)
        if ev_ids:
            print(f"[net] eventView: scanning {len(ev_ids)} events ...")
            for idx, ev_id in enumerate(ev_ids, 1):
                m = fetch_eventview(
                    bases=bases,
                    event_id=ev_id,
                    lang=args.lang,
                    proxy=proxy,
                    wanted=remaining_set,
                    dump_raw_path=eventview_raw_path if (args.dump and idx == 1) else None,
                )
                if m:
                    eventview_mapping.update(m)
                    # stop early if we got most ids
                    if len(eventview_mapping) >= min(200, len(remaining_set)):
                        break

            if eventview_mapping:
                print(f"[net] eventView mapped: {len(eventview_mapping)}")
                if args.dump:
                    dump_txt(dump_path, "UPDATED_EVENTVIEW", [(str(k), v) for k, v in sorted(eventview_mapping.items())])

    updated_ev = update_names(conn, eventview_mapping, dry_run=args.dry_run)

    # 3) history text fallback
    remaining2 = get_bad_factor_ids(conn, limit=args.limit)
    remaining2_set = set(remaining2)

    hist_mapping = derive_from_history_text(conn, remaining2)
    hist_mapping = {fid: nm for fid, nm in hist_mapping.items() if fid in remaining2_set}
    print(f"[db] history mapping: {len(hist_mapping)}")

    updated_hist = update_names(conn, hist_mapping, dry_run=args.dry_run)

    remaining3 = get_bad_factor_ids(conn, limit=args.limit)

    print(
        f"[done] updated: {updated_net + updated_ev + updated_hist} "
        f"(net={updated_net}, eventView={updated_ev}, history={updated_hist}); "
        f"remaining bad: {len(remaining3)}"
    )

    if args.dump:
        dump_txt(dump_path, "UPDATED_HISTORY", [(str(k), v) for k, v in sorted(hist_mapping.items())])
        dump_txt(dump_path, "REMAINING_BAD", [(str(fid), "") for fid in remaining3])
        print(f"[dump] written: {dump_path}")
        if listbase_raw_path and os.path.exists(listbase_raw_path):
            print(f"[dump] listBase raw: {listbase_raw_path}")
        if eventview_raw_path and os.path.exists(eventview_raw_path):
            print(f"[dump] eventView sample raw: {eventview_raw_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
