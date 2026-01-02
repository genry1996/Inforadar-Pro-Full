# -*- coding: utf-8 -*-
"""
Fonbet (cy mirror) prematch poller -> MySQL (latest + history) for:
- 1x2
- Totals
- Handicaps

Goal: same pattern as 22bet module (odds_* latest table + *_history snapshots only on change).

How it finds the API URL:
1) If env FONBET_EVENTS_URL is set -> use it.
2) Else tries to parse ./fonbet_debug/captured.json and extract the newest URL that contains "/events/list?"
3) Else you must pass --url.

Recommended: keep your browser-capture script (tools/fonbet_one.py) to refresh the URL/version
when it expires, then paste it into .env as FONBET_EVENTS_URL.

Run once:
  python .\tools\fonbet_prematch_poll.py --once --hours 12

Run loop (every 10s):
  python .\tools\fonbet_prematch_poll.py --interval 10 --hours 12

ENV (.env supported, both project root and this script folder)
- DB / MySQL:
  MYSQL_HOST / MYSQL_PORT / MYSQL_USER / MYSQL_PASSWORD / MYSQL_DB
  or DB_HOST / DB_PORT / DB_USER / DB_PASSWORD / DB_NAME

- Proxy (optional):
  Option A (single var): FONBET_PROXY="http://user:pass@ip:port"
  Option B (split vars): FONBET_PROXY_SERVER + FONBET_PROXY_USERNAME + FONBET_PROXY_PASSWORD
  Fallback: PROXY or PROXY_SERVER + PROXY_USERNAME + PROXY_PASSWORD

- API URL:
  FONBET_EVENTS_URL="https://line02....../events/list?lang=ru&version=...&scopeMarket=1700"

Tables:
- odds_fonbet
- odds_fonbet_history
- odds_fonbet_lines
- odds_fonbet_lines_history

Notes:
- Fonbet JSON schemas vary by mirror/version. This script uses robust heuristics:
  it always dumps raw JSON to --outdir (default ./fonbet_debug) to help refine parsers.
- If extraction finds 0 events/lines, check the saved raw file and update heuristics.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pymysql
import requests

try:
    from zoneinfo import ZoneInfo  # py3.9+
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore


# ----------------------------
# dotenv loading (safe)
# ----------------------------

def _load_env_file(path: Path, override: bool = False) -> bool:
    if not path.exists():
        return False
    try:
        from dotenv import load_dotenv  # type: ignore
        load_dotenv(path, override=override)
        return True
    except Exception:
        pass

    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if override or (k not in os.environ):
            os.environ[k] = v
    return True


def load_env_candidates() -> None:
    here = Path(__file__).resolve().parent
    project_root = here.parent
    candidates = [here / ".env", project_root / ".env", project_root / "parsers" / "playwright_22bet" / ".env"]
    for p in candidates:
        _load_env_file(p, override=False)


load_env_candidates()


def _env(*names: str, default: str = "") -> str:
    for n in names:
        v = (os.getenv(n) or "").strip()
        if v:
            return v
    return default


# ----------------------------
# Time helpers
# ----------------------------

def now_local(tz_name: str) -> dt.datetime:
    if ZoneInfo is None:
        return dt.datetime.now()
    return dt.datetime.now(ZoneInfo(tz_name))


def to_local_naive_from_epoch(ts: Any, tz_name: str) -> Optional[dt.datetime]:
    try:
        if ts is None:
            return None
        if isinstance(ts, str) and not ts.strip():
            return None
        x = int(float(ts))
        # try ms
        if x > 10_000_000_000:
            x = int(x / 1000)
        if x < 1_000_000_000:
            return None
        dtu = dt.datetime.utcfromtimestamp(x).replace(tzinfo=dt.timezone.utc)
        if ZoneInfo is None:
            return dtu.replace(tzinfo=None)
        return dtu.astimezone(ZoneInfo(tz_name)).replace(tzinfo=None)
    except Exception:
        return None


def within_hours(match_time: Optional[dt.datetime], tz_name: str, hours: int) -> bool:
    if match_time is None:
        return False
    now = now_local(tz_name).replace(tzinfo=None)
    return now <= match_time <= now + dt.timedelta(hours=hours)


# ----------------------------
# HTTP helpers
# ----------------------------

def _proxy_url() -> str:
    """
    Proxy resolution order (most specific -> fallback):
    1) FONBET_PROXY (if contains auth or if auth fields exist -> inject)
    2) FONBET_PROXY_SERVER + FONBET_PROXY_USERNAME/PASSWORD
    3) PROXY (if contains auth or if auth fields exist -> inject from PROXY_USERNAME/PASSWORD)
    4) PROXY_SERVER + PROXY_USERNAME/PASSWORD
    """
    # 1) FONBET_PROXY (may be host:port OR already user:pass@host:port)
    p = _env("FONBET_PROXY", default="")
    if p:
        u = _env("FONBET_PROXY_USERNAME", "FONBET_PROXY_USER", default="")
        pw = _env("FONBET_PROXY_PASSWORD", "FONBET_PROXY_PASS", default="")
        if "@" in p:
            return p
        if u and pw:
            m = re.match(r"^(https?://)(.+)$", p.strip())
            if m:
                return f"{m.group(1)}{u}:{pw}@{m.group(2)}"
        return p

    # 2) FONBET_PROXY_SERVER + creds
    server = _env("FONBET_PROXY_SERVER", default="")
    if server:
        u = _env("FONBET_PROXY_USERNAME", "FONBET_PROXY_USER", default="")
        pw = _env("FONBET_PROXY_PASSWORD", "FONBET_PROXY_PASS", default="")
        if u and pw and "@" not in server:
            m = re.match(r"^(https?://)(.+)$", server.strip())
            if m:
                return f"{m.group(1)}{u}:{pw}@{m.group(2)}"
        return server.strip()

    # 3) PROXY (generic)
    p = _env("PROXY", default="")
    if p:
        u = _env("PROXY_USERNAME", "PROXY_USER", default="")
        pw = _env("PROXY_PASSWORD", "PROXY_PASS", default="")
        if "@" in p:
            return p
        if u and pw:
            m = re.match(r"^(https?://)(.+)$", p.strip())
            if m:
                return f"{m.group(1)}{u}:{pw}@{m.group(2)}"
        return p

    # 4) PROXY_SERVER + creds
    server = _env("PROXY_SERVER", default="")
    if not server:
        return ""
    u = _env("PROXY_USERNAME", "PROXY_USER", default="")
    pw = _env("PROXY_PASSWORD", "PROXY_PASS", default="")
    if u and pw and "@" not in server:
        m = re.match(r"^(https?://)(.+)$", server.strip())
        if m:
            return f"{m.group(1)}{u}:{pw}@{m.group(2)}"
    return server.strip()


def _proxies() -> Optional[Dict[str, str]]:
    p = _proxy_url()
    if not p:
        return None
    return {"http": p, "https": p}


def _headers() -> Dict[str, str]:
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "ru,en;q=0.9",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
    }


def fetch_json(url: str, timeout: int = 25) -> Any:
    r = requests.get(url, headers=_headers(), proxies=_proxies(), timeout=timeout)
    r.raise_for_status()
    # requests handles gzip automatically; API should be JSON
    try:
        return r.json()
    except Exception:
        # sometimes returns text json
        return json.loads(r.text)


# ----------------------------
# Robust traversal + parsing heuristics
# ----------------------------

def iter_dicts(obj: Any) -> Iterable[Dict[str, Any]]:
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from iter_dicts(v)
    elif isinstance(obj, list):
        for it in obj:
            yield from iter_dicts(it)


def pick(d: Dict[str, Any], keys: List[str]) -> Any:
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return None


def to_int(x: Any) -> Optional[int]:
    try:
        if x is None or isinstance(x, bool):
            return None
        if isinstance(x, int):
            return x
        s = str(x).strip()
        if not s:
            return None
        return int(float(s))
    except Exception:
        return None


def to_float(x: Any) -> Optional[float]:
    try:
        if x is None or isinstance(x, bool):
            return None
        if isinstance(x, (int, float)):
            return float(x)
        s = str(x).strip().replace(",", ".")
        if not s:
            return None
        return float(s)
    except Exception:
        return None


def normalize_team_name(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip())


def split_event_name(name: str) -> Tuple[Optional[str], Optional[str]]:
    s = name.strip()
    if " — " in s:
        a, b = s.split(" — ", 1)
        return normalize_team_name(a), normalize_team_name(b)
    if " - " in s:
        a, b = s.split(" - ", 1)
        return normalize_team_name(a), normalize_team_name(b)
    if " vs " in s.lower():
        parts = re.split(r"\s+vs\.?\s+", s, flags=re.I)
        if len(parts) >= 2:
            return normalize_team_name(parts[0]), normalize_team_name(parts[1])
    return None, None


def guess_football_sport_ids(data: Any) -> set:
    ids = set()
    for d in iter_dicts(data):
        nm = pick(d, ["name", "sportName", "title", "nm"])
        if isinstance(nm, str) and nm.strip().lower() in ("футбол", "football"):
            sid = to_int(pick(d, ["id", "sportId", "sport_id"]))
            if sid is not None:
                ids.add(sid)
    return ids


@dataclass
class Event:
    event_id: int
    league: str
    event_name: str
    home_team: Optional[str]
    away_team: Optional[str]
    match_time: Optional[dt.datetime]
    odd_1: Optional[float]
    odd_x: Optional[float]
    odd_2: Optional[float]


@dataclass
class Line:
    event_id: int
    league: str
    event_name: str
    match_time: Optional[dt.datetime]
    market_type: str         # total | handicap
    line_value: float
    side_1: str
    side_2: str
    odd_1: Optional[float]
    odd_2: Optional[float]


def extract_events_and_lines(data: Any, tz_name: str, hours: int) -> Tuple[List[Event], List[Line]]:
    football_ids = guess_football_sport_ids(data)

    # Collect event-like dicts
    candidates: Dict[int, Dict[str, Any]] = {}
    for d in iter_dicts(data):
        eid = to_int(pick(d, ["eventId", "event_id", "id", "event", "eId"]))
        if eid is None or eid < 10000:
            continue
        # must have name
        nm = pick(d, ["name", "eventName", "title"])
        if not isinstance(nm, str) or not nm.strip():
            continue
        # must have time
        ts = pick(d, ["startTime", "start_time", "start", "ts", "kickoff", "time"])
        mt = to_local_naive_from_epoch(ts, tz_name)
        if mt is None:
            continue

        # if football ids known, filter when possible
        sid = to_int(pick(d, ["sportId", "sport_id"]))
        if football_ids and sid is not None and sid not in football_ids:
            continue

        # keep first
        candidates.setdefault(eid, d)

    events: List[Event] = []
    lines: List[Line] = []

    # regex for outcomes
    re_total = re.compile(r"(?:тб|тм|over|under|тотал|total)", re.I)
    re_hand = re.compile(r"(?:ф1|ф2|handicap|фора|h1|h2)", re.I)

    for eid, ed in candidates.items():
        name = str(pick(ed, ["name", "eventName", "title"]) or "").strip()
        league = str(pick(ed, ["league", "tournament", "competition", "champ", "categoryName", "leagueName"]) or "").strip()
        ts = pick(ed, ["startTime", "start_time", "start", "ts", "kickoff", "time"])
        mt = to_local_naive_from_epoch(ts, tz_name)

        if not within_hours(mt, tz_name, hours):
            continue

        home = pick(ed, ["team1", "home", "homeName", "teamHome"])
        away = pick(ed, ["team2", "away", "awayName", "teamAway"])
        home_s = normalize_team_name(str(home)) if isinstance(home, str) and home.strip() else None
        away_s = normalize_team_name(str(away)) if isinstance(away, str) and away.strip() else None
        if not home_s or not away_s:
            h2, a2 = split_event_name(name)
            home_s = home_s or h2
            away_s = away_s or a2

        # collect outcome nodes inside this event block
        outcomes: List[Tuple[str, Optional[float], Optional[float]]] = []  # (label, price, param)
        for od in iter_dicts(ed):
            price = to_float(pick(od, ["price", "k", "coef", "value", "odd", "odds"]))
            if price is None:
                continue
            label = pick(od, ["name", "title", "outcome", "label", "shortName"])
            if not isinstance(label, str):
                continue
            label_s = label.strip()
            if not label_s:
                continue
            param = pick(od, ["param", "line", "handicap", "total", "points", "p"])
            pv = to_float(param)
            if pv is None:
                # parse from label like "ТБ(2.5)" or "Ф1(-1.5)"
                m = re.search(r"([+-]?\d+(?:[.,]\d+)?)", label_s)
                if m:
                    pv = to_float(m.group(1))
            outcomes.append((label_s, price, pv))

        # 1x2
        o1 = ox = o2 = None
        for lbl, price, _pv in outcomes:
            l = lbl.lower()
            if l in ("1", "п1", "home", "хозяева"):
                o1 = price
            elif l in ("x", "х", "draw", "ничья"):
                ox = price
            elif l in ("2", "п2", "away", "гости"):
                o2 = price

        events.append(Event(eid, league, name, home_s, away_s, mt, o1, ox, o2))

        # totals and handicaps (pair lines)
        totals_map: Dict[float, Dict[str, Optional[float]]] = {}
        hand_map: Dict[float, Dict[str, Optional[float]]] = {}

        for lbl, price, pv in outcomes:
            if pv is None:
                continue
            l = lbl.lower()

            if re_total.search(lbl):
                side = None
                if "тб" in l or "over" in l or "больше" in l:
                    side = "over"
                elif "тм" in l or "under" in l or "меньше" in l:
                    side = "under"
                if side:
                    totals_map.setdefault(pv, {"over": None, "under": None})
                    totals_map[pv][side] = price
                continue

            if re_hand.search(lbl):
                side = None
                if "ф1" in l or "h1" in l or "home" in l:
                    side = "home"
                elif "ф2" in l or "h2" in l or "away" in l:
                    side = "away"
                if side:
                    hand_map.setdefault(pv, {"home": None, "away": None})
                    hand_map[pv][side] = price
                continue

        for pv, dct in totals_map.items():
            lines.append(Line(eid, league, name, mt, "total", float(pv), "over", "under", dct.get("over"), dct.get("under")))
        for pv, dct in hand_map.items():
            lines.append(Line(eid, league, name, mt, "handicap", float(pv), "home", "away", dct.get("home"), dct.get("away")))

    return events, lines


# ----------------------------
# URL extraction from captured.json
# ----------------------------

def extract_best_url_from_captured(captured_path: Path) -> Optional[str]:
    if not captured_path.exists():
        return None
    try:
        data = json.loads(captured_path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return None

    urls: List[str] = []

    def walk(o: Any):
        if isinstance(o, dict):
            for k, v in o.items():
                if isinstance(v, str) and "/events/list" in v:
                    urls.append(v)
                walk(v)
        elif isinstance(o, list):
            for it in o:
                walk(it)

    walk(data)

    # prefer newest by 'version' parameter (largest)
    def version_of(u: str) -> int:
        m = re.search(r"(?:\?|&)version=(\d+)", u)
        return int(m.group(1)) if m else -1

    urls = sorted(set(urls), key=version_of, reverse=True)
    return urls[0] if urls else None


# ----------------------------
# MySQL
# ----------------------------

def mysql_connect():
    host = _env("MYSQL_HOST", "DB_HOST", default="127.0.0.1")
    port = int(_env("MYSQL_PORT", "DB_PORT", default="3306") or "3306")
    user = _env("MYSQL_USER", "DB_USER", default="root")
    password = _env("MYSQL_PASSWORD", "DB_PASSWORD", default="")
    db = _env("MYSQL_DB", "DB_NAME", default="inforadar")
    return pymysql.connect(
        host=host,
        port=port,
        user=user,
        password=(password or "").strip(),
        database=db,
        charset="utf8mb4",
        autocommit=True,
        cursorclass=pymysql.cursors.DictCursor,
    )


def ensure_schema(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS odds_fonbet (
              id BIGINT AUTO_INCREMENT PRIMARY KEY,
              event_id BIGINT NOT NULL,
              bookmaker VARCHAR(50) NOT NULL,
              sport VARCHAR(50) NOT NULL,
              league VARCHAR(255) NULL,
              event_name VARCHAR(512) NOT NULL,
              home_team VARCHAR(255) NULL,
              away_team VARCHAR(255) NULL,
              market_type VARCHAR(50) NOT NULL DEFAULT '1x2',
              odd_1 DECIMAL(10,3) NULL,
              odd_x DECIMAL(10,3) NULL,
              odd_2 DECIMAL(10,3) NULL,
              match_time DATETIME NULL,
              updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
              UNIQUE KEY uk_fonbet_event_market (event_id, market_type, bookmaker, sport)
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS odds_fonbet_history (
              id BIGINT AUTO_INCREMENT PRIMARY KEY,
              event_id BIGINT NOT NULL,
              bookmaker VARCHAR(50) NOT NULL,
              sport VARCHAR(50) NOT NULL,
              league VARCHAR(255) NULL,
              event_name VARCHAR(512) NOT NULL,
              market_type VARCHAR(50) NOT NULL,
              odd_1 DECIMAL(10,3) NULL,
              odd_x DECIMAL(10,3) NULL,
              odd_2 DECIMAL(10,3) NULL,
              match_time DATETIME NULL,
              captured_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
              INDEX idx_fonbet_hist_event_time (event_id, captured_at)
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS odds_fonbet_lines (
              id BIGINT AUTO_INCREMENT PRIMARY KEY,
              event_id BIGINT NOT NULL,
              bookmaker VARCHAR(50) NOT NULL,
              sport VARCHAR(50) NOT NULL,
              league VARCHAR(255) NULL,
              event_name VARCHAR(512) NOT NULL,
              market_type VARCHAR(50) NOT NULL,
              line_value DECIMAL(10,3) NOT NULL,
              side_1 VARCHAR(20) NOT NULL,
              side_2 VARCHAR(20) NOT NULL,
              odd_1 DECIMAL(10,3) NULL,
              odd_2 DECIMAL(10,3) NULL,
              match_time DATETIME NULL,
              updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
              UNIQUE KEY uk_fonbet_lines (event_id, market_type, line_value, bookmaker, sport)
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS odds_fonbet_lines_history (
              id BIGINT AUTO_INCREMENT PRIMARY KEY,
              event_id BIGINT NOT NULL,
              bookmaker VARCHAR(50) NOT NULL,
              sport VARCHAR(50) NOT NULL,
              league VARCHAR(255) NULL,
              event_name VARCHAR(512) NOT NULL,
              market_type VARCHAR(50) NOT NULL,
              line_value DECIMAL(10,3) NOT NULL,
              side_1 VARCHAR(20) NOT NULL,
              side_2 VARCHAR(20) NOT NULL,
              odd_1 DECIMAL(10,3) NULL,
              odd_2 DECIMAL(10,3) NULL,
              match_time DATETIME NULL,
              captured_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
              INDEX idx_fonbet_lines_hist_event_time (event_id, captured_at)
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
            """
        )


