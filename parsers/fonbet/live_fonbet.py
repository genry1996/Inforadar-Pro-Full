#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fonbet LIVE parser (football) - MVP (proxy-first).

Почему у тебя было 404 "CYLA01-MA: Not Found" даже на /line/listBase:
- это типичное "маскирование" блокировки по IP/гео. В prematch ты ходишь через шведский прокси,
  а live запускал без него → сервер отдаёт 404 HTML вместо JSON.

Что делает этот файл:
- читает .env из корня проекта (как prematch_fonbet.py)
- использует прокси из FONBET_PROXY / HTTPS_PROXY / HTTP_PROXY
- берёт pv через /line/listBase (scopeMarket=1700) — если доступ есть
- кандидатов берёт из БД fonbet_events (окно времени)
- пробует live eventView: /line/live/eventView и /line/liveLine/eventView
- если получил JSON, пишет коэффициенты в fonbet_odds_history с phase='live'
- помечает fonbet_events.is_live=1 и last_seen_ts

Запуск:
  $env:MYSQL_PASSWORD="***"
  $env:FONBET_PROXY="http://user:pass@ip:port"   # или в .env
  python parsers/fonbet/live_fonbet.py --interval 5 --max-events 200 --debug
"""

import argparse
import datetime as dt
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

import pymysql
import requests

try:
    from dotenv import load_dotenv  # type: ignore
except Exception:
    load_dotenv = None


# -------------------- env / config --------------------

def load_env(project_root: str) -> None:
    """Load .env if python-dotenv available."""
    if load_dotenv is None:
        return
    env_path = os.path.join(project_root, ".env")
    if os.path.exists(env_path):
        load_dotenv(env_path)


def get_proxy() -> Optional[str]:
    # Prefer explicit project var, fallback to standard
    return (
        os.environ.get("FONBET_PROXY")
        or os.environ.get("HTTPS_PROXY")
        or os.environ.get("HTTP_PROXY")
        or os.environ.get("https_proxy")
        or os.environ.get("http_proxy")
    )


def build_requests_session(proxy: Optional[str], debug: bool = False) -> requests.Session:
    s = requests.Session()
    # User-Agent helps some edges; keep simple.
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": os.environ.get("FONBET_LANG", "ru"),
        "Connection": "keep-alive",
    })
    if proxy:
        s.proxies.update({"http": proxy, "https": proxy})
        if debug:
            print(f"[net] using proxy: {proxy}")
    else:
        if debug:
            print("[net] proxy: NONE (⚠️ если у тебя блок, будет 404 HTML)")
    return s


def db_connect() -> pymysql.connections.Connection:
    host = os.environ.get("MYSQL_HOST", "127.0.0.1")
    port = int(os.environ.get("MYSQL_PORT", "3306"))
    user = os.environ.get("MYSQL_USER", "root")
    password = os.environ.get("MYSQL_PASSWORD", "")
    db = os.environ.get("MYSQL_DB", "inforadar")
    # Важно: в твоём стенде mysql контейнер слушает 3306 внутри, а снаружи может быть 3307 — это у тебя уже в .env.
    conn = pymysql.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        database=db,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
    )
    return conn


# -------------------- Fonbet HTTP helpers --------------------

def _is_html_404(resp: requests.Response) -> bool:
    ctype = (resp.headers.get("Content-Type") or "").lower()
    if "text/html" in ctype:
        return True
    # Some edges return HTML without content-type
    body = (resp.text or "")[:200].lower()
    return "<html" in body and "not found" in body


def http_get_json(
    sess: requests.Session,
    url: str,
    params: Dict[str, Any],
    timeout: float,
    debug: bool = False,
) -> Tuple[Optional[Dict[str, Any]], int, str]:
    try:
        r = sess.get(url, params=params, timeout=timeout)
    except requests.RequestException as e:
        return None, -1, f"req_exc:{e.__class__.__name__}"
    status = r.status_code
    # 404 html page is common on blocked IP
    if status != 200:
        if debug:
            body = (r.text or "")[:220].replace("\n", " ")
            print(f"   [dbg] GET fail {status} {url} params={params} body='{body}'")
        return None, status, "http"
    # Try JSON
    try:
        return r.json(), status, "ok"
    except Exception:
        if debug:
            body = (r.text or "")[:220].replace("\n", " ")
            print(f"   [dbg] JSON decode fail {url} status=200 body='{body}'")
        return None, status, "bad_json"


def get_pv_from_listbase(
    sess: requests.Session,
    base: str,
    lang: str,
    sys_id: int,
    scope_market: int,
    debug: bool = False,
) -> Optional[int]:
    url = f"{base}/line/listBase"
    params = {"lang": lang, "sysId": sys_id, "scopeMarket": scope_market}
    j, st, _ = http_get_json(sess, url, params, timeout=10, debug=debug)
    if not j:
        return None
    # listBase version can be in different keys; keep robust
    for k in ("pv", "version", "ver"):
        v = j.get(k)
        if isinstance(v, int):
            return v
        if isinstance(v, str) and v.isdigit():
            return int(v)
    # sometimes nested
    v = j.get("packetVersion") or j.get("packet_version")
    if isinstance(v, int):
        return v
    return None


def fetch_eventview_live(
    sess: requests.Session,
    base: str,
    eid: int,
    lang: str,
    sys_id: int,
    pv: Optional[int],
    debug: bool = False,
) -> Tuple[Optional[Dict[str, Any]], str, int]:
    """
    Returns (json, source, http_status)
      source: LIVE | LIVELINE | PREMATCH | NONE
    """
    # Try live endpoints first
    candidates: List[Tuple[str, str]] = [
        (f"{base}/line/live/eventView", "LIVE"),
        (f"{base}/line/liveLine/eventView", "LIVELINE"),
    ]
    base_params = {"id": eid, "lang": lang, "sysId": sys_id}
    if pv is not None:
        # different mirrors accept different pv key; we try both variants by separate calls
        pass

    # Try with pv keys variations
    pv_variants: List[Dict[str, Any]] = [{}]
    if pv is not None:
        pv_variants = [{"pv": pv}, {"p": pv}, {"ver": pv}, {"version": pv}, {"packetVersion": pv}]

    for url, src in candidates:
        for pv_add in pv_variants:
            params = dict(base_params)
            params.update(pv_add)
            j, st, _ = http_get_json(sess, url, params, timeout=10, debug=debug)
            if j is not None:
                return j, src, st
            if debug and st == 404:
                print(f"   [dbg] eventView {src} 404 for eid={eid}")

    # Fallback: prematch eventView (иногда live отдаёт 404, а prematch отдаёт state=LIVE)
    for url in (f"{base}/line/eventView", f"{base}/line/eventView2"):
        for pv_add in pv_variants:
            params = dict(base_params)
            params.update(pv_add)
            j, st, _ = http_get_json(sess, url, params, timeout=10, debug=debug)
            if j is not None:
                return j, "PREMATCH", st

    return None, "NONE", 404


# -------------------- parsing odds --------------------

def extract_factors(ev: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Extract a flat list of factor records from Fonbet eventView JSON.
    We keep it permissive: support common keys.
    Each record returned should contain: factor_id, odd, param (optional), label (optional)
    """
    out: List[Dict[str, Any]] = []

    # Common places:
    # - ev["customFactors"]
    # - ev["factors"]
    # - ev["events"][0]["factors"] etc.
    candidates: List[Any] = []
    for k in ("customFactors", "factors", "factor", "markets"):
        if k in ev:
            candidates.append(ev.get(k))

    # nested event
    if isinstance(ev.get("event"), dict):
        for k in ("customFactors", "factors"):
            if k in ev["event"]:
                candidates.append(ev["event"].get(k))

    # events list
    if isinstance(ev.get("events"), list) and ev["events"]:
        e0 = ev["events"][0]
        if isinstance(e0, dict):
            for k in ("customFactors", "factors"):
                if k in e0:
                    candidates.append(e0.get(k))

    # Normalize list of dicts
    def push_factor(fd: Dict[str, Any]) -> None:
        fid = fd.get("f") or fd.get("factorId") or fd.get("id") or fd.get("factor_id")
        odd = fd.get("v") or fd.get("odd") or fd.get("value")
        if fid is None or odd is None:
            return
        try:
            fid_i = int(fid)
            odd_f = float(odd)
        except Exception:
            return
        rec: Dict[str, Any] = {"factor_id": fid_i, "odd": odd_f}
        # param / label if present
        if "p" in fd and fd["p"] is not None:
            try:
                rec["param"] = float(fd["p"])
            except Exception:
                pass
        elif "param" in fd and fd["param"] is not None:
            try:
                rec["param"] = float(fd["param"])
            except Exception:
                pass
        if "l" in fd and fd["l"]:
            rec["label"] = str(fd["l"])
        elif "label" in fd and fd["label"]:
            rec["label"] = str(fd["label"])
        out.append(rec)

    def walk(obj: Any) -> None:
        if obj is None:
            return
        if isinstance(obj, list):
            for it in obj:
                walk(it)
        elif isinstance(obj, dict):
            # leaf factor?
            if any(k in obj for k in ("f", "factorId", "factor_id")) and any(k in obj for k in ("v", "odd", "value")):
                push_factor(obj)
                return
            # otherwise traverse values
            for v in obj.values():
                walk(v)

    for c in candidates:
        walk(c)

    # De-dup keep last
    uniq: Dict[int, Dict[str, Any]] = {}
    for r in out:
        uniq[r["factor_id"]] = r
    return list(uniq.values())