def _eq(a, b) -> bool:
    try:
        return (a is None and b is None) or (a is not None and b is not None and float(a) == float(b))
    except Exception:
        return False


def upsert_event(conn, ev: Event) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO odds_fonbet (event_id, bookmaker, sport, league, event_name, home_team, away_team, market_type,
                                    odd_1, odd_x, odd_2, match_time)
            VALUES (%s,'fonbet','Football',%s,%s,%s,%s,'1x2',%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE
              league=VALUES(league),
              event_name=VALUES(event_name),
              home_team=VALUES(home_team),
              away_team=VALUES(away_team),
              odd_1=VALUES(odd_1),
              odd_x=VALUES(odd_x),
              odd_2=VALUES(odd_2),
              match_time=VALUES(match_time)
            """,
            (ev.event_id, ev.league or None, ev.event_name, ev.home_team, ev.away_team, ev.odd_1, ev.odd_x, ev.odd_2, ev.match_time),
        )


def insert_event_history_if_changed(conn, ev: Event) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT odd_1, odd_x, odd_2
            FROM odds_fonbet_history
            WHERE event_id=%s AND bookmaker='fonbet' AND sport='Football' AND market_type='1x2'
            ORDER BY captured_at DESC
            LIMIT 1
            """,
            (ev.event_id,),
        )
        prev = cur.fetchone() or {}
        if prev and _eq(prev.get("odd_1"), ev.odd_1) and _eq(prev.get("odd_x"), ev.odd_x) and _eq(prev.get("odd_2"), ev.odd_2):
            return
        cur.execute(
            """
            INSERT INTO odds_fonbet_history (event_id, bookmaker, sport, league, event_name, market_type, odd_1, odd_x, odd_2, match_time)
            VALUES (%s,'fonbet','Football',%s,%s,'1x2',%s,%s,%s,%s)
            """,
            (ev.event_id, ev.league or None, ev.event_name, ev.odd_1, ev.odd_x, ev.odd_2, ev.match_time),
        )