def is_live_event(ev: Dict[str, Any], src: str) -> bool:
    """Heuristic: if fetched from live endpoints OR state says live."""
    if src in ("LIVE", "LIVELINE"):
        return True
    st = None
    if isinstance(ev.get("event"), dict):
        st = ev["event"].get("state") or ev["event"].get("st")
    if st is None:
        st = ev.get("state") or ev.get("st")
    if isinstance(st, str):
        s = st.lower()
        if "live" in s or "inplay" in s or "play" in s:
            return True
    # some payloads have timer/score live only
    if isinstance(ev.get("score"), dict) or isinstance(ev.get("timer"), dict):
        return True
    return False


# -------------------- DB writes --------------------

def upsert_live_flags(conn: pymysql.connections.Connection, event_id: int, is_live: int, last_seen_ts: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE fonbet_events SET is_live=%s, last_seen_ts=%s WHERE event_id=%s",
            (is_live, last_seen_ts, event_id),
        )


def insert_odds_rows(
    conn: pymysql.connections.Connection,
    event_id: int,
    rows: List[Dict[str, Any]],
    phase: str,
) -> int:
    if not rows:
        return 0
    now = dt.datetime.now()
    vals = []
    for r in rows:
        vals.append((
            event_id,
            r["factor_id"],
            float(r["odd"]),
            now,
            r.get("param"),
            r.get("label"),
            phase,
        ))
    sql = (
        "INSERT INTO fonbet_odds_history (event_id, factor_id, odd, ts, param, label, phase) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s)"
    )
    with conn.cursor() as cur:
        cur.executemany(sql, vals)
    return len(vals)


# -------------------- main loop --------------------

def pick_candidates(
    conn: pymysql.connections.Connection,
    now_ts: int,
    before_min: int,
    after_min: int,
    limit: int,
) -> List[int]:
    lo = now_ts - before_min * 60
    hi = now_ts + after_min * 60
    with conn.cursor() as cur:
        cur.execute(
            "SELECT event_id FROM fonbet_events "
            "WHERE sport_id=1 AND start_ts BETWEEN %s AND %s "
            "ORDER BY ABS(start_ts - %s) ASC "
            "LIMIT %s",
            (lo, hi, now_ts, limit),
        )
        rows = cur.fetchall()
    return [int(r["event_id"]) for r in rows]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=float, default=5.0)
    ap.add_argument("--max-events", type=int, default=200)
    ap.add_argument("--window-before-min", type=int, default=1440)
    ap.add_argument("--window-after-min", type=int, default=240)
    ap.add_argument("--debug", action="store_true")
    ap.add_argument("--probe-eid", type=int, default=0)
    args = ap.parse_args()

    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    load_env(project_root)

    base = os.environ.get("FONBET_BASE", "https://line01.cy8cff-resources.com").rstrip("/")
    sys_id = int(os.environ.get("FONBET_SYS_ID", "21"))
    lang = os.environ.get("FONBET_LANG", "ru")

    proxy = get_proxy()
    sess = build_requests_session(proxy, debug=args.debug)

    print(f"🏁 Fonbet LIVE | base={base} | sys_id={sys_id} | lang={lang} | interval={args.interval}s | max_events={args.max_events}")
    conn = db_connect()
    print(f"[db] host={os.environ.get('MYSQL_HOST','127.0.0.1')}:{os.environ.get('MYSQL_PORT','3306')} db={os.environ.get('MYSQL_DB','inforadar')} user={os.environ.get('MYSQL_USER','root')} pass_len={len(os.environ.get('MYSQL_PASSWORD',''))}")

    while True:
        t0 = time.time()
        now_ts = int(time.time())

        # Probe mode: test one event id and exit
        if args.probe_eid:
            pv = get_pv_from_listbase(sess, base, lang, sys_id, scope_market=1700, debug=args.debug)
            if pv is None:
                print("⚠️ cannot read pv from listBase (eventView may return 404). Will try without pv.")
            ev, src, st = fetch_eventview_live(sess, base, args.probe_eid, lang, sys_id, pv, debug=args.debug)
            factors = extract_factors(ev) if ev else []
            live_flag = is_live_event(ev, src) if ev else False
            print(f"[probe] eid={args.probe_eid} src={src} http={st} json={'YES' if ev else 'NO'} factors={len(factors)} live={live_flag} pv={pv}")
            return

        pv = get_pv_from_listbase(sess, base, lang, sys_id, scope_market=1700, debug=args.debug)
        if pv is None and args.debug:
            print("   [dbg] pv from listBase: NONE (если prematch у тебя работает через прокси — проверь, что proxy реально подхватился)")

        eids = pick_candidates(conn, now_ts, args.window_before_min, args.window_after_min, args.max_events)
        wrote = 0
        marked = 0
        tried = 0
        ok = 0

        for eid in eids:
            tried += 1
            ev, src, st = fetch_eventview_live(sess, base, eid, lang, sys_id, pv, debug=args.debug)
            if not ev:
                continue
            ok += 1
            factors = extract_factors(ev)
            if not factors:
                continue
            live_flag = is_live_event(ev, src)
            if not live_flag:
                # not live → don't write
                continue
            wrote += insert_odds_rows(conn, eid, factors, phase="live")
            upsert_live_flags(conn, eid, 1, int(time.time()))
            marked += 1

        dur_ms = int((time.time() - t0) * 1000)
        print(f"✅ live tick: candidates={len(eids)} tried={tried} ok_json={ok} wrote_rows={wrote} marked_live={marked} dur={dur_ms}ms ts={dt.datetime.now().strftime('%H:%M:%S')}")
        time.sleep(float(args.interval))


if __name__ == "__main__":
    main()