def upsert_line(conn, ln: Line) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO odds_fonbet_lines (event_id, bookmaker, sport, league, event_name, market_type, line_value, side_1, side_2,
                                          odd_1, odd_2, match_time)
            VALUES (%s,'fonbet','Football',%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE
              league=VALUES(league),
              event_name=VALUES(event_name),
              side_1=VALUES(side_1),
              side_2=VALUES(side_2),
              odd_1=VALUES(odd_1),
              odd_2=VALUES(odd_2),
              match_time=VALUES(match_time)
            """,
            (ln.event_id, ln.league or None, ln.event_name, ln.market_type, ln.line_value, ln.side_1, ln.side_2, ln.odd_1, ln.odd_2, ln.match_time),
        )


def insert_line_history_if_changed(conn, ln: Line) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT odd_1, odd_2
            FROM odds_fonbet_lines_history
            WHERE event_id=%s AND bookmaker='fonbet' AND sport='Football' AND market_type=%s AND line_value=%s
            ORDER BY captured_at DESC
            LIMIT 1
            """,
            (ln.event_id, ln.market_type, ln.line_value),
        )
        prev = cur.fetchone() or {}
        if prev and _eq(prev.get("odd_1"), ln.odd_1) and _eq(prev.get("odd_2"), ln.odd_2):
            return
        cur.execute(
            """
            INSERT INTO odds_fonbet_lines_history (event_id, bookmaker, sport, league, event_name, market_type, line_value,
                                                  side_1, side_2, odd_1, odd_2, match_time)
            VALUES (%s,'fonbet','Football',%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (ln.event_id, ln.league or None, ln.event_name, ln.market_type, ln.line_value, ln.side_1, ln.side_2, ln.odd_1, ln.odd_2, ln.match_time),
        )


# ----------------------------
# Main
# ----------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="", help="Fonbet events/list URL (optional if env/captured.json exists)")
    ap.add_argument("--tz", default="Europe/Paris")
    ap.add_argument("--hours", type=int, default=12)
    ap.add_argument("--interval", type=int, default=10)
    ap.add_argument("--limit", type=int, default=0, help="limit events written (0 = no limit)")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--outdir", default="fonbet_debug", help="where to dump raw json")
    args = ap.parse_args()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    url = args.url.strip() or _env("FONBET_EVENTS_URL", default="").strip()
    if not url:
        # try captured.json
        project_root = Path(__file__).resolve().parent.parent
        cap = project_root / "fonbet_debug" / "captured.json"
        url = extract_best_url_from_captured(cap) or ""

    if not url:
        print("[ERR] No FONBET_EVENTS_URL. Pass --url or set env FONBET_EVENTS_URL or keep fonbet_debug/captured.json.")
        return 2

    print("======================================================================")
    print("Inforadar Pro - Fonbet prematch poller")
    print(f"URL: {url}")
    print(f"Proxy: {_proxy_url() or 'none'}")
    print(f"Window: {args.hours}h | interval: {args.interval}s | tz={args.tz}")
    print("======================================================================")

    conn = mysql_connect()
    ensure_schema(conn)
    print("✅ MySQL connected + schema ensured")

    while True:
        t0 = time.time()
        try:
            data = fetch_json(url)

            # dump raw
            stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
            raw_path = outdir / "fonbet_events_latest.json"
            raw_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

            events, lines = extract_events_and_lines(data, tz_name=args.tz, hours=args.hours)

            if args.limit and args.limit > 0:
                events = events[: args.limit]

            for ev in events:
                upsert_event(conn, ev)
                insert_event_history_if_changed(conn, ev)

            for ln in lines:
                upsert_line(conn, ln)
                insert_line_history_if_changed(conn, ln)

            dt_s = time.time() - t0
            print(f"✅ saved: events={len(events)} | lines={len(lines)} | {dt_s:.1f}s | raw={raw_path}")

        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"[ERR] {e}")

        if args.once:
            break

        sleep_for = max(1, args.interval - int(time.time() - t0))
        time.sleep(sleep_for)

    try:
        conn.close()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
