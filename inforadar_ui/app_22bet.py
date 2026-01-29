# -*- coding: utf-8 -*-
"""
22BET prematch UI/API (Flask) — 1x2 + Totals/Handicaps (latest + history)

This build adds:
- /prematch_simple (always uses built-in simple UI with correct links)
- /prematch_event/<event_id> now accepts BOTH digits and the literal placeholder "<event_id>"
  (shows a helpful hint instead of 404)
- Optional: FORCE_INLINE_UI=1 to make /prematch and /prematch_event use the simple UI even if templates exist

It keeps all API endpoints:
- /api/odds/prematch
- /api/odds/prematch/history/<event_id>
- /api/odds/prematch/lines/<event_id>
- /api/odds/prematch/lines_history/<event_id>

Run:
  cd D:\Inforadar_Pro\inforadar_ui
  .\venv\Scripts\Activate.ps1
  python .\app_22bet.py
"""

from __future__ import annotations


# Fonbet DB column detection caches
_FONBET_TS_COL_CACHE: Optional[str] = None
_FONBET_LABEL_COL_CACHE: Optional[str] = None

_FONBET_LINE_COL_CACHE = None  # detected numeric line column (handicap/total) in fonbet_odds_history

import os
import json
import time
import re
import datetime as dt
try:
    from zoneinfo import ZoneInfo  # py3.9+
except Exception:
    ZoneInfo = None
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any, Dict, List, Optional

# --- Fonbet Inforadar-like strict market mapping (eventView) --------------------
try:
    from fonbet_inforadar_markets import (
        build_market_map_from_eventview,
        extract_current_odds_from_eventview,
        choose_mainline_total,
        choose_mainline_asian_hcp,
    )
    _HAS_FONBET_INFORADAR_MARKETS = True
except Exception:
    build_market_map_from_eventview = None
    extract_current_odds_from_eventview = None
    choose_mainline_total = None
    choose_mainline_asian_hcp = None
    _HAS_FONBET_INFORADAR_MARKETS = False



import pymysql
# --- Inforadar hotfix: PyMySQL percent escape (DATE_FORMAT/LIKE with params) ---
# Problem: PyMySQL uses Python %-formatting for params. Any literal % inside SQL query
# (inside quotes like '%Y-%m-%d' or LIKE '%abc%') must be escaped as %% or PyMySQL crashes.
def _escape_sql_percent_literals__inforadar(q: str) -> str:
    # Escapes % only inside single-quoted SQL literals.
    # Keeps already-escaped %% intact.
    out = []
    i = 0
    in_str = False
    n = len(q)
    while i < n:
        ch = q[i]
        if not in_str:
            if ch == "'":
                in_str = True
                out.append(ch)
                i += 1
                continue
            out.append(ch)
            i += 1
            continue

        # inside single-quoted literal
        if ch == "'":
            # SQL escaped quote as '' (two single quotes)
            if i + 1 < n and q[i + 1] == "'":
                out.append("''")
                i += 2
                continue
            in_str = False
            out.append(ch)
            i += 1
            continue

        if ch == "%":
            # keep already escaped %%
            if i + 1 < n and q[i + 1] == "%":
                out.append("%%")
                i += 2
                continue
            out.append("%%")
            i += 1
            continue

        out.append(ch)
        i += 1

    return "".join(out)


def _patch_pymysql_execute__inforadar():
    try:
        import pymysql  # noqa: F401
        from pymysql.cursors import Cursor
    except Exception:
        return

    # idempotent: patch only once
    if getattr(Cursor.execute, "percent_escape_patched__inforadar", False):
        return

    _orig_execute = Cursor.execute
    _orig_executemany = Cursor.executemany

    def _exec(self, query, args=None):
        if args is not None and isinstance(query, str) and "%" in query and "'" in query:
            query = _escape_sql_percent_literals__inforadar(query)
        return _orig_execute(self, query, args)

    def _many(self, query, args):
        if args is not None and isinstance(query, str) and "%" in query and "'" in query:
            query = _escape_sql_percent_literals__inforadar(query)
        return _orig_executemany(self, query, args)

    setattr(_exec, "percent_escape_patched__inforadar", True)
    Cursor.execute = _exec
    Cursor.executemany = _many


_patch_pymysql_execute__inforadar()
# --- end Inforadar hotfix ---

from flask import Flask, jsonify, request, render_template, render_template_string, redirect, url_for

APP_TITLE = "Inforadar Pro - Prematch UI"


# --- Filtering helpers (exclude specials / not-real matches) ---
_SPECIAL_ROW_SUBSTRINGS = [
    "special bet", "special bets", "специальн",
    "team vs player", "player vs team", "team vs team",
    "winner", "outright", "top scorer", "goalscorer",
    "1st teams vs 2nd teams", "1st team", "2nd team",
]
_GENERIC_TEAMS = {"home", "away", "hosts", "guests", "host", "guest", "хозяева", "гости", "хозяин", "гость"}
# Words that typically indicate esports/virtual/simulated matches (should be excluded from "football prematch")
_VIRTUAL_NOISE_SUBSTRINGS = [
    "кибер", "cyber", "e-sport", "esport", "esports",
    "efootball", "e-football", "fifa", "pes", "pro evolution",
    "virtual", "simulated", "simulation", "sims", "fantasy",
    "battle", "clash", "arena", "gametime",
]


def _has_nickname_parentheses(s: str) -> bool:
    """
    Detect esports/virtual nicknames inside parentheses:
      Italy (Liu_Kang), Germany (Billy_Alish), Real (Shrek), etc.
    Also filters explicit virtual marker "(x)".

    NOTE: We allow common real-football tags (U20/U21/W/etc).
    """
    for part in re.findall(r"\(([^)]+)\)", s or ""):
        p = (part or "").strip()
        if not p:
            continue
        pl = p.lower()

        # allow-list: typical football tags
        if re.fullmatch(r"u\d{2}", pl):
            continue
        if pl in (
            "w", "women", "жен", "женщины",
            "res", "reserves", "ii", "b", "youth",
            "u23", "u21", "u20", "u19", "u18", "u17", "u16",
        ):
            continue

        # explicit virtual marker seen in Fonbet virtual football: (x)
        if pl == "x":
            return True

        # underscore is a very strong esports marker
        if "_" in p:
            return True

        # mixed letters+digits like Player123
        if re.search(r"[A-Za-z]", p) and re.search(r"\d", p):
            return True

        # mostly ASCII letters and short -> nickname
        ascii_ratio = sum(1 for ch in p if ord(ch) < 128) / max(1, len(p))
        if ascii_ratio > 0.75 and len(p) <= 24 and re.search(r"[A-Za-z]", p):
            return True

        # mixed Cyrillic + Latin inside parentheses is almost always nickname
        if re.search(r"[A-Za-z]", p) and re.search(r"[А-Яа-я]", p):
            return True

    return False

def _is_special_row(r: dict) -> bool:
    """Filter out non-football / specials / esports-like rows from events list (22bet + fonbet)."""
    league = str(r.get("league_name") or r.get("league") or r.get("tournament") or "").lower()

    # match/title may live under different keys depending on endpoint
    name = str(
        r.get("event_name")
        or r.get("name")
        or r.get("match")
        or r.get("event")
        or r.get("teams")
        or ""
    ).lower()

    # teams: support both 22bet naming and fonbet naming
    h = str(
        r.get("home_team")
        or r.get("home")
        or r.get("team1")
        or r.get("team_1")
        or r.get("t1")
        or r.get("team1_name")
        or r.get("team1Title")
        or ""
    ).lower()

    a = str(
        r.get("away_team")
        or r.get("away")
        or r.get("team2")
        or r.get("team_2")
        or r.get("t2")
        or r.get("team2_name")
        or r.get("team2Title")
        or ""
    ).lower()

    blob = " ".join([league, name, h, a]).strip()

    # 0) Placeholder teams (Хозяева/Гости, Home/Away, etc.) — always exclude
    if (h.strip() in _GENERIC_TEAMS) or (a.strip() in _GENERIC_TEAMS):
        return True
    if any(x in blob for x in ("хозяева", "гости", "home", "away", "hosts", "guests", "host", "guest")):
        return True

    # 1) obvious esports / virtual markers
    if any(ss in blob for ss in _VIRTUAL_NOISE_SUBSTRINGS):
        return True

    # 2) "vs" patterns are typical for cyber/virtual listings
    if re.search(r"(^|[^a-z])vs([^a-z]|$)", blob):
        return True

    # 3) underscores in names (Shang_Tsung) are almost always cyber
    if "_" in blob:
        return True

    # 4) Nicknames in parentheses, including "(x)" marker
    if _has_nickname_parentheses(blob):
        return True

    # 5) specials / not real prematch
    if any(ss in blob for ss in _SPECIAL_ROW_SUBSTRINGS):
        return True

    return False

    # match/title may live under different keys depending on endpoint
    name = str(
        r.get("event_name")
        or r.get("name")
        or r.get("match")
        or r.get("event")
        or ""
    ).lower()

    # teams: support both 22bet naming and fonbet naming
    h = str(
        r.get("home_team")
        or r.get("home")
        or r.get("team1")
        or r.get("team_1")
        or r.get("t1")
        or ""
    ).lower()
    a = str(
        r.get("away_team")
        or r.get("away")
        or r.get("team2")
        or r.get("team_2")
        or r.get("t2")
        or ""
    ).lower()

    blob = " ".join([league, name, h, a]).strip()

    # 0) "generic teams" placeholders (Хозяева/Гости, Home/Away, etc.)
    if (h.strip() in _GENERIC_TEAMS) or (a.strip() in _GENERIC_TEAMS):
        return True
    # also if whole match name is just placeholders
    if any(x in blob for x in ("хозяева", "гости", "home", "away", "hosts", "guests")) and not any(
        ch.isdigit() for ch in blob
    ):
        # keep this strict: only placeholders without digits (U20 etc.)
        if (h.strip() in _GENERIC_TEAMS) or (a.strip() in _GENERIC_TEAMS) or ("хозяева" in blob and "гости" in blob):
            return True

    # 1) specials / not real prematch
    if any(ss in blob for ss in _SPECIAL_ROW_SUBSTRINGS):
        return True

    # 2) esports / virtual / simulated / FIFA etc
    if any(ss in blob for ss in _VIRTUAL_NOISE_SUBSTRINGS):
        return True

    # 3) Nicknames in parentheses, including "(x)" markers seen in virtual football feeds
    if _has_nickname_parentheses(h) or _has_nickname_parentheses(a) or _has_nickname_parentheses(name):
        return True

    # 4) very common virtual pattern: "(x)" on teams
    if "(x)" in blob or "( x )" in blob:
        return True

    return False
def _load_env_file(path: Path, override: bool = False) -> bool:
    if not path.exists():
        return False

    try:
        from dotenv import load_dotenv  # type: ignore
        load_dotenv(path, override=override)
        return True
    except Exception:
        pass

    # fallback parser
    try:
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
    except Exception:
        return True


def load_env_candidates() -> None:
    here = Path(__file__).resolve().parent
    project_root = here.parent
    cands = [
        here / ".env",
        project_root / "parsers" / "playwright_22bet" / ".env",
        project_root / ".env",
    ]
    loaded = False
    for p in cands:
        loaded = _load_env_file(p, override=False) or loaded
    if loaded:
        print(f"[env] loaded from: {project_root / 'parsers' / 'playwright_22bet' / '.env'} | {project_root / '.env'}")


load_env_candidates()


def _env(*names: str, default: str = "") -> str:
    for n in names:
        v = (os.getenv(n) or "").strip()
        if v:
            return v
    return default


def db_connect():
    host = _env("MYSQL_HOST", "DB_HOST", default="127.0.0.1")
    port = int(_env("MYSQL_PORT", "DB_PORT", default="3306") or "3306")
    user = _env("MYSQL_USER", "DB_USER", default="root")
    password = _env("MYSQL_PASSWORD", "DB_PASSWORD", default="")
    db = _env("MYSQL_DB", "DB_NAME", default="inforadar")

    return pymysql.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        database=db,
        charset="utf8mb4",
        autocommit=True,
        cursorclass=pymysql.cursors.DictCursor,
    )


def safe_int(x: Any, default: int = 0) -> int:
    try:
        if x is None:
            return default
        if isinstance(x, bool):
            return int(x)
        if isinstance(x, int):
            return x
        if isinstance(x, float):
            return int(x)
        s = str(x).strip()
        if s == "":
            return default
        # handle "1,234" or "1.234"
        s = s.replace(",", ".")
        return int(float(s))
    except Exception:
        return default

def safe_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        if isinstance(v, (int, float)):
            return float(v)
        s = str(v).strip().replace(",", ".")
        if s == "":
            return default
        return float(s)
    except Exception:
        return default


# --- Fonbet sport_id helpers (football default) ---------------------------------

FOOTBALL_DEFAULT_CANDIDATES = [11918, 11937, 11917]

_SOCCER_KEYWORDS = [
    "football", "soccer", "футбол", "премьер", "premier", "liga", "league", "serie", "bundes",
    "кубок", "cup", "championship", "чемпионат", "лига",
]
_SOCCER_TEAM_HINTS = [
    " fc", "фк ", "ф.к", "united", "city", "real ", "atletico", "sporting", "benfica", "porto",
    "juventus", "milan", "inter", "barcelona", "arsenal", "chelsea", "liverpool", "manchester",
]

_HOCKEY_HINTS = ["u20", "u18", "whl", "ahl", "nhl", "broncos", "marlies", "monsters", "wildcats"]
_INDIVIDUAL_RX = re.compile(r"^[A-Za-zА-ЯЁ][\w\-\.'’]+(?:\s+[A-Za-zА-ЯЁ][\w\-\.'’]+)?\s+[A-Za-zА-ЯЁ]\.?$", re.U)

def _score_soccer_like(team1: str, team2: str, league: str) -> int:
    t1 = (team1 or "").strip()
    t2 = (team2 or "").strip()
    lg = (league or "").strip().lower()
    s = 0

    # league hints
    for k in _SOCCER_KEYWORDS:
        if k in lg:
            s += 2

    t = f" {t1.lower()}  {t2.lower()} "
    for k in _SOCCER_TEAM_HINTS:
        if k.strip() in t:
            s += 2

    # penalize individual sports (darts/tennis/table tennis)
    if t1 and _INDIVIDUAL_RX.match(t1) and t2 and _INDIVIDUAL_RX.match(t2):
        s -= 6

    # penalize obvious hockey / NA sports words
    for k in _HOCKEY_HINTS:
        if k in t:
            s -= 3

    # bonus if looks like club vs club (many chars, no trailing initials)
    if len(t1) >= 8 and len(t2) >= 8 and not (_INDIVIDUAL_RX.match(t1) or _INDIVIDUAL_RX.match(t2)):
        s += 1

    return s

def _guess_football_sport_id_from_items(items: List[Dict[str, Any]]) -> int:
    best_sid, best_score = 0, -10**9
    for it in items or []:
        sid = safe_int(it.get("sport_id"), 0)
        score = 0
        for sm in (it.get("sample") or [])[:5]:
            score += _score_soccer_like(sm.get("team1") or "", sm.get("team2") or "", sm.get("league_name") or "")
        if score > best_score:
            best_sid, best_score = sid, score
    # require some confidence
    return best_sid if best_score >= 3 else 0

def _football_sport_id(cur) -> int:
    # 1) explicit env override
    env_sid = safe_int(os.environ.get("FONBET_FOOTBALL_SPORT_ID"), 0)
    if env_sid > 0:
        return env_sid

    # 2) try mapping table if exists
    try:
        cur.execute("SHOW TABLES LIKE 'fonbet_sports'")
        if cur.fetchone():
            cur.execute("SELECT sport_id FROM fonbet_sports WHERE LOWER(name) LIKE %s LIMIT 1", ("%футбол%",))
            r = cur.fetchone()
            if r and safe_int(r.get("sport_id"), 0) > 0:
                return int(r["sport_id"])
            cur.execute("SELECT sport_id FROM fonbet_sports WHERE LOWER(name) LIKE %s LIMIT 1", ("%football%",))
            r = cur.fetchone()
            if r and safe_int(r.get("sport_id"), 0) > 0:
                return int(r["sport_id"])
    except Exception:
        pass

    # 3) common known candidates (if present at all)
    try:
        for sid in FOOTBALL_DEFAULT_CANDIDATES:
            cur.execute("SELECT 1 FROM fonbet_events WHERE sport_id=%s LIMIT 1", (sid,))
            if cur.fetchone():
                return sid
    except Exception:
        pass

    return 0

# -------------------------------------------------------------------------------


def parse_limit(default: int = 2000) -> int:
    return safe_int(request.args.get("limit", default), default)


def _dt_to_str(v: Any) -> Any:
    try:
        if hasattr(v, "isoformat"):
            return v.isoformat(sep=" ", timespec="seconds")
    except Exception:
        pass
    return v


def api_fonbet_events_impl():
    """Internal implementation for listing fonbet events."""
    hours = safe_int(request.args.get("hours", 12), 12)
    limit = safe_int(request.args.get("limit", 200), 200)
    q = (request.args.get("q") or "").strip()
    # Default behavior: if sport_id is NOT provided -> use ENV football id; if provided (even 0) -> respect it.
    env_football_sid = safe_int(_env("FONBET_FOOTBALL_SPORT_ID", default="1"), 0)
    if "sport_id" in request.args:
        sport_id = safe_int(request.args.get("sport_id", 0), 0)  # 0 = no filter
    else:
        sport_id = env_football_sid if env_football_sid > 0 else 0

    # normalize bounds
    hours = max(1, min(168, int(hours)))
    limit = max(1, min(2000, int(limit)))

    with db_connect() as conn:
        with conn.cursor() as cur:
            rows = _sql_fonbet_events(cur, hours=hours, q=q, limit=limit, sport_id=sport_id)

            drops_map = {}
            try:
                ts_col = _fonbet_ts_col(cur)
                drops_map = _sql_fonbet_drops_map(cur, ts_col=ts_col) or {}
            except Exception:
                drops_map = {}

    items = []
    for r in rows or []:
        eid = safe_int(r.get("event_id"), 0)
        dm = drops_map.get(eid) or {}

        item = {
            "event_id": eid,
            "sport_id": safe_int(r.get("sport_id"), 0),
            "league_name": r.get("league_name") or "",
            "team1": r.get("team1") or "",
            "team2": r.get("team2") or "",
            "start_time": str(r.get("start_time") or ""),
            "drops": int(dm.get("drops") or 0),
            "max_drop": dm.get("max_drop"),
        }
        item["match"] = f'{item["team1"]} — {item["team2"]}'.strip(" —")

        # HARD filter: remove cyber/virtual/esports placeholders from football list
        if _is_special_row(item):
            continue

        items.append(item)
    return jsonify({"events": items})





def _force_inline() -> bool:
    return _env("FORCE_INLINE_UI", default="0").lower() in ("1", "true", "yes", "y")


# ------------------------------
# Flask app
# ------------------------------

app = Flask(__name__)

@app.route("/__whoami")
def __whoami():
    return jsonify({"running_file": __file__})

@app.route("/__routes")
def __routes():
    routes = []
    for rule in sorted(app.url_map.iter_rules(), key=lambda r: str(r)):
        routes.append({"rule": str(rule), "methods": sorted([m for m in rule.methods if m not in ("HEAD","OPTIONS")])})
    return jsonify({"count": len(routes), "routes": routes})



# ------------------------------
# API: list prematch odds (latest) + summary Total 2.5 / Hcap 0
# ------------------------------

@app.route("/api/odds/prematch")
def api_prematch_odds():
    sport = request.args.get("sport", "Football")
    hours = safe_int(request.args.get("hours", 12)) or 12
    tz_name = request.args.get("tz") or os.getenv("PREMATCH_TZ", "Europe/Paris")
    # match_time in DB is saved as naive datetime in parser tz; so window must be computed in the same tz
    now = dt.datetime.utcnow()
    if ZoneInfo is not None:
        try:
            now = now.replace(tzinfo=dt.timezone.utc).astimezone(ZoneInfo(tz_name)).replace(tzinfo=None)
        except Exception:
            pass
    to_dt = now + dt.timedelta(hours=hours)
    limit = parse_limit()

    q = """
        SELECT o.*
        FROM odds_22bet o
        JOIN (
            SELECT event_id, MAX(updated_at) AS mx
            FROM odds_22bet
            WHERE bookmaker='22bet'
              AND sport=%s
              AND market_type='1x2'
              AND event_id IS NOT NULL
              AND match_time IS NOT NULL
              AND match_time >= %s
              AND match_time < %s
            GROUP BY event_id
        ) t ON t.event_id=o.event_id AND t.mx=o.updated_at
        ORDER BY o.match_time ASC
        LIMIT %s
    """

    try:
        with db_connect() as conn:
            with conn.cursor() as cur:
                cur.execute(q, (sport, now, to_dt, limit))
                rows: List[Dict[str, Any]] = cur.fetchall() or []

                # Summary lines: Total 2.5 and Handicap 0 for list page
                event_ids = sorted({safe_int(r.get("event_id") or 0) for r in rows if safe_int(r.get("event_id") or 0) > 0})
                lines_map: Dict[int, Dict[str, Any]] = {}

                if event_ids:
                    in_sql = ",".join(["%s"] * len(event_ids))
                    ql = f"""
                        SELECT event_id, market_type, line_value, odd_1, odd_2
                        FROM odds_22bet_lines
                        WHERE bookmaker='22bet' AND sport=%s
                          AND event_id IN ({in_sql})
                          AND (
                                (market_type='total' AND line_value=2.5)
                             OR (market_type='handicap' AND line_value=0)
                          )
                    """
                    cur.execute(ql, [sport, *event_ids])
                    for r in (cur.fetchall() or []):
                        eid = safe_int(r.get("event_id") or 0)
                        mt = (r.get("market_type") or "").lower()
                        lv = float(r.get("line_value") or 0.0)
                        o1 = r.get("odd_1")
                        o2 = r.get("odd_2")
                        d = lines_map.setdefault(eid, {})
                        if mt == "total" and abs(lv - 2.5) < 1e-9:
                            d["total_25_over"] = float(o1) if o1 is not None else None
                            d["total_25_under"] = float(o2) if o2 is not None else None
                        elif mt == "handicap" and abs(lv - 0.0) < 1e-9:
                            d["hcap_0_home"] = float(o1) if o1 is not None else None
                            d["hcap_0_away"] = float(o2) if o2 is not None else None

        # Normalize JSON output
        for r in rows:
            r["event_id"] = safe_int(r.get("event_id") or 0)
            r["market_type"] = r.get("market_type") or "1x2"

            for k in ("odd_1", "odd_x", "odd_2"):
                if k in r and r[k] is not None:
                    try:
                        r[k] = float(r[k])
                    except Exception:
                        pass

            for k in ("updated_at", "match_time", "created_at"):
                if k in r and r[k] is not None:
                    r[k] = _dt_to_str(r[k])

            s = lines_map.get(r["event_id"], {})
            r["total_25_over"] = s.get("total_25_over")
            r["total_25_under"] = s.get("total_25_under")
            r["hcap_0_home"] = s.get("hcap_0_home")
            r["hcap_0_away"] = s.get("hcap_0_away")

        return jsonify(rows)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ------------------------------
# API: per-event history (1x2)
# ------------------------------

@app.route("/api/odds/prematch/history/<int:event_id>")
def api_prematch_history(event_id: int):
    limit = safe_int(request.args.get("limit", 300), 300)
    market = request.args.get("market", "1x2")

    q = """
        SELECT event_id, event_name, league, sport, market_type,
               odd_1, odd_x, odd_2, captured_at
        FROM odds_22bet_history
        WHERE bookmaker='22bet' AND event_id=%s AND market_type=%s
        ORDER BY captured_at DESC
        LIMIT %s
    """

    try:
        with db_connect() as conn:
            with conn.cursor() as cur:
                cur.execute(q, (event_id, market, limit))
                rows = cur.fetchall() or []
            rows = [r for r in rows if not _is_special_row(r)]

        for r in rows:
            for k in ("odd_1", "odd_x", "odd_2"):
                if k in r and r[k] is not None:
                    try:
                        r[k] = float(r[k])
                    except Exception:
                        pass
            if r.get("captured_at") is not None:
                r["captured_at"] = _dt_to_str(r["captured_at"])

        return jsonify(list(reversed(rows)))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ------------------------------
# API: per-event lines (latest)
# ------------------------------

@app.route("/api/odds/prematch/lines/<int:event_id>")
def api_prematch_lines(event_id: int):
    sport = request.args.get("sport", "Football")
    market = request.args.get("market", "total")  # total | handicap
    limit = safe_int(request.args.get("limit", 800), 800)

    q = """
        SELECT event_id, event_name, league, sport, market_type, line_value,
               side_1, side_2, odd_1, odd_2, match_time, updated_at
        FROM odds_22bet_lines
        WHERE bookmaker='22bet' AND sport=%s AND event_id=%s AND market_type=%s
        ORDER BY line_value ASC
        LIMIT %s
    """

    try:
        with db_connect() as conn:
            with conn.cursor() as cur:
                cur.execute(q, (sport, event_id, market, limit))
                rows = cur.fetchall() or []
            rows = [r for r in rows if not _is_special_row(r)]

        for r in rows:
            for k in ("odd_1", "odd_2", "line_value"):
                if k in r and r[k] is not None:
                    try:
                        r[k] = float(r[k])
                    except Exception:
                        pass
            for k in ("updated_at", "match_time"):
                if k in r and r[k] is not None:
                    r[k] = _dt_to_str(r[k])

        return jsonify(rows)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ------------------------------
# API: per-event lines history (by market + line_value)
# ------------------------------

@app.route("/api/odds/prematch/lines_history/<int:event_id>")
def api_prematch_lines_history(event_id: int):
    sport = request.args.get("sport", "Football")
    market = request.args.get("market", "total")  # total | handicap
    limit = safe_int(request.args.get("limit", 600), 600)
    line_value = request.args.get("line_value", None)

    if line_value is None:
        return jsonify({"error": "line_value is required"}), 400

    try:
        lv = float(str(line_value).replace(",", "."))
    except Exception:
        return jsonify({"error": "bad line_value"}), 400

    q = """
        SELECT event_id, event_name, league, sport, market_type, line_value,
               side_1, side_2, odd_1, odd_2, match_time, captured_at
        FROM odds_22bet_lines_history
        WHERE bookmaker='22bet' AND sport=%s AND event_id=%s AND market_type=%s AND line_value=%s
        ORDER BY captured_at DESC
        LIMIT %s
    """

    try:
        with db_connect() as conn:
            with conn.cursor() as cur:
                cur.execute(q, (sport, event_id, market, lv, limit))
                rows = cur.fetchall() or []
            rows = [r for r in rows if not _is_special_row(r)]

        for r in rows:
            for k in ("odd_1", "odd_2", "line_value"):
                if k in r and r[k] is not None:
                    try:
                        r[k] = float(r[k])
                    except Exception:
                        pass
            for k in ("captured_at", "match_time"):
                if k in r and r[k] is not None:
                    r[k] = _dt_to_str(r[k])

        return jsonify(list(reversed(rows)))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ------------------------------
# UI pages (simple built-in)
# ------------------------------

PREMATCH_SIMPLE_INLINE = r"""
<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{{title}}</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 16px; }
    .bar { display:flex; gap:8px; align-items:center; margin-bottom: 12px; flex-wrap: wrap; }
    table { width: 100%; border-collapse: collapse; }
    th, td { border-bottom: 1px solid #eee; padding: 8px; text-align: left; font-size: 14px; }
    th { background: #fafafa; position: sticky; top: 0; z-index: 1; }
    a { color: #0b5fff; text-decoration: none; }
    a:hover { text-decoration: underline; }
    .muted { color: #777; font-size: 12px; }
    .num { font-variant-numeric: tabular-nums; }
    .pill { display:inline-block; padding:2px 8px; border-radius: 999px; background:#f2f5ff; font-size:12px; }
  </style>
</head>
<body>

  <div class="nav" style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:12px;">
    <a href="/prematch" style="text-decoration:none;padding:6px 10px;border-radius:999px;border:1px solid #e4e7ec;color:#667085;font-weight:800;font-size:13px;">22BET</a>
    <a href="/fonbet" style="text-decoration:none;padding:6px 10px;border-radius:999px;border:1px solid #e4e7ec;color:#667085;font-weight:800;font-size:13px;">FONBET</a>
    <a href="/betwatch" style="text-decoration:none;padding:6px 10px;border-radius:999px;border:1px solid #e4e7ec;color:#667085;font-weight:800;font-size:13px;">BETWATCH</a>
  </div>
  <h2>22BET Prematch — simple view</h2>
  <div class="muted">Если в красивом UI “Connection error” — открой эту страницу для проверки API.</div>
  <div class="bar">
    <label>Sport:
      <select id="sport"><option>Football</option></select>
    </label>
    <label>Limit:
      <select id="limit">
        <option>200</option>
        <option selected>2000</option>
      </select>
    </label>
    <button onclick="loadData()">Refresh</button>
    <span id="status" class="muted"></span>
  </div>

  <table>
    <thead>
      <tr>
        <th>League</th><th>Event</th><th>1</th><th>X</th><th>2</th>
        <th>Total 2.5 (O/U)</th><th>Hcap 0 (H/A)</th><th class="muted">Updated</th>
      </tr>
    </thead>
    <tbody id="tbody"></tbody>
  </table>

<script>
async function loadData(){
  const limit=document.getElementById('limit').value;
  const sport=document.getElementById('sport').value;
  const status=document.getElementById('status');
  status.textContent='Loading...';
  try{
    const r=await fetch(`/api/odds/prematch?limit=${limit}&sport=${encodeURIComponent(sport)}`);
    const rows=await r.json();
    const tb=document.getElementById('tbody');
    tb.innerHTML='';
    for(const row of rows){
      const tr=document.createElement('tr');
      const eid=row.event_id||0;
      const eventCell = eid ? `<a href="/prematch_event/${eid}">${row.event_name}</a>` : `${row.event_name} <span class="pill">no event_id</span>`;
      const updated = row.updated_at ? new Date(row.updated_at).toLocaleString() : '';
      const t25 = (row.total_25_over!=null || row.total_25_under!=null) ? `${row.total_25_over ?? ''} / ${row.total_25_under ?? ''}` : '';
      const h0  = (row.hcap_0_home!=null || row.hcap_0_away!=null) ? `${row.hcap_0_home ?? ''} / ${row.hcap_0_away ?? ''}` : '';
      tr.innerHTML =
        `<td>${row.league||'Unknown'}</td>`+
        `<td>${eventCell}</td>`+
        `<td class="num">${row.odd_1 ?? ''}</td>`+
        `<td class="num">${row.odd_x ?? ''}</td>`+
        `<td class="num">${row.odd_2 ?? ''}</td>`+
        `<td class="num">${t25}</td>`+
        `<td class="num">${h0}</td>`+
        `<td class="muted">${updated}</td>`;
      tb.appendChild(tr);
    }
    status.textContent = `OK: ${rows.length} events`;
  }catch(e){
    console.error(e);
    status.textContent='Failed (see console)';
  }
}
loadData();
</script>
</body>
</html>
"""

EVENT_SIMPLE_INLINE = r"""
<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{{title}}</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 16px; }
    a { color: #0b5fff; text-decoration: none; }
    a:hover { text-decoration: underline; }
    .tabs { display:flex; gap:10px; margin: 10px 0 16px; flex-wrap: wrap; }
    .tab { padding: 6px 10px; border: 1px solid #ddd; border-radius: 8px; cursor:pointer; }
    .tab.active { background: #f2f5ff; border-color: #c7d2ff; }
    table { width: 100%; border-collapse: collapse; }
    th, td { border-bottom: 1px solid #eee; padding: 8px; text-align: left; font-size: 14px; }
    th { background: #fafafa; position: sticky; top: 0; z-index: 1; }
    .muted { color: #777; font-size: 12px; }
    .box { border: 1px solid #eee; border-radius: 12px; padding: 12px; }
    .num { font-variant-numeric: tabular-nums; }
  </style>
</head>
<body>

  <div class="nav" style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:12px;">
    <a href="/prematch" style="text-decoration:none;padding:6px 10px;border-radius:999px;border:1px solid #e4e7ec;color:#667085;font-weight:800;font-size:13px;">22BET</a>
    <a href="/fonbet" style="text-decoration:none;padding:6px 10px;border-radius:999px;border:1px solid #e4e7ec;color:#667085;font-weight:800;font-size:13px;">FONBET</a>
    <a href="/betwatch" style="text-decoration:none;padding:6px 10px;border-radius:999px;border:1px solid #e4e7ec;color:#667085;font-weight:800;font-size:13px;">BETWATCH</a>
  </div>
  <div><a href="/prematch_simple">← Back to /prematch_simple</a></div>
  <h2 id="h">Event #{{event_id}}</h2>
  <div class="tabs">
    <div class="tab active" data-tab="1x2" onclick="switchTab('1x2')">1X2</div>
    <div class="tab" data-tab="handicap" onclick="switchTab('handicap')">Handicap</div>
    <div class="tab" data-tab="total" onclick="switchTab('total')">Total</div>
  </div>

  <div id="panel-1x2" class="box">
    <div class="muted" id="meta"></div>
    <h3>1X2 history</h3>
    <table><thead><tr><th>Time</th><th>1</th><th>X</th><th>2</th></tr></thead><tbody id="hist"></tbody></table>
  </div>

  <div id="panel-handicap" class="box" style="display:none;">
    <h3>Handicap (latest)</h3>
    <div class="muted">Click a line to load its history.</div>
    <table><thead><tr><th>Line</th><th>Home</th><th>Away</th><th class="muted">Updated</th></tr></thead><tbody id="lines-handicap"></tbody></table>
    <div style="height:10px;"></div>
    <h3>Handicap history (selected line)</h3>
    <div class="muted" id="hcap-hint">Select a line above.</div>
    <table><thead><tr><th>Time</th><th>Home</th><th>Away</th></tr></thead><tbody id="hist-handicap"></tbody></table>
  </div>

  <div id="panel-total" class="box" style="display:none;">
    <h3>Total (latest)</h3>
    <div class="muted">Click a line to load its history.</div>
    <table><thead><tr><th>Line</th><th>Over</th><th>Under</th><th class="muted">Updated</th></tr></thead><tbody id="lines-total"></tbody></table>
    <div style="height:10px;"></div>
    <h3>Total history (selected line)</h3>
    <div class="muted" id="tot-hint">Select a line above.</div>
    <table><thead><tr><th>Time</th><th>Over</th><th>Under</th></tr></thead><tbody id="hist-total"></tbody></table>
  </div>

<script>
function switchTab(name){
  for(const el of document.querySelectorAll('.tab')) el.classList.toggle('active', el.dataset.tab===name);
  for(const p of ['1x2','handicap','total']) document.getElementById('panel-'+p).style.display = (p===name)?'block':'none';
}

async function load1x2(){
  const r = await fetch(`/api/odds/prematch/history/{{event_id}}?limit=500&market=1x2`);
  const tb = document.getElementById('hist');
  tb.innerHTML = '';
  if(!r.ok){ tb.innerHTML = `<tr><td colspan="4">API error</td></tr>`; return; }
  const rows = await r.json();
  if(!rows.length){ tb.innerHTML = `<tr><td colspan="4">No history yet (wait 1-2 minutes)</td></tr>`; return; }
  document.getElementById('h').textContent = rows[0].event_name || `Event #{{event_id}}`;
  document.getElementById('meta').textContent = `${rows[0].league||'Unknown'} · ${rows[0].sport||''}`;
  for(const row of rows){
    const t = row.captured_at ? new Date(row.captured_at).toLocaleString() : '';
    const tr=document.createElement('tr');
    tr.innerHTML = `<td>${t}</td><td class="num">${row.odd_1 ?? ''}</td><td class="num">${row.odd_x ?? ''}</td><td class="num">${row.odd_2 ?? ''}</td>`;
    tb.appendChild(tr);
  }
}

async function loadLines(market){
  const r = await fetch(`/api/odds/prematch/lines/{{event_id}}?market=${encodeURIComponent(market)}&limit=800`);
  const tb = document.getElementById(market==='total' ? 'lines-total' : 'lines-handicap');
  tb.innerHTML = '';
  if(!r.ok){ tb.innerHTML = `<tr><td colspan="4">API error</td></tr>`; return; }
  const rows = await r.json();
  if(!rows.length){ tb.innerHTML = `<tr><td colspan="4">No lines yet (wait 1-2 minutes)</td></tr>`; return; }
  for(const row of rows){
    const tr=document.createElement('tr');
    const updated = row.updated_at ? new Date(row.updated_at).toLocaleString() : '';
    const lv = row.line_value;
    const a = row.odd_1 ?? '';
    const b = row.odd_2 ?? '';
    tr.style.cursor = 'pointer';
    tr.title = 'Click to load history';
    tr.onclick = () => loadLineHistory(market, lv);
    tr.innerHTML = `<td class="num">${lv}</td><td class="num">${a}</td><td class="num">${b}</td><td class="muted">${updated}</td>`;
    tb.appendChild(tr);
  }
}

async function loadLineHistory(market, lineValue){
  const hintId = market==='total' ? 'tot-hint' : 'hcap-hint';
  const tbId   = market==='total' ? 'hist-total' : 'hist-handicap';
  document.getElementById(hintId).textContent = `History: ${market} line ${lineValue}`;
  const r = await fetch(`/api/odds/prematch/lines_history/{{event_id}}?market=${encodeURIComponent(market)}&line_value=${encodeURIComponent(lineValue)}&limit=600`);
  const tb = document.getElementById(tbId);
  tb.innerHTML = '';
  if(!r.ok){ tb.innerHTML = `<tr><td colspan="3">API error</td></tr>`; return; }
  const rows = await r.json();
  if(!rows.length){ tb.innerHTML = `<tr><td colspan="3">No history yet</td></tr>`; return; }
  for(const row of rows){
    const t = row.captured_at ? new Date(row.captured_at).toLocaleString() : '';
    const tr=document.createElement('tr');
    tr.innerHTML = `<td>${t}</td><td class="num">${row.odd_1 ?? ''}</td><td class="num">${row.odd_2 ?? ''}</td>`;
    tb.appendChild(tr);
  }
}

async function loadAll(){
  await load1x2();
  await loadLines('handicap');
  await loadLines('total');
}
loadAll();
</script>
</body>
</html>
"""

PREMATCH_PAGE_INLINE = r"""
<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Inforadar — 22BET Prematch</title>
  <style>
    :root{
      --bg:#f6f8fc;
      --card:#ffffff;
      --text:#101828;
      --muted:#667085;
      --border:#e4e7ec;
      --brand:#2b6cff;
      --shadow: 0 8px 24px rgba(16,24,40,.08);
      --radius:14px;
      --mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
    }
    html,body{height:100%;}
    body{
      margin:0;
      font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif;
      background:var(--bg);
      color:var(--text);
    }
    .topbar{
      position:sticky; top:0; z-index:10;
      background:rgba(255,255,255,.85);
      backdrop-filter: blur(10px);
      border-bottom:1px solid var(--border);
    }
    .topbar-inner{
      max-width:1400px;
      margin:0 auto;
      padding:12px 16px;
      display:flex;
      align-items:center;
      justify-content:space-between;
      gap:12px;
    }
    .brand{
      display:flex; align-items:center; gap:10px;
      font-weight:800; letter-spacing:.2px;
    }
    .dot{
      width:12px;height:12px;border-radius:50%;
      background:var(--brand);
      box-shadow:0 0 0 6px rgba(43,108,255,.14);
    }
    .nav{
      display:flex; gap:14px; color:var(--muted); font-size:14px;
    }
    .nav a{ color:inherit; text-decoration:none; padding:6px 10px; border-radius:999px; }
    .nav a:hover{ background:#f1f4ff; color:var(--brand); }
    .wrap{
      max-width:1400px;
      margin:0 auto;
      padding:16px;
    }
    .grid{
      display:grid;
      grid-template-columns: 320px 1fr;
      gap:14px;
    }
    @media (max-width: 1100px){
      .grid{grid-template-columns:1fr;}
    }
    .card{
      background:var(--card);
      border:1px solid var(--border);
      border-radius:var(--radius);
      box-shadow: var(--shadow);
    }
    .card h3{
      margin:0;
      padding:14px 14px 10px;
      font-size:14px;
      color:var(--muted);
      font-weight:700;
      text-transform: uppercase;
      letter-spacing: .08em;
    }
    .card .body{ padding: 0 14px 14px; }
    label{ display:block; font-size:12px; color:var(--muted); margin:10px 0 6px; }
    input, select, button{
      width:100%;
      box-sizing:border-box;
      border:1px solid var(--border);
      border-radius: 10px;
      padding:10px 10px;
      font-size:14px;
      background:#fff;
      color:var(--text);
      outline:none;
    }
    input:focus, select:focus{
      border-color: rgba(43,108,255,.55);
      box-shadow: 0 0 0 4px rgba(43,108,255,.12);
    }
    .row{ display:flex; gap:10px; }
    .row > *{ flex:1; }
    button{
      cursor:pointer;
      background: var(--brand);
      color:white;
      border-color: transparent;
      font-weight:700;
    }
    button:hover{ filter: brightness(.97); }
    .ghost{
      background:#fff;
      color:var(--text);
      border-color:var(--border);
      font-weight:700;
    }
    .ghost:hover{ background:#f9fafb; }
    .status{
      margin-top:10px;
      font-size:12px;
      color:var(--muted);
      display:flex;
      gap:10px;
      align-items:center;
      flex-wrap:wrap;
    }
    .badge{
      display:inline-flex; align-items:center; gap:8px;
      padding:6px 10px;
      border:1px solid var(--border);
      border-radius:999px;
      font-size:12px;
      background:#fff;
    }
    .led{ width:8px; height:8px; border-radius:50%; background:#98a2b3; }
    .led.ok{ background:#12b76a; }
    .led.err{ background:#f04438; }
    .table-card{ overflow:hidden; }
    .table-top{
      padding:12px 14px;
      display:flex;
      justify-content:space-between;
      align-items:center;
      gap:12px;
      border-bottom:1px solid var(--border);
    }
    .table-top .title{
      display:flex; flex-direction:column; gap:2px;
    }
    .table-top .title b{ font-size:16px; }
    .table-top .title span{ font-size:12px; color:var(--muted); }
    .pager{
      display:flex; gap:8px; align-items:center; flex-wrap:wrap;
      font-size:12px; color:var(--muted);
    }
    .pager button{
      width:auto;
      padding:8px 12px;
      border-radius:10px;
      border:1px solid var(--border);
      background:#fff;
      color:var(--text);
      font-weight:700;
    }
    .pager button:hover{ background:#f9fafb; }
    .pager .num{ font-family:var(--mono); color:var(--text); }
    table{
      width:100%;
      border-collapse:separate;
      border-spacing:0;
      font-size:13px;
    }
    thead th{
      position:sticky; top:0;
      background:#fff;
      border-bottom:1px solid var(--border);
      text-align:left;
      padding:10px 12px;
      color:var(--muted);
      font-size:12px;
      font-weight:800;
      z-index:2;
      white-space:nowrap;
    }
    tbody td{
      padding:10px 12px;
      border-bottom:1px solid #f1f2f5;
      vertical-align:middle;
      white-space:nowrap;
    }
    tbody tr:hover{ background:#fbfcff; }
    a{ color:var(--brand); text-decoration:none; }
    a:hover{ text-decoration:underline; }
    .mono{ font-family:var(--mono); font-variant-numeric: tabular-nums; }
    .muted{ color:var(--muted); }
    .pill{
      display:inline-flex; align-items:center;
      padding:2px 8px;
      border-radius:999px;
      border:1px solid var(--border);
      color:var(--muted);
      font-size:12px;
      background:#fff;
    }
    .right{ text-align:right; }
    .scroll{
      max-height: calc(100vh - 190px);
      overflow:auto;
    }
    .hint{
      font-size:12px;
      color:var(--muted);
      line-height:1.35;
      margin-top:8px;
    }
  </style>
</head>
<body>
  <div class="topbar">
    <div class="topbar-inner">
      <div class="brand"><span class="dot"></span> INFORADAR <span class="pill">22BET • prematch</span></div>
      <div class="nav">
        <a href="/prematch">22BET</a>
        <a href="/fonbet">FONBET</a>
        <a href="/betwatch">BETWATCH</a>
        <a href="/prematch_simple">Debug</a>
      </div>
    </div>
  </div>

  <div class="wrap">
    <div class="grid">
      <div class="card">
        <h3>Filters</h3>
        <div class="body">
          <label>Sport</label>
          <select id="sport">
            <option value="Football" selected>Football</option>
          </select>

          <label>Search (team / league)</label>
          <input id="q" placeholder="e.g. Arsenal, Premier League"/>

          <label>League</label>
          <select id="league">
            <option value="">All leagues</option>
          </select>

          <div class="row">
            <div>
              <label>Rows</label>
              <select id="rows">
                <option value="50" selected>50</option>
                <option value="100">100</option>
                <option value="200">200</option>
              </select>
            </div>
            <div>
              <label>Sort</label>
              <select id="sort">
                <option value="time" selected>By time</option>
                <option value="updated">By updated</option>
              </select>
            </div>
          </div>

          <div class="row">
            <div>
              <label>Hide “Special bets”</label>
              <select id="hideSpecial">
                <option value="1" selected>Yes</option>
                <option value="0">No</option>
              </select>
            </div>
            <div>
              <label>Auto refresh</label>
              <select id="autorefresh">
                <option value="0">Off</option>
                <option value="15">15s</option>
                <option value="30" selected>30s</option>
                <option value="60">60s</option>
              </select>
            </div>
          </div>

          <div class="row" style="margin-top:10px;">
            <button id="btnRefresh">Refresh</button>
            <button class="ghost" id="btnReset" type="button">Reset</button>
          </div>

          <div class="status">
            <span class="badge"><span id="led" class="led"></span><span id="status">idle</span></span>
            <span class="badge">events: <span id="cnt" class="mono">0</span></span>
            <span class="badge">shown: <span id="shown" class="mono">0</span></span>
          </div>

          <div class="hint">
            Подсказка: кликай по матчу → откроется <span class="mono">/prematch_event/&lt;event_id&gt;</span> с историей 1X2 и линиями тоталов/фор.
          </div>
        </div>
      </div>

      <div class="card table-card">
        <div class="table-top">
          <div class="title">
            <b>Prematch</b>
            <span>1X2 + Total 2.5 + Handicap 0 (summary)</span>
          </div>
          <div class="pager">
            <button id="prev">Prev</button>
            <span>page <span id="page" class="num">1</span>/<span id="pages" class="num">1</span></span>
            <button id="next">Next</button>
          </div>
        </div>

        <div class="scroll">
          <table>
            <thead>
              <tr>
                <th style="min-width:180px;">League</th>
                <th style="min-width:260px;">Event</th>
                <th class="right">1</th>
                <th class="right">X</th>
                <th class="right">2</th>
                <th class="right">Total 2.5<br><span class="muted">(O / U)</span></th>
                <th class="right">Hcap 0<br><span class="muted">(H / A)</span></th>
                <th style="min-width:155px;">Start</th>
                <th style="min-width:155px;">Updated</th>
              </tr>
            </thead>
            <tbody id="tbody"></tbody>
          </table>
        </div>
      </div>
    </div>
  </div>

<script>
let ALL = [];
let timer = null;

function fmtDT(s){
  if(!s) return '';
  const d = new Date(s);
  if(isNaN(d.getTime())) return s;
  return d.toLocaleString();
}
function toNum(x){
  if(x===null || x===undefined || x==='') return null;
  const n = Number(x);
  return Number.isFinite(n) ? n : null;
}
function uniq(arr){ return Array.from(new Set(arr)); }

function setLed(state){
  const led = document.getElementById('led');
  led.classList.remove('ok','err');
  if(state==='ok') led.classList.add('ok');
  if(state==='err') led.classList.add('err');
}

async function fetchData(){
  const sport = document.getElementById('sport').value;
  const status = document.getElementById('status');
  status.textContent = 'loading...';
  setLed('');
  try{
    const r = await fetch(`/api/odds/prematch?limit=2000&sport=${encodeURIComponent(sport)}`);
    if(!r.ok) throw new Error('HTTP '+r.status);
    ALL = await r.json();
    status.textContent = 'ok';
    setLed('ok');
    document.getElementById('cnt').textContent = ALL.length;
    rebuildLeagueOptions();
    render();
  }catch(e){
    console.error(e);
    status.textContent = 'failed';
    setLed('err');
    ALL = [];
    document.getElementById('cnt').textContent = '0';
    document.getElementById('shown').textContent = '0';
    document.getElementById('tbody').innerHTML = `<tr><td colspan="9" class="muted">Connection error. See console.</td></tr>`;
  }
}

function rebuildLeagueOptions(){
  const leagueSel = document.getElementById('league');
  const current = leagueSel.value;
  const leagues = uniq(ALL.map(r => r.league || 'Unknown')).sort((a,b)=>a.localeCompare(b));
  leagueSel.innerHTML = `<option value="">All leagues</option>` + leagues.map(l => `<option value="${escapeHtml(l)}">${escapeHtml(l)}</option>`).join('');
  if(leagues.includes(current)) leagueSel.value = current;
}

function escapeHtml(s){
  return String(s ?? '').replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
}

function filtered(){
  const q = (document.getElementById('q').value || '').trim().toLowerCase();
  const league = document.getElementById('league').value;
  const hideSpecial = document.getElementById('hideSpecial').value === '1';

  return ALL.filter(r => {
    const ev = (r.event_name || '').toLowerCase();
    const lg = (r.league || 'Unknown');
    if(hideSpecial && ev.includes('special bets')) return false;
    if(league && lg !== league) return false;
    if(q && !(ev.includes(q) || String(lg).toLowerCase().includes(q))) return false;
    return true;
  });
}

function sortRows(rows){
  const sort = document.getElementById('sort').value;
  if(sort==='updated'){
    rows.sort((a,b) => String(b.updated_at||'').localeCompare(String(a.updated_at||'')));
  }else{
    rows.sort((a,b) => String(a.match_time||'').localeCompare(String(b.match_time||'')));
  }
  return rows;
}

let page = 1;

function render(){
  const rowsPerPage = Number(document.getElementById('rows').value || 50);
  let rows = filtered();
  rows = sortRows(rows);
  const total = rows.length;
  document.getElementById('shown').textContent = total;

  const pages = Math.max(1, Math.ceil(total / rowsPerPage));
  if(page > pages) page = pages;
  document.getElementById('page').textContent = page;
  document.getElementById('pages').textContent = pages;

  const slice = rows.slice((page-1)*rowsPerPage, page*rowsPerPage);

  const tb = document.getElementById('tbody');
  tb.innerHTML = '';
  if(!slice.length){
    tb.innerHTML = `<tr><td colspan="9" class="muted">No events for current filters.</td></tr>`;
    return;
  }

  for(const r of slice){
    const eid = r.event_id || 0;
    const ev = eid ? `<a href="/prematch_event/${eid}">${escapeHtml(r.event_name||'')}</a>` : `${escapeHtml(r.event_name||'')} <span class="pill">no id</span>`;
    const t25 = (r.total_25_over!=null || r.total_25_under!=null) ? `${toNum(r.total_25_over) ?? ''} / ${toNum(r.total_25_under) ?? ''}` : '';
    const h0  = (r.hcap_0_home!=null || r.hcap_0_away!=null) ? `${toNum(r.hcap_0_home) ?? ''} / ${toNum(r.hcap_0_away) ?? ''}` : '';
    const tr = document.createElement('tr');
    tr.innerHTML =
      `<td>${escapeHtml(r.league||'Unknown')}</td>`+
      `<td>${ev}</td>`+
      `<td class="right mono">${toNum(r.odd_1) ?? ''}</td>`+
      `<td class="right mono">${toNum(r.odd_x) ?? ''}</td>`+
      `<td class="right mono">${toNum(r.odd_2) ?? ''}</td>`+
      `<td class="right mono">${escapeHtml(t25)}</td>`+
      `<td class="right mono">${escapeHtml(h0)}</td>`+
      `<td class="mono">${fmtDT(r.match_time)}</td>`+
      `<td class="mono">${fmtDT(r.updated_at)}</td>`;
    tb.appendChild(tr);
  }
}

function resetFilters(){
  document.getElementById('q').value = '';
  document.getElementById('league').value = '';
  document.getElementById('rows').value = '50';
  document.getElementById('sort').value = 'time';
  document.getElementById('hideSpecial').value = '1';
  page = 1;
  render();
}

function applyAutoRefresh(){
  const sec = Number(document.getElementById('autorefresh').value || 0);
  if(timer) { clearInterval(timer); timer = null; }
  if(sec > 0){
    timer = setInterval(fetchData, sec * 1000);
  }
}

document.getElementById('btnRefresh').addEventListener('click', (e)=>{ e.preventDefault(); fetchData(); });
document.getElementById('btnReset').addEventListener('click', (e)=>{ e.preventDefault(); resetFilters(); });
document.getElementById('q').addEventListener('input', ()=>{ page=1; render(); });
document.getElementById('league').addEventListener('change', ()=>{ page=1; render(); });
document.getElementById('rows').addEventListener('change', ()=>{ page=1; render(); });
document.getElementById('sort').addEventListener('change', ()=>{ page=1; render(); });
document.getElementById('hideSpecial').addEventListener('change', ()=>{ page=1; render(); });
document.getElementById('autorefresh').addEventListener('change', applyAutoRefresh);

document.getElementById('prev').addEventListener('click', ()=>{ page = Math.max(1, page-1); render(); });
document.getElementById('next').addEventListener('click', ()=>{
  const rowsPerPage = Number(document.getElementById('rows').value || 50);
  const total = filtered().length;
  const pages = Math.max(1, Math.ceil(total / rowsPerPage));
  page = Math.min(pages, page+1);
  render();
});

// init
applyAutoRefresh();
fetchData();
</script>
</body>
</html>

"""

EVENT_PAGE_INLINE = r"""
<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Inforadar — Event {{event_id}}</title>
  <style>
    :root{
      --bg:#f6f8fc; --card:#fff; --text:#101828; --muted:#667085; --border:#e4e7ec;
      --brand:#2b6cff; --shadow:0 8px 24px rgba(16,24,40,.08); --radius:14px;
      --mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
    }
    body{ margin:0; font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif; background:var(--bg); color:var(--text); }
    .top{
      position:sticky; top:0; z-index:10;
      background:rgba(255,255,255,.85); backdrop-filter: blur(10px);
      border-bottom:1px solid var(--border);
    }
    .top-inner{
      max-width:1200px; margin:0 auto; padding:12px 16px;
      display:flex; align-items:center; justify-content:space-between; gap:12px;
    }
    a{ color:var(--brand); text-decoration:none; }
    a:hover{ text-decoration:underline; }
    .wrap{ max-width:1200px; margin:0 auto; padding:16px; }
    .card{ background:var(--card); border:1px solid var(--border); border-radius:var(--radius); box-shadow:var(--shadow); overflow:hidden; }
    .header{
      padding:14px 16px;
      display:flex; flex-direction:column; gap:6px;
      border-bottom:1px solid var(--border);
    }
    .title{ font-size:20px; font-weight:900; letter-spacing:.2px; }
    .meta{ color:var(--muted); font-size:13px; }
    .tabs{
      display:flex; gap:10px; padding:12px 16px; border-bottom:1px solid var(--border); flex-wrap:wrap;
    }
    .tab{
      padding:8px 12px;
      border:1px solid var(--border);
      border-radius:999px;
      cursor:pointer;
      background:#fff;
      font-weight:800;
      font-size:13px;
      color:var(--muted);
      user-select:none;
    }
    .tab.active{ background:#f1f4ff; border-color:#c7d2ff; color:var(--brand); }
    .section{ padding: 14px 16px; }
    .section h3{ margin:0 0 6px; font-size:14px; color:var(--muted); text-transform:uppercase; letter-spacing:.08em; }
    .hint{ font-size:12px; color:var(--muted); margin:0 0 10px; line-height:1.35; }
    table{ width:100%; border-collapse:separate; border-spacing:0; font-size:13px; }
    th, td{ border-bottom:1px solid #f1f2f5; padding:10px 12px; text-align:left; white-space:nowrap; }
    th{ background:#fff; position:sticky; top:0; z-index:2; color:var(--muted); font-size:12px; font-weight:900; }
    .mono{ font-family:var(--mono); font-variant-numeric: tabular-nums; }
    .right{ text-align:right; }
    .grid{ display:grid; grid-template-columns: 1fr 1fr; gap:14px; }
    @media(max-width: 980px){ .grid{ grid-template-columns:1fr; } }
    .panel{ border:1px solid var(--border); border-radius:12px; overflow:hidden; }
    .panel .panel-title{
      padding:10px 12px; border-bottom:1px solid var(--border);
      background:#fbfcff; font-weight:900; color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.08em;
    }
    .panel .panel-body{ max-height: 420px; overflow:auto; }
    .row-click{ cursor:pointer; }
    .row-click:hover{ background:#fbfcff; }
    .muted{ color:var(--muted); }
  </style>
</head>
<body>
  <div class="top">
    <div class="top-inner" style="display:flex;align-items:center;justify-content:space-between;gap:12px;">
      <div style="display:flex;align-items:center;gap:12px;">
        <a href="/prematch" style="font-weight:800;">← Back</a>
        <span class="mono" style="color:var(--muted);">event_id: {{event_id}}</span>
      </div>
      <div style="display:flex;gap:10px;flex-wrap:wrap;">
        <a href="/prematch" style="text-decoration:none;color:var(--muted);font-weight:800;">22BET</a>
        <a href="/fonbet" style="text-decoration:none;color:var(--muted);font-weight:800;">FONBET</a>
        <a href="/betwatch" style="text-decoration:none;color:var(--muted);font-weight:800;">BETWATCH</a>
      </div>
    </div>
  </div>

  <div class="wrap">
    <div class="card">
      <div class="header">
        <div id="title" class="title">Event #{{event_id}}</div>
        <div id="meta" class="meta">Loading…</div>
      </div>

      <div class="tabs">
        <div class="tab active" data-tab="1x2">1X2 history</div>
        <div class="tab" data-tab="handicap">Handicap</div>
        <div class="tab" data-tab="total">Total</div>
      </div>

      <div id="panel-1x2" class="section">
        <h3>1X2</h3>
        <div class="hint">История изменений (точки появятся по мере работы парсера).</div>
        <div class="panel">
          <div class="panel-body">
            <table>
              <thead><tr><th>Time</th><th class="right">1</th><th class="right">X</th><th class="right">2</th></tr></thead>
              <tbody id="hist-1x2"></tbody>
            </table>
          </div>
        </div>
      </div>

      <div id="panel-handicap" class="section" style="display:none;">
        <h3>Handicap</h3>
        <div class="hint">Сверху — актуальные линии. Кликни линию → снизу загрузится история именно по этой линии.</div>

        <div class="grid">
          <div class="panel">
            <div class="panel-title">Handicap — latest</div>
            <div class="panel-body">
              <table>
                <thead><tr><th>Line</th><th class="right">Home</th><th class="right">Away</th><th>Updated</th></tr></thead>
                <tbody id="latest-handicap"></tbody>
              </table>
            </div>
          </div>

          <div class="panel">
            <div class="panel-title" id="hcap-h-title">Handicap — history</div>
            <div class="panel-body">
              <table>
                <thead><tr><th>Time</th><th class="right">Home</th><th class="right">Away</th></tr></thead>
                <tbody id="hist-handicap"></tbody>
              </table>
            </div>
          </div>
        </div>
      </div>

      <div id="panel-total" class="section" style="display:none;">
        <h3>Total</h3>
        <div class="hint">Показываем только “стандартные” линии (шаг 0.5) — как у Inforadar.</div>

        <div class="grid">
          <div class="panel">
            <div class="panel-title">Total — latest</div>
            <div class="panel-body">
              <table>
                <thead><tr><th>Line</th><th class="right">Over</th><th class="right">Under</th><th>Updated</th></tr></thead>
                <tbody id="latest-total"></tbody>
              </table>
            </div>
          </div>

          <div class="panel">
            <div class="panel-title" id="tot-h-title">Total — history</div>
            <div class="panel-body">
              <table>
                <thead><tr><th>Time</th><th class="right">Over</th><th class="right">Under</th></tr></thead>
                <tbody id="hist-total"></tbody>
              </table>
            </div>
          </div>
        </div>
      </div>

    </div>
  </div>

<script>
const EID = {{event_id}};

function fmtDT(s){
  if(!s) return '';
  const d = new Date(s);
  if(isNaN(d.getTime())) return s;
  return d.toLocaleString();
}
function toNum(x){
  if(x===null || x===undefined || x==='') return null;
  const n = Number(x);
  return Number.isFinite(n) ? n : null;
}
function isStdTotal(v){
  if(v===null) return false;
  if(v < 0 || v > 10) return false;
  return Math.abs(v*2 - Math.round(v*2)) < 1e-9;
}
function isStdHcap(v){
  if(v===null) return false;
  if(v < -5 || v > 5) return false;
  return Math.abs(v*4 - Math.round(v*4)) < 1e-9;
}

function switchTab(tab){
  for(const t of document.querySelectorAll('.tab')){
    t.classList.toggle('active', t.dataset.tab===tab);
  }
  document.getElementById('panel-1x2').style.display = tab==='1x2' ? '' : 'none';
  document.getElementById('panel-handicap').style.display = tab==='handicap' ? '' : 'none';
  document.getElementById('panel-total').style.display = tab==='total' ? '' : 'none';
}
for(const t of document.querySelectorAll('.tab')){
  t.addEventListener('click', ()=>switchTab(t.dataset.tab));
}

async function load1x2(){
  const tb = document.getElementById('hist-1x2');
  tb.innerHTML = `<tr><td colspan="4" class="muted">Loading…</td></tr>`;
  const r = await fetch(`/api/odds/prematch/history/${EID}?limit=500&market=1x2`);
  if(!r.ok){ tb.innerHTML = `<tr><td colspan="4" class="muted">API error</td></tr>`; return; }
  const rows = await r.json();
  tb.innerHTML = '';
  if(!rows.length){ tb.innerHTML = `<tr><td colspan="4" class="muted">No history yet — wait 1–2 cycles</td></tr>`; return; }
  document.getElementById('title').textContent = rows[0].event_name || `Event #${EID}`;
  document.getElementById('meta').textContent = `${rows[0].league || 'Unknown'} · ${rows[0].sport || ''}`;
  for(const row of rows){
    const tr = document.createElement('tr');
    tr.innerHTML = `<td class="mono">${fmtDT(row.captured_at)}</td>
                    <td class="right mono">${toNum(row.odd_1) ?? ''}</td>
                    <td class="right mono">${toNum(row.odd_x) ?? ''}</td>
                    <td class="right mono">${toNum(row.odd_2) ?? ''}</td>`;
    tb.appendChild(tr);
  }
}

async function loadLatestLines(market){
  const tb = document.getElementById(market==='total' ? 'latest-total' : 'latest-handicap');
  tb.innerHTML = `<tr><td colspan="4" class="muted">Loading…</td></tr>`;
  const r = await fetch(`/api/odds/prematch/lines/${EID}?market=${encodeURIComponent(market)}&limit=2000`);
  if(!r.ok){ tb.innerHTML = `<tr><td colspan="4" class="muted">API error</td></tr>`; return; }
  let rows = await r.json();
  tb.innerHTML = '';
  if(!rows.length){ tb.innerHTML = `<tr><td colspan="4" class="muted">No lines yet</td></tr>`; return; }

  rows = rows.filter(x=>{
    const v = toNum(x.line_value);
    return market==='total' ? isStdTotal(v) : isStdHcap(v);
  });

  if(!rows.length){ tb.innerHTML = `<tr><td colspan="4" class="muted">No standard lines</td></tr>`; return; }

  rows.sort((a,b)=>(toNum(a.line_value)??0)-(toNum(b.line_value)??0));

  for(const row of rows){
    const lv = toNum(row.line_value);
    const tr = document.createElement('tr');
    tr.className = 'row-click';
    tr.title = 'Click to load history';
    tr.addEventListener('click', ()=>loadLineHistory(market, lv));
    tr.innerHTML = `<td class="mono">${lv ?? ''}</td>
                    <td class="right mono">${toNum(row.odd_1) ?? ''}</td>
                    <td class="right mono">${toNum(row.odd_2) ?? ''}</td>
                    <td class="mono">${fmtDT(row.updated_at)}</td>`;
    tb.appendChild(tr);
  }
}

async function loadLineHistory(market, lv){
  const titleId = market==='total' ? 'tot-h-title' : 'hcap-h-title';
  const tb = document.getElementById(market==='total' ? 'hist-total' : 'hist-handicap');
  document.getElementById(titleId).textContent = `${market} — history (line ${lv})`;
  tb.innerHTML = `<tr><td colspan="3" class="muted">Loading…</td></tr>`;
  const r = await fetch(`/api/odds/prematch/lines_history/${EID}?market=${encodeURIComponent(market)}&line_value=${encodeURIComponent(lv)}&limit=800`);
  if(!r.ok){ tb.innerHTML = `<tr><td colspan="3" class="muted">API error</td></tr>`; return; }
  const rows = await r.json();
  tb.innerHTML = '';
  if(!rows.length){ tb.innerHTML = `<tr><td colspan="3" class="muted">No history yet (wait next cycles)</td></tr>`; return; }
  for(const row of rows){
    const tr = document.createElement('tr');
    tr.innerHTML = `<td class="mono">${fmtDT(row.captured_at)}</td>
                    <td class="right mono">${toNum(row.odd_1) ?? ''}</td>
                    <td class="right mono">${toNum(row.odd_2) ?? ''}</td>`;
    tb.appendChild(tr);
  }
}

async function init(){
  await load1x2();
  await loadLatestLines('handicap');
  await loadLatestLines('total');
}
init();
</script>
</body>
</html>

"""
# ------------------------------
# FONBET UI (inline) + BETWATCH placeholder
# ------------------------------

_FONBET_TS_COL_CACHE: Optional[str] = None

def _fonbet_ts_col(cur) -> str:
    """Try to detect timestamp column name in fonbet_odds_history."""
    global _FONBET_TS_COL_CACHE
    if _FONBET_TS_COL_CACHE:
        return _FONBET_TS_COL_CACHE
    candidates = ("ts", "created_at", "captured_at", "updated_at", "time", "dt")
    try:
        cur.execute("SHOW COLUMNS FROM fonbet_odds_history")
        cols = [r.get("Field") for r in (cur.fetchall() or []) if isinstance(r, dict)]
        for c in candidates:
            if c in cols:
                return c
    except Exception:
        pass
    return _FONBET_TS_COL_CACHE

def _fonbet_label_col(cur) -> Optional[str]:
    """Try to detect a factor label column in fonbet_odds_history (optional)."""
    global _FONBET_LABEL_COL_CACHE
    # cache: None = unknown; "" = not found
    if _FONBET_LABEL_COL_CACHE is not None:
        return _FONBET_LABEL_COL_CACHE or None

    candidates = (
        "factor_label", "factor_name", "factor_title",
        "label", "name", "title",
        "factor", "factor_text", "caption", "short_title",
    )
    try:
        cur.execute("SHOW COLUMNS FROM fonbet_odds_history")
        cols = [r.get("Field") for r in (cur.fetchall() or []) if isinstance(r, dict)]
        for c in candidates:
            if c in cols:
                _FONBET_LABEL_COL_CACHE = c
                return c
    except Exception:
        pass

    _FONBET_LABEL_COL_CACHE = ""
    return None


def _fonbet_param_col(cur) -> Optional[str]:
    """
    Detect numeric parameter/line column in fonbet_odds_history, if present.
    Fonbet sometimes stores template labels like "Фора (%P)" / "Тотал %P",
    while the actual line value is stored in a separate DB column.
    """
    global _FONBET_PARAM_COL_CACHE
    # cache: None = unknown; "" = not found
    if _FONBET_PARAM_COL_CACHE is not None:
        return _FONBET_PARAM_COL_CACHE or None

    candidates = (
        "param", "p", "line", "param_value", "p_value", "pval", "pv",
        "handicap", "total_line", "value", "val",
    )
    try:
        cur.execute("SHOW COLUMNS FROM fonbet_odds_history")
        cols = [r.get("Field") for r in (cur.fetchall() or []) if isinstance(r, dict)]
        for c in candidates:
            if c in cols:
                _FONBET_PARAM_COL_CACHE = c
                return c
    except Exception:
        pass

    _FONBET_PARAM_COL_CACHE = ""
    return None


FONBET_LIST_INLINE = r"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Inforadar — Fonbet Prematch (Football)</title>
  <style>
    :root{
      --bg:#f6f8fc; --card:#fff; --text:#101828; --muted:#667085; --border:#e4e7ec; --brand:#2b6cff;
      --shadow:0 8px 24px rgba(16,24,40,.08); --radius:14px;
      --mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono","Courier New", monospace;
      --good:#12b76a; --bad:#f04438; --warn:#f79009;
    }
    body{margin:0;font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;background:var(--bg);color:var(--text);}
    .topbar{position:sticky;top:0;z-index:10;background:rgba(255,255,255,.85);backdrop-filter:blur(10px);border-bottom:1px solid var(--border);}
    .topbar-inner{max-width:1400px;margin:0 auto;padding:12px 16px;display:flex;align-items:center;justify-content:space-between;gap:12px;}
    .brand{display:flex;align-items:center;gap:10px;font-weight:900;letter-spacing:.2px;}
    .dot{width:12px;height:12px;border-radius:50%;background:var(--brand);box-shadow:0 0 0 6px rgba(43,108,255,.14);}
    .nav{display:flex;gap:10px;align-items:center;font-size:13px;}
    .nav a{color:var(--muted);text-decoration:none;padding:6px 10px;border-radius:999px;border:1px solid transparent}
    .nav a:hover{border-color:var(--border);background:#fff}
    .nav a.active{color:var(--brand);border-color:#d6e4ff;background:#f1f4ff;font-weight:700}
    .wrap{max-width:1400px;margin:0 auto;padding:18px 16px;}
    .card{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);box-shadow:var(--shadow);}
    .card-h{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:14px 16px;border-bottom:1px solid var(--border);}
    .card-h h2{margin:0;font-size:14px;letter-spacing:.3px}
    .controls{display:flex;gap:10px;flex-wrap:wrap;align-items:end}
    label{font-size:12px;color:var(--muted);display:block;margin:0 0 6px}
    input{height:34px;border:1px solid var(--border);border-radius:10px;padding:0 10px;font-size:13px;outline:none;background:#fff}
    input:focus{border-color:#c2d4ff;box-shadow:0 0 0 4px rgba(43,108,255,.12)}
    .btn{height:34px;border-radius:10px;border:1px solid #c2d4ff;background:var(--brand);color:#fff;padding:0 12px;font-weight:700;cursor:pointer}
    .btn.secondary{background:#fff;color:var(--brand)}
    .small{font-size:12px;color:var(--muted)}
    .table-wrap{max-height:72vh;overflow:auto}
    table{width:100%;border-collapse:collapse;font-size:13px}
    th,td{padding:10px 12px;border-bottom:1px solid var(--border);vertical-align:middle}
    th{position:sticky;top:0;background:#fff;z-index:2;text-align:left;font-size:12px;color:var(--muted);font-weight:700}
    tr:hover td{background:#fbfcff}
    a.link{color:var(--brand);text-decoration:none}
    a.link:hover{text-decoration:underline}
    .badge{display:inline-flex;align-items:center;gap:6px;padding:2px 10px;border-radius:999px;font-size:12px;border:1px solid var(--border);background:#fff}
    .badge.bad{border-color:#ffd3d0;background:#fff5f5;color:#b42318}
    .badge.good{border-color:#b7f0cd;background:#ecfdf3;color:#027a48}
    .mono{font-family:var(--mono)}
    .row-drop td{background:linear-gradient(90deg, rgba(240,68,56,.10), rgba(240,68,56,0) 55%);}
    .league{color:var(--muted)}
    .right{display:flex;align-items:center;gap:10px}
    .toggle{display:flex;align-items:center;gap:8px;font-size:12px;color:var(--muted)}
    .toggle input{height:auto}
  </style>
</head>
<body>
  <div class="topbar">
    <div class="topbar-inner">
      <div class="brand"><span class="dot"></span> INFORADAR <span class="badge good">FONBET · prematch · football</span></div>
      <div class="nav">
        <a href="/22bet">22BET</a>
        <a class="active" href="/fonbet">Fonbet</a>
        <a href="/betwatch">Betwatch</a>
      </div>
    </div>
  </div>

  <div class="wrap">
    <div class="card">
      <div class="card-h">
        <div>
          <h2>EVENTS</h2>
          <div class="small">Показываем только футбол (prematch) в ближайшие <span class="mono" id="hoursLabel">12</span> часов. Авто‑обновление подсвечивает события, где <b>хотя бы 1 фактор</b> упал (по сравнению с предыдущим значением).</div>
        </div>
        <div class="right">
          <div class="toggle">
            <input type="checkbox" id="auto" checked />
            <span>Auto refresh</span>
          </div>
          <span class="badge" id="status">—</span>
        </div>
      </div>

      <div class="card-h" style="border-bottom:none;padding-top:10px">
        <div class="controls">
          <div>
            <label>Search</label>
            <input id="q" placeholder="команда / лига" />
          </div>
          <div>
            <label>Hours ahead</label>
            <input id="hours" type="number" min="1" max="72" value="12"/>
          </div>
          <div>
            <label>Sport ID</label>
            <div style="display:flex; gap:8px; align-items:center">
              <input id="sportId" type="number" min="0" placeholder="0 = all" style="width:120px" />
              <select id="sportSel" style="min-width:220px">
                <option value="">(top sport_id…)</option>
              </select>
            </div>
            <div class="small" style="margin-top:6px;color:var(--muted)">
              Выбери sport_id футбола (подсказки в выпадающем списке). Сохранится в браузере.
            </div>
          </div>

          <div>
            <label>Limit</label>
            <input id="limit" type="number" min="50" max="2000" value="200"/>
          </div>
          <div>
            <label>Refresh (sec)</label>
            <input id="refresh" type="number" min="3" max="60" value="10"/>
          </div>
          <button class="btn" id="btn">Show</button>
          <button class="btn secondary" id="btnNow">Now</button>
        </div>
      </div>

      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th style="width:170px">Start</th>
              <th style="width:260px">League</th>
              <th>Match</th>
              <th style="width:120px">Drops</th>
              <th style="width:120px">Max Δ</th>
              <th style="width:120px">ID</th>
            </tr>
          </thead>
          <tbody id="tbody">
            <tr><td colspan="6" class="small">Loading…</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>

<script>
const $ = (id)=>document.getElementById(id);
const ENV_FOOTBALL_SID = Number('__ENV_FOOTBALL_SID__') || 0;
let timer=null;
let sportHintsHours = null;
let autoPickedOnce = false;

async function ensureSportHints(hours){
  if(sportHintsHours === hours) return;
  sportHintsHours = hours;
  const sel = $("sportSel");
  if(!sel) return;
  sel.innerHTML = `<option value="">(top sport_id…)</option>`;
  try{
    const res = await fetch(`/api/fonbet/sport_ids?hours=${encodeURIComponent(String(hours))}&limit=50`, {cache:"no-store"});
    const js = await res.json();
    const items = js.items || [];
    const footballSid = Number(js.football_sport_id || 0) || ENV_FOOTBALL_SID;

    // fill dropdown
    for(const it of items){
      const sid = it.sport_id;
      const cnt = it.count ?? it.cnt ?? 0;
      const sm = (it.sample && it.sample[0]) ? it.sample[0] : null;
      const smTxt = sm ? ` · ${(sm.team1||"").toString()} — ${(sm.team2||"").toString()}` : "";
      const opt = document.createElement("option");
      opt.value = String(sid);
      opt.textContent = `${sid} (${cnt})${smTxt}`;
      sel.appendChild(opt);
    }

    // sync current selection (priority: saved -> input -> ENV default)
    const _sid = (v) => {
      const s = (v ?? '').toString().trim();
      if (s === '' || /[^0-9]/.test(s)) return '';
      return s;
    };
    const saved = _sid(localStorage.getItem('fonbet_sport_id'));
    const inputVal = _sid($("sportId")?.value);
    const current = (saved !== '' ? saved : (inputVal !== '' ? inputVal : (ENV_FOOTBALL_SID ? String(ENV_FOOTBALL_SID) : ''))).toString().trim();
if(current !== ''){
      sel.value = current;
      if($("sportId")) $("sportId").value = current;
    }

    // auto-pick football if nothing chosen yet
    if((!current || Number(current)===0) && footballSid){
      if($('sportId')) $('sportId').value = String(footballSid);
      sel.value = String(footballSid);
      localStorage.setItem('fonbet_sport_id', String(footballSid));
      // re-fetch events once so page immediately becomes "football only"
      if(!autoPickedOnce){
        autoPickedOnce = true;
        setTimeout(()=>{ try{ loadEvents(); }catch(e){} }, 0);
      }
    }
  }catch(e){
    // ignore
  }
}


function fmtTs(s){
  if(!s) return "-";
  // backend returns "YYYY-mm-dd HH:MM:SS"
  return s.replace("T"," ").slice(0,19);
}

function badgeDrops(n){
  if(!n) return `<span class="badge good">0</span>`;
  return `<span class="badge bad">${n}</span>`;
}

function badgeDelta(d){
  if(d === null || d === undefined) return `<span class="badge">—</span>`;
  const v = Number(d);
  if(!isFinite(v)) return `<span class="badge">—</span>`;
  const cls = v < 0 ? "bad" : "good";
  const sign = v < 0 ? "" : "+";
  return `<span class="badge ${cls} mono">${sign}${v.toFixed(3)}</span>`;
}

async function load(){
  const q = $("q").value.trim();
  const hours = Number($("hours").value||12);
  const limit = Number($("limit").value||200);
  $("hoursLabel").textContent = String(hours);

  await ensureSportHints(hours);

  const _sid = (v) => {
    const s = (v ?? '').toString().trim();
    // ignore legacy "0 = all" label or any non-numeric text
    if (s === '' || /[^0-9]/.test(s)) return '';
    return s;
  };

  const savedSport = _sid(localStorage.getItem('fonbet_sport_id'));
  const inputSport = _sid($('sportId')?.value);

  // priority: input -> saved -> ENV default (can be '0' to show all sports)
  const sportRaw = (inputSport !== '' ? inputSport : (savedSport !== '' ? savedSport : (ENV_FOOTBALL_SID ? String(ENV_FOOTBALL_SID) : ''))).toString().trim();
// If nothing selected yet, show ENV default in the input (but still allow user to choose 0=all)
  if($('sportId') && inputSport === '' && savedSport === '' && ENV_FOOTBALL_SID){
    $('sportId').value = String(ENV_FOOTBALL_SID);
  }
  // persist selection (including '0')
  if($('sportId')) localStorage.setItem('fonbet_sport_id', sportRaw);
  let url = `/api/fonbet/events?hours=${encodeURIComponent(hours)}&limit=${encodeURIComponent(limit)}&q=${encodeURIComponent(q)}`;
  if (sportRaw !== '') url += `&sport_id=${encodeURIComponent(String(sportRaw))}`;
  if ($('sportId')) localStorage.setItem('fonbet_sport_id', sportId ? String(sportId) : '');
  const t0 = performance.now();
  try{
    $("status").textContent = "loading…";
    const res = await fetch(url, {cache:"no-store"});
    const js = await res.json();
    const ms = Math.round(performance.now()-t0);
    $("status").textContent = `events: ${js.events.length} · ${ms}ms`;

    const rows = js.events.map(e=>{
      const cls = (e.drops && e.drops>0) ? "row-drop" : "";
      const match = `${e.team1||"?"} — ${e.team2||"?"}`;
      const link = `<a class="link" href="/fonbet_event/${e.event_id}">${match}</a>`;
      const league = `<span class="league">${e.league_name||"-"}</span>`;
      return `<tr class="${cls}">
        <td class="mono">${fmtTs(e.start_time)}</td>
        <td>${league}</td>
        <td>${link}</td>
        <td>${badgeDrops(e.drops)}</td>
        <td>${badgeDelta(e.max_drop)}</td>
        <td class="mono">${e.event_id}</td>
      </tr>`;
    }).join("");

    $("tbody").innerHTML = rows || `<tr><td colspan="6" class="small">No events</td></tr>`;
  }catch(err){
    $("status").textContent = "error";
    $("tbody").innerHTML = `<tr><td colspan="6"><pre class="small">${String(err)}</pre></td></tr>`;
  }
}

function stopTimer(){
  if(timer){ clearInterval(timer); timer=null; }
}
function startTimer(){
  stopTimer();
  const sec = Math.max(3, Math.min(60, Number($("refresh").value||10)));
  timer=setInterval(()=>{ if($("auto").checked) load(); }, sec*1000);
}

if($("sportSel")){
  $("sportSel").addEventListener("change", ()=>{
    const v = $("sportSel").value;
    if($("sportId")) $("sportId").value = v;
    if(v) localStorage.setItem('fonbet_sport_id', v); else localStorage.removeItem('fonbet_sport_id');
    load();
  });
}
if($("sportId")){
  $("sportId").addEventListener("change", ()=>{
    const v = $("sportId").value.trim();
    if(v) localStorage.setItem('fonbet_sport_id', v); else localStorage.removeItem('fonbet_sport_id');
    if($("sportSel")) $("sportSel").value = v;
    load();
  });
}
$("hours").addEventListener("change", ()=>{
  sportHintsHours = null;
  load();
});

$("btn").addEventListener("click", ()=>{ load(); startTimer(); });
$("btnNow").addEventListener("click", ()=>{
  $("q").value=""; $("hours").value=12; $("limit").value=200; $("refresh").value=10; if($("sportId")) $("sportId").value=""; if($("sportSel")) $("sportSel").value=""; localStorage.removeItem("fonbet_sport_id"); sportHintsHours=null;
  load(); startTimer();
});
$("auto").addEventListener("change", ()=>{ if($("auto").checked) load(); });

load(); startTimer();
</script>
</body>
</html>
"""


FONBET_EVENT_INLINE = r"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Inforadar — Fonbet Event {{ event.event_id }}</title>
  <style>
    :root{
      --bg:#f6f8fc; --card:#fff; --text:#101828; --muted:#667085; --border:#e4e7ec; --brand:#2b6cff;
      --shadow:0 8px 24px rgba(16,24,40,.08); --radius:14px;
      --mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono","Courier New", monospace;
      --good:#12b76a; --bad:#f04438; --warn:#f79009;
    }
    body{margin:0;font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;background:var(--bg);color:var(--text);}
    .topbar{position:sticky;top:0;z-index:10;background:rgba(255,255,255,.72);backdrop-filter:blur(10px);border-bottom:1px solid var(--border);}
    .topbar-inner{max-width:1300px;margin:0 auto;padding:10px 16px;display:flex;align-items:center;justify-content:space-between;gap:12px;}
    .brand{display:flex;align-items:center;gap:10px;font-weight:900;letter-spacing:.2px}
    .dot{width:10px;height:10px;border-radius:50%;background:var(--brand);box-shadow:0 0 0 4px rgba(43,108,255,.15)}
    .nav{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
    .nav a{color:var(--muted);text-decoration:none;padding:6px 10px;border-radius:999px;border:1px solid transparent;font-weight:800;font-size:13px;}
    .nav a:hover{border-color:var(--border);background:#fff}
    .nav a.active{color:var(--brand);border-color:#d6e4ff;background:#f1f4ff;}
    .wrap{max-width:1300px;margin:0 auto;padding:18px 16px;}
    .card{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);box-shadow:var(--shadow);margin-bottom:14px;}
    .card-h{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;padding:14px 16px;border-bottom:1px solid var(--border);}
    h1{margin:0;font-size:18px}
    .meta{font-size:12px;color:var(--muted);margin-top:2px}
    .controls{display:flex;gap:10px;flex-wrap:wrap;align-items:end}
    label{font-size:12px;color:var(--muted);display:block;margin:0 0 6px}
    input{height:34px;border:1px solid var(--border);border-radius:10px;padding:0 10px;font-size:13px;outline:none;background:#fff}
    .btn{height:34px;border-radius:10px;border:1px solid #c2d4ff;background:var(--brand);color:#fff;padding:0 12px;font-weight:800;cursor:pointer}
    .btn.secondary{background:#fff;color:var(--brand)}
    .btn:disabled{opacity:.6;cursor:not-allowed}
    .seg{display:flex;gap:6px;align-items:center}
    .seg .pill{height:34px;display:inline-flex;align-items:center;justify-content:center;padding:0 12px;border-radius:999px;border:1px solid var(--border);background:#fff;color:var(--muted);font-weight:900;cursor:pointer}
    .seg .pill.active{border-color:#d6e4ff;background:#f1f4ff;color:var(--brand)}
    .grid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;padding:14px 16px;}
    @media(max-width:1100px){.grid{grid-template-columns:1fr}}
    .box{border:1px solid var(--border);border-radius:12px;overflow:hidden;background:#fff}
    .box-h{display:flex;align-items:center;justify-content:space-between;padding:10px 12px;border-bottom:1px solid var(--border);font-weight:900}
    .small{font-size:12px;color:var(--muted)}
    .table-wrap{overflow:auto;max-height:520px}
    table{width:100%;border-collapse:collapse}
    th,td{border-bottom:1px solid #eef2f6;padding:8px 10px;text-align:center;font-size:13px;white-space:nowrap}
    th{position:sticky;top:0;background:#f9fafb;z-index:1}
    td.mono{font-family:var(--mono);font-variant-numeric:tabular-nums}
    .bad{color:var(--bad);font-weight:900}
    .good{color:var(--good);font-weight:900}
  </style>
</head>
<body>
  <div class="topbar">
    <div class="topbar-inner">
      <div class="brand"><span class="dot"></span>INFORADAR <span style="font-size:12px;font-weight:900;color:#12b76a;border:1px solid #b7ebc6;background:#ecfdf3;border-radius:999px;padding:2px 8px;">FONBET • prematch • football</span></div>
      <div class="nav">
        <a href="/prematch">22BET</a>
        <a href="/fonbet" class="active">Fonbet</a>
        <a href="/betwatch">Betwatch</a>
      </div>
    </div>
  </div>

  <div class="wrap">
    <div class="card">
      <div class="card-h">
        <div>
          <h1 id="title">{{ event.team1 }} — {{ event.team2 }}</h1>
          <div class="meta">
            <b>start:</b> {{ event.start_time }}{% if event.league_name %} • <b>{{ event.league_name }}</b>{% endif %}
          </div>
        </div>

        <div class="controls">
          <div class="seg" title="FT / 1st half (как Inforadar)">
            <div id="pill-ft" class="pill active">FT</div>
            <div id="pill-ht" class="pill">HT</div>
          </div>
          <div>
            <label>History hours</label>
            <input id="hours" type="number" value="12" min="1" max="72" style="width:92px"/>
          </div>
          <div>
            <label>Hist limit</label>
            <input id="limit" type="number" value="8000" min="200" max="50000" style="width:110px"/>
          </div>
          <button id="btn" class="btn">Обновить</button>
          <label style="display:flex;gap:8px;align-items:center;margin:0 0 2px">
            <input id="auto" type="checkbox"/> <span class="small">авто</span>
          </label>
        </div>
      </div>

      <div style="padding:10px 16px" class="small" id="meta">event_id: {{ event.event_id }}{% if event.sport_id %} • sport: {{ event.sport_id }}{% endif %} • Alg.1/Alg.2 = изменение коэффициента относительно первой строки истории (как в Inforadar).</div>

      <div class="grid">
        <div class="box">
          <div class="box-h">1X2 <span class="small" id="m1"></span></div>
          <div class="table-wrap">
            <table>
              <thead><tr><th class="mono">Time</th><th>1</th><th>X</th><th>2</th></tr></thead>
              <tbody id="t1"><tr><td colspan="4" class="small">Loading…</td></tr></tbody>
            </table>
          </div>
        </div>

        <div class="box">
          <div class="box-h">Handicap (mainline) <span class="small" id="m2"></span></div>
          <div class="table-wrap">
            <table>
              <thead><tr><th class="mono">Time</th><th>Home</th><th>Hcp</th><th>Away</th><th>Alg.1</th><th>Alg.2</th></tr></thead>
              <tbody id="tH"><tr><td colspan="6" class="small">Loading…</td></tr></tbody>
            </table>
          </div>
        </div>

        <div class="box">
          <div class="box-h">Total (mainline) <span class="small" id="m3"></span></div>
          <div class="table-wrap">
            <table>
              <thead><tr><th class="mono">Time</th><th>Over</th><th>Total</th><th>Under</th><th>Alg.1</th><th>Alg.2</th></tr></thead>
              <tbody id="tT"><tr><td colspan="6" class="small">Loading…</td></tr></tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  </div>

<script>
const $ = (id)=>document.getElementById(id);

let currentHalf = "ft";
let timer = null;

function fmtNum(v){
  if(v===null || v===undefined) return "";
  const n = (typeof v === "number") ? v : Number(v);
  if(!Number.isFinite(n)) return String(v);
  let s = n.toFixed(3);
  // trim trailing zeros like 2.500 -> 2.5, -1.000 -> -1
  s = s.replace(/\.0+$/,"").replace(/(\.\d*[1-9])0+$/,"$1");
  return s;
}


function heatStyle(v){
  const x = Number(v);
  if(!isFinite(x)) return "";
  const a = Math.abs(x);
  if(a < 0.01) return "";
  const alpha = Math.min(0.65, a * 0.65); // |1.00| => 0.65
  return `style="background: rgba(220, 53, 69, ${alpha});"`;
}

function chgStyle(cur, prev){
  const c = Number(cur);
  const p = Number(prev);
  if(!isFinite(c) || !isFinite(p) || p === 0) return "";
  const d = c - p;
  if(Math.abs(d) < 1e-9) return "";
  const pct = Math.abs(d) / Math.abs(p);
  const alpha = Math.min(0.55, pct * 4.0);
  const bg = d < 0 ? `rgba(220, 53, 69, ${alpha})` : `rgba(25, 135, 84, ${alpha})`;
  return `style="background: ${bg};"`;
}

function pill(half){
  currentHalf = half;
  $("pill-ft").classList.toggle("active", half==="ft");
  $("pill-ht").classList.toggle("active", half==="1h");
  load();
}

$("pill-ft").addEventListener("click", ()=>pill("ft"));
$("pill-ht").addEventListener("click", ()=>pill("1h"));

function render1x2(rows){
  const tb=$("t1");
  if(!rows || !rows.length){
    tb.innerHTML = `<tr><td colspan="4" class="small">No data</td></tr>`;
    return;
  }
  tb.innerHTML = rows.map((r,i)=>{
    const prev = i>0 ? rows[i-1] : null;
    const s1 = prev ? chgStyle(r["1"], prev["1"]) : "";
    const sx = prev ? chgStyle(r["X"], prev["X"]) : "";
    const s2 = prev ? chgStyle(r["2"], prev["2"]) : "";
    return `<tr>
      <td class="mono">${String(r.Time||"")}</td>
      <td class="mono" ${s1}>${fmtNum(r["1"])}</td>
      <td class="mono" ${sx}>${fmtNum(r["X"])}</td>
      <td class="mono" ${s2}>${fmtNum(r["2"])}</td>
    </tr>`;
  }).join("");
}

function renderHandicap(rows){
  const tb=$("tH");
  if(!rows || !rows.length){
    tb.innerHTML = `<tr><td colspan="6" class="small">No data</td></tr>`;
    return;
  }
  tb.innerHTML = rows.map((r,i)=>{
    const prev = i>0 ? rows[i-1] : null;
    const sHome = prev ? chgStyle(r.Home, prev.Home) : "";
    const sAway = prev ? chgStyle(r.Away, prev.Away) : "";
    const sA1 = heatStyle(r.Alg1);
    const sA2 = heatStyle(r.Alg2);
    return `<tr>
      <td class="mono">${String(r.Time||"")}</td>
      <td class="mono" ${sHome}>${fmtNum(r.Home)}</td>
      <td class="mono">${fmtNum(r.Hcp)}</td>
      <td class="mono" ${sAway}>${fmtNum(r.Away)}</td>
      <td class="mono" ${sA1}>${fmtNum(r.Alg1)}</td>
      <td class="mono" ${sA2}>${fmtNum(r.Alg2)}</td>
    </tr>`;
  }).join("");
}

function renderTotal(rows){
  const tb=$("tT");
  if(!rows || !rows.length){
    tb.innerHTML = `<tr><td colspan="6" class="small">No data</td></tr>`;
    return;
  }
  tb.innerHTML = rows.map((r,i)=>{
    const prev = i>0 ? rows[i-1] : null;
    const sOver = prev ? chgStyle(r.Over, prev.Over) : "";
    const sUnder = prev ? chgStyle(r.Under, prev.Under) : "";
    const sA1 = heatStyle(r.Alg1);
    const sA2 = heatStyle(r.Alg2);
    return `<tr>
      <td class="mono">${String(r.Time||"")}</td>
      <td class="mono" ${sOver}>${fmtNum(r.Over)}</td>
      <td class="mono">${fmtNum(r.Total)}</td>
      <td class="mono" ${sUnder}>${fmtNum(r.Under)}</td>
      <td class="mono" ${sA1}>${fmtNum(r.Alg1)}</td>
      <td class="mono" ${sA2}>${fmtNum(r.Alg2)}</td>
    </tr>`;
  }).join("");
}

async function load(){
  const hours = $("hours").value || "12";
  const limit = $("limit").value || "8000";
    const url = `/api/fonbet/event/{{ event.event_id }}/tables?hours=${encodeURIComponent(hours)}&limit=${encodeURIComponent(limit)}&half=${encodeURIComponent(currentHalf)}`;
  $("m1").textContent="loading…"; $("m2").textContent=""; $("m3").textContent="";
  try{
    const t0=performance.now();
    const r = await fetch(url);
    const js = await r.json();
    const ms = Math.round(performance.now()-t0);

    if(js.error){
      $("meta").textContent = "ERROR: " + js.error;
    } else if(js.meta){
    $("meta").textContent = `event_id: {{ event.event_id }} • half=${currentHalf} • snapshots=${js.meta?.snapshots ?? 0} • raw_rows=${js.meta?.raw_rows ?? 0} • ${ms}ms`;
    }

    $("m1").textContent = js.meta ? (`snapshots: ${js.meta.snapshots}`) : "";
    $("m2").textContent = js.meta ? (`main: ${js.meta.main_handicap ?? ""}`) : "";
    $("m3").textContent = js.meta ? (`main: ${js.meta.main_total ?? ""}`) : "";

    render1x2(js.outcomes || []);
    renderHandicap(js.handicap || []);
    renderTotal(js.total || []);

  }catch(e){
    console.error(e);
    $("meta").textContent = "Failed (see console)";
  }
}

$("btn").addEventListener("click", load);

$("auto").addEventListener("change", (e)=>{
  if(timer){ clearInterval(timer); timer=null; }
  if(e.target.checked){
    timer = setInterval(load, 8000);
  }
});

load();
</script>
</body>
</html>
"""




_FONBET_TS_MODE_CACHE: Dict[str, Optional[str]] = {"col": None, "mode": None}  # mode: datetime | int_s | int_ms

def _fonbet_ts_mode(cur, ts_col: str) -> str:
    """Detect whether fonbet_odds_history.<ts_col> is DATETIME-like or integer unix time (s/ms)."""
    global _FONBET_TS_MODE_CACHE
    if _FONBET_TS_MODE_CACHE.get("col") == ts_col and _FONBET_TS_MODE_CACHE.get("mode"):
        return str(_FONBET_TS_MODE_CACHE["mode"])

    mode = "datetime"
    try:
        cur.execute("SHOW COLUMNS FROM fonbet_odds_history")
        cols = cur.fetchall() or []
        col_type = ""
        for r in cols:
            if isinstance(r, dict) and r.get("Field") == ts_col:
                col_type = (r.get("Type") or "").lower()
                break

        is_numeric = any(x in col_type for x in ("int", "bigint", "decimal", "double", "float"))
        if is_numeric:
            try:
                cur.execute(f"SELECT {ts_col} AS v FROM fonbet_odds_history ORDER BY {ts_col} DESC LIMIT 1")
                v = (cur.fetchone() or {}).get("v")
                v_int = int(v) if v is not None else 0
                mode = "int_ms" if v_int > 10**11 else "int_s"
            except Exception:
                mode = "int_s"
        else:
            mode = "datetime"
    except Exception:
        mode = "datetime"

    _FONBET_TS_MODE_CACHE = {"col": ts_col, "mode": mode}
    return mode


def _fonbet_ts_where(cur, ts_col: str, hours: int) -> tuple:
    """Return (sql_condition_with_one_%s_placeholder, [param])."""
    hours = int(hours)
    mode = _fonbet_ts_mode(cur, ts_col)

    if mode == "datetime":
        return f"{ts_col} >= NOW() - INTERVAL %s HOUR", [hours]

    secs = max(1, hours) * 3600
    if mode == "int_ms":
        return f"{ts_col} >= (UNIX_TIMESTAMP(NOW()) - %s) * 1000", [secs]
    return f"{ts_col} >= UNIX_TIMESTAMP(NOW()) - %s", [secs]


def _fonbet_ts_select_expr(cur, ts_col: str) -> str:
    """Expression that yields a DATETIME-ish value for JSON/UI, regardless of ts storage."""
    mode = _fonbet_ts_mode(cur, ts_col)
    if mode == "int_ms":
        return f"FROM_UNIXTIME(FLOOR({ts_col}/1000))"
    if mode == "int_s":
        return f"FROM_UNIXTIME({ts_col})"
    return ts_col

@app.route("/prematch_simple")
def page_prematch_simple():
    return render_template_string(PREMATCH_PAGE_INLINE, title=APP_TITLE)

@app.route("/prematch")
def page_prematch():
    if _force_inline():
        return render_template_string(PREMATCH_SIMPLE_INLINE, title=APP_TITLE)

    # If you have your own templates (beautiful UI), they will be used:
    for tpl in ("prematch_22bet.html", "prematchodds.html", "prematch.html"):
        try:
            return render_template(tpl)
        except Exception:
            continue

    return render_template_string(PREMATCH_PAGE_INLINE, title=APP_TITLE)

@app.route("/22bet")
def page_22bet_alias():
    # Backward compatible URL (many people use /22bet from the menu)
    return redirect(url_for("page_prematch"))

@app.route("/prematch_event/<event_id>")
def page_prematch_event(event_id: str):
    # Handle literal placeholder URL /prematch_event/<event_id>
    if event_id.strip() in ("<event_id>", "%3Cevent_id%3E"):
        # show hint + a working example
        example = None
        try:
            with db_connect() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT event_id FROM odds_22bet WHERE bookmaker='22bet' AND sport='Football' AND event_id IS NOT NULL LIMIT 1")
                    row = cur.fetchone() or {}
                    example = row.get("event_id")
        except Exception:
            pass

        msg = f"""
        <h2>Нужно подставить реальный event_id</h2>
        <p>Твой URL содержит плейсхолдер <code>&lt;event_id&gt;</code>.</p>
        <p>Открой так: <code>/prematch_event/680582276</code> (пример).</p>
        """
        if example:
            msg += f'<p>Вот готовая ссылка из БД: <a href="/prematch_event/{example}">/prematch_event/{example}</a></p>'
        msg += '<p><a href="/prematch_simple">← назад</a></p>'
        return msg, 200

    # Validate numeric
    if not event_id.isdigit():
        return "Bad event_id (must be digits).", 400

    eid = int(event_id)

    if _force_inline():
        return render_template_string(EVENT_SIMPLE_INLINE, title=f"Event {eid}", event_id=eid)

    for tpl in ("prematch_event_22bet.html", "prematch_event.html"):
        try:
            return render_template(tpl, event_id=eid)
        except Exception:
            continue

    return render_template_string(EVENT_PAGE_INLINE, title=f"Event {eid}", event_id=eid)
# ------------------------------
# FONBET helpers + API
# ------------------------------

_FONBET_CATALOG_CACHE = {"ts": 0.0, "data": None, "map": None}
_FONBET_CATALOG_TTL_SEC = 3600  # 1h

_FONBET_TS_COL_CACHE = ""  # detected timestamp column in fonbet_odds_history
_FONBET_LABEL_COL_CACHE = None  # detected label column in fonbet_odds_history
_FONBET_PARAM_COL_CACHE = None  # detected param/line column in fonbet_odds_history



def _fonbet_proxy_url() -> Optional[str]:
    """Build proxy URL from env (server + optional user/pass)."""
    server = _env("FONBET_PROXY_SERVER", default="") or ""
    if not server:
        return None
    user = _env("FONBET_PROXY_USERNAME", default="") or ""
    pwd = _env("FONBET_PROXY_PASSWORD", default="") or ""
    if user and pwd and "@" not in server:
        # keep scheme from server
        # server like http://host:port
        try:
            scheme, rest = server.split("://", 1)
            return f"{scheme}://{user}:{pwd}@{rest}"
        except Exception:
            return server
    return server


def _http_get_json(url: str, timeout: float = 15.0) -> Optional[dict]:
    """Small stdlib HTTP JSON helper (supports proxy)."""
    proxy = _fonbet_proxy_url()
    handlers = []
    if proxy:
        handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    opener = urllib.request.build_opener(*handlers)
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (InforadarBot)",
            "Accept": "application/json,text/plain,*/*",
        },
        method="GET",
    )
    try:
        with opener.open(req, timeout=timeout) as resp:
            data = resp.read()
        return json.loads(data.decode("utf-8", errors="replace"))
    except Exception:
        return None


def _fonbet_line_bases() -> List[str]:
    # prefer env, then fallbacks
    env_base = _env("FONBET_LINE_BASE", default="") or ""
    bases = []
    if env_base:
        bases.append(env_base.rstrip("/"))
    bases += [
        "https://line01.cy8cff-resources.com",
        "https://line02.cy8cff-resources.com",
    ]
    # de-dup
    out = []
    for b in bases:
        if b and b not in out:
            out.append(b)
    return out


def _fonbet_classify_market(label: str) -> str:
    """
    Rough market classifier by label/context. Returns:
      outcomes | outcomes_1h
      handicap | handicap_1h
      total | total_1h
      other
    """
    t2 = re.sub(r"\s+", " ", (label or "").strip().lower())

    # half / 1st half markers
    is_1h = any(k in t2 for k in ("1-й тайм", "1 тайм", "1st half", "1h", "первый тайм", "1 half"))

    # totals
    if ("тотал" in t2) or ("total" in t2) or ("тб" in t2) or ("тм" in t2) or ("over" in t2) or ("under" in t2) or re.search(r"(^|\s)[бм]\s*\(\s*\d", t2):
        return "total_1h" if is_1h else "total"

    # handicap / spread
    # IMPORTANT: require a numeric inside parentheses to avoid misclassifying outcomes like "1 (something)"
    if ("фора" in t2) or ("handicap" in t2) or re.search(r"(^|[^0-9])[12]\s*\(\s*[-+]?\d", t2) or re.search(r"\(\s*[-+]?\d+(?:\.\d+)?\s*\)", t2):
        return "handicap_1h" if is_1h else "handicap"

    # outcomes / 1X2 / double chance
    if ("исход" in t2) or ("1x2" in t2) or ("match result" in t2) or ("п1" in t2) or ("п2" in t2) or ("нич" in t2) or ("draw" in t2) or re.search(r"\b(x|х|н)\b", t2) or re.fullmatch(r"(1|2|x|х|1x|x2|12)", t2.replace(" ", "")):
        return "outcomes_1h" if is_1h else "outcomes"

    return "other"

def _fonbet_extract_factor_map(obj, *, only_event_id: Optional[int] = None, base_event_id: Optional[int] = None, half: str = "ft") -> Dict[int, dict]:
    """
    Build factorId -> {label, market, param} map from various Fonbet JSON payloads.

    Special handling for *eventView* structure:
      { events: [ { subcategories: [ { name: str, quotes: [ { factorId, name, p?, value/quote } ] } ] } ] }

    NOTE: In eventView, field `value` is the *odd* (not the line param). Line param lives in `p`.
    """
    out: Dict[int, dict] = {}

    # --- eventView fast-path ---
    try:
        if isinstance(obj, dict) and isinstance(obj.get("events"), list):
            events = obj.get("events") or []
            sel_events: List[dict] = []

            # Prefer a specific event node (prevents factorId/param overwrites between FT and 1H)
            if only_event_id:
                try:
                    oe = int(only_event_id)
                except Exception:
                    oe = 0
                if oe:
                    for e in events:
                        if isinstance(e, dict) and safe_int(e.get("id"), 0) == oe:
                            sel_events.append(e)

            if not sel_events and str(half or "ft").lower() == "1h":
                # Pick the 1H child by kind/name (+ optional parentId linkage to base_event_id)
                be = int(base_event_id) if base_event_id else 0
                for e in events:
                    if not isinstance(e, dict):
                        continue
                    is_1h = (safe_int(e.get("kind"), 0) == 100201) or _fonbet_ev_name_is_1h(str(e.get("name") or ""))
                    if not is_1h:
                        continue
                    if be and safe_int(e.get("parentId"), 0) not in (0, be) and safe_int(e.get("id"), 0) != be:
                        continue
                    sel_events.append(e)

            if not sel_events and str(half or "ft").lower() == "ft":
                # Prefer base event, otherwise exclude 1H-like nodes
                be = int(base_event_id) if base_event_id else 0
                if be:
                    for e in events:
                        if isinstance(e, dict) and safe_int(e.get("id"), 0) == be:
                            sel_events.append(e)
                if not sel_events:
                    for e in events:
                        if not isinstance(e, dict):
                            continue
                        if (safe_int(e.get("kind"), 0) == 100201) or _fonbet_ev_name_is_1h(str(e.get("name") or "")):
                            continue
                        sel_events.append(e)

            if not sel_events:
                sel_events = [e for e in events if isinstance(e, dict)]

            for ev in sel_events:
                for sc in (ev.get("subcategories") or []):
                    sc_name = str(sc.get("name") or "").strip()
                    sc_l = sc_name.lower()

                    if any(k in sc_l for k in ("исход", "1x2", "результат", "match result")):
                        base_market = "outcomes"
                    elif any(k in sc_l for k in ("фор", "handicap")):
                        base_market = "handicap"
                    elif any(k in sc_l for k in ("тотал", "total")):
                        base_market = "total"
                    else:
                        base_market = ""

                    for q in (sc.get("quotes") or []):
                        if not isinstance(q, dict):
                            continue
                        fid = q.get("factorId")
                        if fid is None:
                            continue
                        try:
                            fid_i = int(fid)
                        except Exception:
                            continue

                        label = str((q.get("name") or q.get("title") or q.get("label") or "")).strip()

                        # line param (handicap/total) lives in `p` for eventView
                        param = q.get("p") if "p" in q else q.get("param")

                        if param in ("", None):
                            param_n = None
                        else:
                            try:
                                param_n = float(param)
                            except Exception:
                                param_n = param

                        market = base_market or _fonbet_classify_market(f"{label} {sc_name}")
                        if market.startswith("outcomes"):
                            param_n = None

                        out[fid_i] = {"label": label, "market": market, "param": param_n}

            if out:
                return out
    except Exception:
        out = {}

    # --- generic recursive extractor (safe) ---
    def _walk(node, ctx: str = ""):
        if isinstance(node, dict):
            fid = node.get("factorId") or node.get("factor_id") or node.get("factor") or node.get("id")
            label = None
            for k in ("name", "title", "label", "text", "n"):
                if k in node and node.get(k) not in (None, ""):
                    label = str(node.get(k))
                    break

            # IMPORTANT: do NOT treat `value` as param here (in many payloads it's an odd)
            param = None
            for k in ("p", "param", "line", "handicap", "total"):
                if k in node and node.get(k) not in (None, ""):
                    param = node.get(k)
                    break

            if fid is not None:
                try:
                    fid_i = int(fid)
                except Exception:
                    fid_i = None
                if fid_i:
                    lbl = (label or "").strip()
                    market = _fonbet_classify_market(f"{lbl} {ctx}")
                    param_n = None
                    if param not in (None, "") and not market.startswith("outcomes"):
                        try:
                            param_n = float(param)
                        except Exception:
                            param_n = param
                    out[fid_i] = {"label": lbl, "market": market, "param": param_n}

            new_ctx = (ctx + " " + (label or "")).strip()
            for v in node.values():
                _walk(v, new_ctx)

        elif isinstance(node, list):
            for it in node:
                _walk(it, ctx)

    _walk(obj, "")
    return out

_FONBET_CATALOG_CACHE_MAP: dict = {}  # key=(sys_id, lang) -> {"ts": float, "ttl": int, "map": dict, "data": Any}

def _fonbet_try_get_version(obj: Any) -> Optional[str]:
    """Try to extract listBase version from JSON."""
    if isinstance(obj, dict):
        for k in ("version", "ver", "v", "listBaseVersion", "list_base_version"):
            v = obj.get(k)
            if isinstance(v, (int, float)) and v:
                return str(int(v))
            if isinstance(v, str) and v.strip().isdigit():
                return v.strip()
        # sometimes nested
        for v in obj.values():
            vv = _fonbet_try_get_version(v)
            if vv:
                return vv
    elif isinstance(obj, list):
        for it in obj:
            vv = _fonbet_try_get_version(it)
            if vv:
                return vv
    return None

def _fonbet_fetch_listbase(lang: str, sys_id: int) -> Any:
    scope = _env("FONBET_SCOPEMARKET", default="") or _env("FONBET_SCOPE_MARKET", default="") or ""
    scope_q = f"&scopeMarket={scope}" if scope.strip().isdigit() else ""
    for base in _fonbet_line_bases():
        url = f"{base}/line/listBase?lang={lang}&sysId={sys_id}{scope_q}"
        data = _http_get_json(url, timeout=20.0)
        if isinstance(data, (dict, list)):
            return data
    return None


def _fonbet_extract_factor_values(obj: Any, *, only_event_id: Optional[int] = None, base_event_id: Optional[int] = None, half: str = "ft") -> Dict[int, float]:
    """
    Try to extract current coefficient values from eventView JSON.
    Returns factorId -> odd (float).
    """
    out: Dict[int, float] = {}

    def norm_odd(v: Any) -> Optional[float]:
        if v is None or isinstance(v, bool):
            return None
        if isinstance(v, (int, float)):
            x = float(v)
        elif isinstance(v, str):
            s = v.strip().replace(",", ".")
            try:
                x = float(s)
            except Exception:
                return None
        else:
            return None

        if 1.01 <= x < 1000:
            return x
        if x >= 101 and x <= 100000 and abs(x - round(x)) < 1e-9:
            for div in (100.0, 1000.0):
                y = x / div
                if 1.01 <= y < 1000:
                    return y
        return None
    # --- eventView fast-path ---
    # Avoid mixing multiple internal events (FT vs 1H) that may reuse the same factorId with different params.
    # Also do NOT treat `p` as an odd here (in eventView `p` is the line param).
    try:
        if isinstance(obj, dict) and isinstance(obj.get("events"), list):
            events = obj.get("events") or []
            sel_events: List[dict] = []

            if only_event_id:
                try:
                    oe = int(only_event_id)
                except Exception:
                    oe = 0
                if oe:
                    for e in events:
                        if isinstance(e, dict) and safe_int(e.get("id"), 0) == oe:
                            sel_events.append(e)

            if not sel_events and str(half or "ft").lower() == "1h":
                be = int(base_event_id) if base_event_id else 0
                for e in events:
                    if not isinstance(e, dict):
                        continue
                    is_1h = (safe_int(e.get("kind"), 0) == 100201) or _fonbet_ev_name_is_1h(str(e.get("name") or ""))
                    if not is_1h:
                        continue
                    if be and safe_int(e.get("parentId"), 0) not in (0, be) and safe_int(e.get("id"), 0) != be:
                        continue
                    sel_events.append(e)

            if not sel_events and str(half or "ft").lower() == "ft":
                be = int(base_event_id) if base_event_id else 0
                if be:
                    for e in events:
                        if isinstance(e, dict) and safe_int(e.get("id"), 0) == be:
                            sel_events.append(e)
                if not sel_events:
                    for e in events:
                        if not isinstance(e, dict):
                            continue
                        if (safe_int(e.get("kind"), 0) == 100201) or _fonbet_ev_name_is_1h(str(e.get("name") or "")):
                            continue
                        sel_events.append(e)

            if not sel_events:
                sel_events = [e for e in events if isinstance(e, dict)]

            for ev in sel_events:
                for sc in (ev.get("subcategories") or []):
                    for q in (sc.get("quotes") or []):
                        if not isinstance(q, dict):
                            continue
                        fid = q.get("factorId")
                        if fid is None:
                            continue
                        try:
                            fid_i = int(fid)
                        except Exception:
                            continue
                        for k in ("v", "value", "odd", "odds", "coef", "c", "k", "price"):
                            ov = norm_odd(q.get(k))
                            if ov is not None:
                                out[fid_i] = ov
                                break
            if out:
                return out
    except Exception:
        pass


    def walk(x: Any):
        if isinstance(x, dict):
            fid = x.get("factorId")
            if isinstance(fid, int):
                for k in ("v", "value", "odd", "odds", "coef", "c", "k", "p", "price"):
                    if k in x:
                        ov = norm_odd(x.get(k))
                        if ov is not None:
                            out[fid] = ov
                            break
            for vv in x.values():
                walk(vv)
        elif isinstance(x, list):
            for it in x:
                walk(it)

    walk(obj)
    return out


def _fonbet_fetch_event_view_tables(lang: str, sys_id: int, version: str) -> Any:
    scope = _env("FONBET_SCOPEMARKET", default="") or _env("FONBET_SCOPE_MARKET", default="") or ""
    scope_q = f"&scopeMarket={scope}" if scope.strip().isdigit() else ""
    for base in _fonbet_line_bases():
        url = f"{base}/line/factorsCatalog/eventViewTables?version={version}&lang={lang}&sysId={sys_id}{scope_q}"
        data = _http_get_json(url, timeout=20.0)
        if isinstance(data, (dict, list)):
            return data
    return None

def _fonbet_fetch_event_view(lang: str, sys_id: int, event_id: int) -> Any:
    """
    Fetch eventView JSON for a specific event (often contains factorId + label/shortTitle).
    This is a strong fallback when global factorsCatalog is missing/mismatched.
    """
    scope = _env("FONBET_SCOPEMARKET", default="") or _env("FONBET_SCOPE_MARKET", default="") or ""
    scope_q = f"&scopeMarket={scope}" if scope.strip().isdigit() else ""
    for base in _fonbet_line_bases():
        url = f"{base}/line/eventView?eventId={event_id}&lang={lang}&sysId={sys_id}{scope_q}"
        data = _http_get_json(url, timeout=20.0)
        if isinstance(data, (dict, list)):
            return data
    return None

def fonbet_factor_catalog_map(force: bool = False) -> Dict[int, Dict[str, str]]:
    """
    Cache factorId -> {label, market} mapping.

    Why it's critical:
    - fonbet_odds_history stores only factor_id, so UI needs a factor catalog to decode it.
    - sometimes the catalog endpoint returns empty; we must not "stick" to empty forever.

    Strategy:
    1) try eventViewTables with version=0 (fast)
    2) if empty -> fetch listBase, extract version, retry eventViewTables with that version
    3) if still empty -> try extracting from listBase itself
    """
    sys_id = int(_env("FONBET_SYS_ID", default="21") or "21")
    lang = _env("FONBET_LANG", default="ru") or "ru"
    key = (sys_id, lang)

    now = time.time()
    entry = _FONBET_CATALOG_CACHE_MAP.get(key) or {}
    ttl = int(entry.get("ttl") or _FONBET_CATALOG_TTL_SEC)

    if (not force) and entry.get("map") and (now - float(entry.get("ts") or 0) < ttl):
        return entry.get("map") or {}

    data = _fonbet_fetch_event_view_tables(lang, sys_id, version="0")
    fmap: Dict[int, Dict[str, str]] = {}
    if isinstance(data, (dict, list)):
        fmap = _fonbet_extract_factor_map(data) or {}

    listbase = None
    if not fmap:
        listbase = _fonbet_fetch_listbase(lang, sys_id)
        ver = _fonbet_try_get_version(listbase)
        if ver:
            data2 = _fonbet_fetch_event_view_tables(lang, sys_id, version=ver)
            if isinstance(data2, (dict, list)):
                fmap = _fonbet_extract_factor_map(data2) or {}
                data = data2

    # final fallback: extract from listBase directly (heavy but better than empty)
    if not fmap and isinstance(listbase, (dict, list)):
        fmap = _fonbet_extract_factor_map(listbase) or {}
        data = listbase

    # empty catalog happens sometimes -> short TTL, but DO NOT overwrite existing non-empty
    if not fmap:
        _FONBET_CATALOG_CACHE_MAP[key] = {
            "ts": now,
            "ttl": 30,
            "map": entry.get("map") or {},
            "data": data,
        }
        return _FONBET_CATALOG_CACHE_MAP[key]["map"] or {}

    _FONBET_CATALOG_CACHE_MAP[key] = {"ts": now, "ttl": _FONBET_CATALOG_TTL_SEC, "map": fmap, "data": data}
    return fmap

    sys_id = int(_env("FONBET_SYS_ID", default="21") or "21")
    lang = _env("FONBET_LANG", default="ru") or "ru"

    data = None
    for base in _fonbet_line_bases():
        url = f"{base}/line/factorsCatalog/eventViewTables?version=0&lang={lang}&sysId={sys_id}"
        data = _http_get_json(url, timeout=15.0)
        if isinstance(data, (dict, list)):
            break

    fmap: Dict[int, Dict[str, str]] = {}
    if isinstance(data, (dict, list)):
        fmap = _fonbet_extract_factor_map(data)

    _FONBET_CATALOG_CACHE.update({"ts": now, "data": data, "map": fmap})
    return fmap


def _table_has_col(cur, table: str, col: str) -> bool:
    try:
        cur.execute(f"SHOW COLUMNS FROM {table}")
        cols = [r.get("Field") for r in (cur.fetchall() or []) if isinstance(r, dict)]
        return col in cols
    except Exception:
        return False


def _sql_fonbet_events(cur, hours: int, q: str, limit: int, sport_id: int) -> List[dict]:
    """
    Returns Fonbet events for the upcoming window.

    NOTE:
    - Fonbet may store start_ts in different formats depending on the parser build:
        * Unix seconds (10 digits)
        * Unix milliseconds (13 digits)
        * YYYYMMDDHHMMSS (14 digits)
      This helper normalizes start_ts to unix seconds for filtering/sorting.
    """
    has_sport = _table_has_col(cur, "fonbet_events", "sport_id")

    # normalize e.start_ts -> unix seconds
    ts_raw = "CAST(e.start_ts AS UNSIGNED)"
    ts_norm = (
        "CASE "
        f"WHEN {ts_raw} >= 10000000000000 THEN UNIX_TIMESTAMP(STR_TO_DATE(CAST(e.start_ts AS CHAR), '%Y%m%d%H%i%s')) "
        f"WHEN {ts_raw} >= 1000000000000 THEN FLOOR({ts_raw}/1000) "
        f"ELSE {ts_raw} "
        "END"
    )

    where = [
        "e.start_ts IS NOT NULL",
        f"{ts_norm} IS NOT NULL",
        f"{ts_norm} >= UNIX_TIMESTAMP(NOW())",
        f"{ts_norm} <= UNIX_TIMESTAMP(NOW()) + %s",
        # keep team placeholders (like '?') - we can hide them in UI later
        "e.team1 IS NOT NULL AND e.team1 <> '' AND e.team1 <> '?'",
        "e.team2 IS NOT NULL AND e.team2 <> '' AND e.team2 <> '?'",
    ]
    params: List[Any] = [int(hours) * 3600]

    # sport_id=0 means "any"
    if has_sport and int(sport_id) > 0:
        where.append("e.sport_id = %s")
        params.append(int(sport_id))

    if q:
        where.append("(e.team1 LIKE %s OR e.team2 LIKE %s OR e.league_name LIKE %s)")
        params += [f"%{q}%", f"%{q}%", f"%{q}%"]

    select_sport = ", e.sport_id AS sport_id" if has_sport else ", NULL AS sport_id"
    sql = f"""
    SELECT
      e.event_id{select_sport},
      COALESCE(NULLIF(e.league_name,''), '-') AS league_name,
      e.team1, e.team2,
      FROM_UNIXTIME({ts_norm}) AS start_time,
      e.start_ts
    FROM fonbet_events e
    WHERE {' AND '.join(where)}
    ORDER BY league_name ASC, {ts_norm} ASC
    LIMIT %s
    """
    params.append(int(limit))
    cur.execute(sql, params)
    return cur.fetchall() or []
def _sql_fonbet_drops_map(cur, ts_col: str, hours: int = 6) -> Dict[int, dict]:
    """
    For each event_id: count factors where last odd < prev odd; also min delta among dropped factors.
    Works with DATETIME timestamps and with integer unix timestamps (s/ms).
    Uses MySQL 8 window functions.
    """
    try:
        cond, params = _fonbet_ts_where(cur, ts_col, int(hours))
        cur.execute(
            f"""
            WITH last2 AS (
              SELECT event_id, factor_id, odd, {ts_col} AS ts_raw,
                     ROW_NUMBER() OVER (PARTITION BY event_id, factor_id ORDER BY {ts_col} DESC) rn
              FROM fonbet_odds_history
              WHERE {cond}
            ),
            p AS (
              SELECT event_id, factor_id,
                     MAX(CASE WHEN rn=1 THEN odd END) AS odd,
                     MAX(CASE WHEN rn=2 THEN odd END) AS prev_odd
              FROM last2
              WHERE rn <= 2
              GROUP BY event_id, factor_id
            )
            SELECT
              event_id,
              SUM(CASE WHEN prev_odd IS NOT NULL AND odd < prev_odd THEN 1 ELSE 0 END) AS drops,
              MIN(CASE WHEN prev_odd IS NOT NULL THEN (odd - prev_odd) ELSE NULL END) AS max_drop
            FROM p
            GROUP BY event_id
            """,
            params,
        )
        rows = cur.fetchall() or []
        return {int(r["event_id"]): r for r in rows if r.get("event_id") is not None}
    except Exception:
        return {}

def _sql_fonbet_event_factors(cur, event_id: int, hours: int, ts_col: str) -> List[dict]:
    """
    Latest + previous odds for each factor in the time window.
    Works with DATETIME timestamps and with integer unix timestamps (s/ms).
    """
    cond, params = _fonbet_ts_where(cur, ts_col, int(hours))
    ts_select = _fonbet_ts_select_expr(cur, ts_col)

    cur.execute(
        f"""        WITH w AS (
          SELECT event_id, factor_id, odd, {ts_select} AS ts,
                 ROW_NUMBER() OVER (PARTITION BY factor_id ORDER BY {ts_col} DESC) rn_desc,
                 ROW_NUMBER() OVER (PARTITION BY factor_id ORDER BY {ts_col} ASC) rn_asc
          FROM fonbet_odds_history
          WHERE event_id=%s AND {cond}
        )
        SELECT
          factor_id,
          MAX(CASE WHEN rn_desc=1 THEN odd END) AS odd,
          MAX(CASE WHEN rn_desc=2 THEN odd END) AS prev_odd_tick,
          MAX(CASE WHEN rn_asc=1 THEN odd END) AS open_odd,
          MAX(CASE WHEN rn_desc=1 THEN ts END) AS ts,
          MAX(CASE WHEN rn_asc=1 THEN ts END) AS open_ts
        FROM w
        GROUP BY factor_id
        ORDER BY factor_id
    """,
        [event_id] + list(params),
    )
    return cur.fetchall() or []

@app.route("/api/fonbet/catalog")
def api_fonbet_catalog():
    """Alias for events list (backward compatible)."""
    return api_fonbet_events_impl()

@app.route("/api/fonbet/events")
def api_fonbet_events():
    """Events list (primary endpoint)."""
    # /api/fonbet/catalog is kept as backward-compatible alias
    return api_fonbet_events_impl()

@app.route("/api/fonbet/factor_catalog")
def api_fonbet_factor_catalog():
    """Debug: factorId mapping extracted from factorsCatalog."""
    fmap = fonbet_factor_catalog_map(force=bool(request.args.get("force")))
    sample = []
    for k in sorted(fmap.keys())[:50]:
        meta = fmap.get(k) or {}
        sample.append({"factor_id": k, **meta})
    return jsonify({"count": len(fmap), "sample": sample})


@app.route("/api/fonbet/sport_ids")
def api_fonbet_sport_ids():
    """Return top sport_id values seen in upcoming window + sample matches."""
    hours = safe_int(request.args.get("hours", 12), 12)
    limit = safe_int(request.args.get("limit", 20), 20)
    items = []
    try:
        with db_connect() as conn:
            with conn.cursor() as cur:
                has_sport = _table_has_col(cur, "fonbet_events", "sport_id")
                if not has_sport:
                    return jsonify({"items": [], "note": "fonbet_events has no sport_id column"})
                # group counts
                cur.execute(
                    """
                    SELECT e.sport_id AS sport_id, COUNT(*) AS cnt
                    FROM fonbet_events e
                    WHERE e.start_ts IS NOT NULL
                      AND CASE WHEN e.start_ts > 2000000000 THEN FLOOR(e.start_ts/1000) ELSE e.start_ts END >= UNIX_TIMESTAMP(NOW())
                      AND CASE WHEN e.start_ts > 2000000000 THEN FLOOR(e.start_ts/1000) ELSE e.start_ts END <= UNIX_TIMESTAMP(NOW()) + %s
                      AND e.sport_id IS NOT NULL
                    GROUP BY e.sport_id
                    ORDER BY cnt DESC
                    LIMIT %s
                    """,
                    [hours * 3600, limit]
                )
                rows = cur.fetchall() or []
                for r in rows:
                    sid = int(r.get("sport_id") or 0)
                    cnt = int(r.get("cnt") or 0)
                    # sample
                    cur.execute(
                        """
                        SELECT e.event_id,
                               e.league_name,
                               e.team1, e.team2,
                               FROM_UNIXTIME(CASE WHEN e.start_ts > 2000000000 THEN FLOOR(e.start_ts/1000) ELSE e.start_ts END) AS start_time
                        FROM fonbet_events e
                        WHERE e.sport_id=%s
                          AND e.start_ts IS NOT NULL
                          AND CASE WHEN e.start_ts > 2000000000 THEN FLOOR(e.start_ts/1000) ELSE e.start_ts END >= UNIX_TIMESTAMP(NOW())
                          AND CASE WHEN e.start_ts > 2000000000 THEN FLOOR(e.start_ts/1000) ELSE e.start_ts END <= UNIX_TIMESTAMP(NOW()) + %s
                        ORDER BY e.start_ts ASC
                        LIMIT 3
                        """,
                        [sid, hours * 3600]
                    )
                    sample = cur.fetchall() or []
                    items.append({"sport_id": sid, "count": cnt, "sample": sample})
    except Exception as e:
        return jsonify({"items": [], "error": str(e)}), 500
    football_sid = 0
    try:
        with db_connect() as conn:
            with conn.cursor() as cur:
                football_sid = _football_sport_id(cur)
    except Exception:
        football_sid = 0
    if not football_sid:
        football_sid = _guess_football_sport_id_from_items(items)
    return jsonify({"items": items, "hours": hours, "limit": limit, "football_sport_id": football_sid})


@app.route("/api/fonbet/event/<int:event_id>")
def api_fonbet_event(event_id: int):
    hours = safe_int(request.args.get("hours", 6), 6)
    limit = safe_int(request.args.get("limit", 1500), 1500)

    try:
        with db_connect() as conn:
            with conn.cursor() as cur:
                has_sport = _table_has_col(cur, "fonbet_events", "sport_id")
                select_sport = ", sport_id" if has_sport else ""
                cur.execute(
                    f"SELECT event_id, league_name, team1, team2{select_sport}, "
                    "CASE WHEN start_ts > 2000000000 THEN FROM_UNIXTIME(FLOOR(start_ts/1000)) "
                    "ELSE FROM_UNIXTIME(start_ts) END AS start_time "
                    "FROM fonbet_events WHERE event_id=%s",
                    (event_id,),
                )
                event = cur.fetchone() or {"event_id": event_id}

                ts_col = _fonbet_ts_col(cur)

                factors = _sql_fonbet_event_factors(cur, event_id=event_id, hours=hours, ts_col=ts_col)
                # limit factors if user wants
                if limit and len(factors) > limit:
                    factors = factors[:limit]

        fmap = fonbet_factor_catalog_map(force=False)
        catalog_count = len(fmap)

        markets = {"outcomes": [], "handicap": [], "total": [], "other": []}
        for r in factors:
            fid = int(r.get("factor_id") or 0)
            meta = fmap.get(fid) or {}
            label = meta.get("label") or f"factor {fid}"
            market = meta.get("market") or _fonbet_classify_market(label) or "other"
            if market not in markets:
                market = "other"

            # Use "open" as Prev (movement from beginning of selected window to latest), like Inforadar.
            odd_now = r.get("odd")
            prev_open = (r.get("open_odd") if r.get("open_odd") is not None else r.get("prev_odd_tick"))
            try:
                delta_val = (float(odd_now) - float(prev_open)) if (odd_now is not None and prev_open is not None) else None
            except Exception:
                delta_val = None

            row = {
                "factor_id": fid,
                "label": label,
                "odd": odd_now,
                "prev_odd": prev_open,
                "delta": delta_val,
                "ts": r.get("ts"),
            }
            markets[market].append(row)

        # keep only reasonable sizes for main markets
        # Keep only the main (balanced) line for handicap & total, like Inforadar.
        def _parse_line_from_label(lbl: str):
            m = re.search(r"\(([-+]?\d+(?:\.\d+)?)\)", lbl or "")
            try:
                return float(m.group(1)) if m else None
            except Exception:
                return None

        def _pick_balanced_line(rows, kind: str):
            groups = {}
            for row in rows:
                lbl = str(row.get("label") or "")
                line = _parse_line_from_label(lbl)
                if line is None:
                    continue
                key = abs(line) if kind == "handicap" else line

                side = None
                l0 = lbl.strip().lower()
                if kind == "handicap":
                    if l0.startswith("1"):
                        side = "home"
                    elif l0.startswith("2"):
                        side = "away"
                else:
                    # Б = over, М = under
                    if l0.startswith("б") or l0.startswith("over") or l0.startswith("o "):
                        side = "over"
                    elif l0.startswith("м") or l0.startswith("under") or l0.startswith("u "):
                        side = "under"

                if not side:
                    continue

                g = groups.setdefault(key, {})
                g[side] = row

            best_key = None
            best_score = None
            for key, g in groups.items():
                if kind == "handicap":
                    a, b = g.get("home"), g.get("away")
                else:
                    a, b = g.get("over"), g.get("under")

                if not a or not b:
                    continue

                try:
                    oa = float(a.get("odd"))
                    ob = float(b.get("odd"))
                except Exception:
                    continue

                score = abs(oa - ob)

                if best_score is None or score < best_score - 1e-9:
                    best_key, best_score = key, score
                elif abs(score - best_score) < 1e-9:
                    # tie-breakers
                    if kind == "handicap" and best_key is not None and key < best_key:
                        best_key = key
                    if kind == "total" and best_key is not None and abs(key - 2.5) < abs(best_key - 2.5):
                        best_key = key

            if best_key is None:
                return rows

            chosen = groups.get(best_key) or {}
            if kind == "handicap":
                return [chosen.get("home"), chosen.get("away")]
            return [chosen.get("over"), chosen.get("under")]

        if len(markets.get("handicap") or []) > 2:
            markets["handicap"] = [r for r in _pick_balanced_line(markets["handicap"], "handicap") if r]
        if len(markets.get("total") or []) > 2:
            markets["total"] = [r for r in _pick_balanced_line(markets["total"], "total") if r]

        markets["outcomes"] = markets["outcomes"][:20]
        markets["handicap"] = markets["handicap"][:60]
        markets["total"] = markets["total"][:60]
        markets["other"] = markets["other"][:500]

        return jsonify({"event": event, "markets": markets, "count": len(factors), "catalog_count": catalog_count})

    except Exception as e:
        return jsonify({"error": str(e), "event": {"event_id": event_id}, "markets": {"outcomes": [], "handicap": [], "total": [], "other": []}, "count": 0}), 500


# ------------------------------
# FONBET: Inforadar-like HISTORY TABLES (FT / 1H)
# ------------------------------

def _fonbet_parse_line(lbl: str) -> Optional[float]:
    m = re.search(r"\(([-+]?\d+(?:\.\d+)?)\)", lbl or "")
    if not m:
        # fallback: first number in label
        m2 = re.search(r"([-+]?\d+(?:\.\d+)?)", (lbl or "").replace(",", "."))
        if not m2:
            return None
        try:
            return float(m2.group(1))
        except Exception:
            return None
    try:
        return float(m.group(1))
    except Exception:
        return None

def _fonbet_norm_outcome(lbl: str) -> Optional[str]:
    s_raw = (lbl or "").strip()
    if not s_raw:
        return None
    s = s_raw.upper()

    # Exclude "double chance"/combos: 1X, X2, 12, and any "или/or" phrases.
    # We only want pure 1 / X / 2 for the 1X2 table.
    if "ИЛИ" in s or " OR " in s or re.search(r"\b(1X|X2|12)\b", s):
        return None
    # Placeholders combined with draw/other side like "%1s или ничья"
    if ("%1" in s or "%2" in s) and ("ИЛИ" in s or "НИЧ" in s or re.search(r"\bX\b", s)):
        return None

    # draw
    if s in ("X", "Х", "Н", "DRAW", "D") or ("НИЧ" in s):
        return "X"

    # wins
    if "%1" in s or s in ("1", "П1", "W1", "WIN1", "HOME") or ("П1" in s):
        return "1"
    if "%2" in s or s in ("2", "П2", "W2", "WIN2", "AWAY") or ("П2" in s):
        return "2"

    return None

def _fonbet_is_home_hcp(lbl: str) -> bool:
    s = (lbl or "").upper().strip()
    return ("Ф1" in s) or ("H1" in s) or ("HANDICAP 1" in s) or s.startswith("1(") or s.startswith("1 ")

def _fonbet_is_away_hcp(lbl: str) -> bool:
    s = (lbl or "").upper().strip()
    return ("Ф2" in s) or ("H2" in s) or ("HANDICAP 2" in s) or s.startswith("2(") or s.startswith("2 ")

def _fonbet_is_over(lbl: str) -> bool:
    s = (lbl or "").upper()
    return ("ТБ" in s) or ("OVER" in s) or (s.strip().startswith("O(")) or (s.strip().startswith("Б(")) or (s.strip().startswith("БОЛЬШЕ"))

def _fonbet_is_under(lbl: str) -> bool:
    s = (lbl or "").upper()
    return ("ТМ" in s) or ("UNDER" in s) or (s.strip().startswith("U(")) or (s.strip().startswith("М(")) or (s.strip().startswith("МЕНЬШЕ"))

def _median_nearest(values: List[float]) -> Optional[float]:
    if not values:
        return None
    vs = sorted(values)
    mid = vs[len(vs)//2]
    if len(vs) % 2 == 0:
        mid = (vs[len(vs)//2 - 1] + vs[len(vs)//2]) / 2.0
    return min(vs, key=lambda x: (abs(x-mid), abs(x)))

def _choose_mainline(line_counts: Dict[float, int]) -> Optional[float]:
    if not line_counts:
        return None
    mx = max(line_counts.values())
    cand = [k for k,v in line_counts.items() if v == mx]
    if len(cand) == 1:
        return cand[0]
    return _median_nearest(cand)

def _fonbet_tables_from_rows(rows: List[dict], fmap: Dict[int, Dict[str, Any]], half: str, team1: str = "", team2: str = "", market_map: Optional[dict] = None) -> Dict[str, Any]:
    """
    Build Inforadar-like history tables from raw fonbet_odds_history rows.

    IMPORTANT: fonbet_odds_history часто хранит только изменившиеся факторы на каждом ts.
    Поэтому используем forward-fill (держим текущее состояние и обновляем его по мере поступления рядов).
    """
    want_1h = (half or "ft").lower() in ("1h", "ht", "h1", "1st")

    def _norm_team_name(s: str) -> str:
        s = (s or "").strip().lower().replace("ё", "е")
        s = re.sub(r"\s+", " ", s)
        return s

    t1n = _norm_team_name(team1)
    t2n = _norm_team_name(team2)

    market_map = market_map or {}



    # Precompute stable mappings from factorId -> outcome/side using catalog (fmap),
    # so we don't accidentally mix 1X/X2/12 into the 1X2 table.
    def _build_outcome_fid_map() -> Dict[int, str]:
        candidates: List[Tuple[int, str]] = []
        for fid, info in (fmap or {}).items():
            mkt = str(info.get("market") or "")
            base = mkt[:-3] if mkt.endswith("_1h") else mkt
            if base != "outcomes":
                continue
            if want_1h:
                if not mkt.endswith("_1h"):
                    continue
            else:
                if mkt.endswith("_1h"):
                    continue

            lbl = str(info.get("label") or "")
            up = lbl.upper()
            if "ИЛИ" in up or re.search(r"\b(1X|X2|12)\b", up):
                continue
            oc = _fonbet_norm_outcome(lbl)
            if oc in ("1", "X", "2"):
                candidates.append((int(fid), oc))

        fid2oc: Dict[int, str] = {}
        used: set = set()

        for oc in ("1", "X", "2"):
            fids = sorted([fid for fid, o in candidates if o == oc])
            if fids:
                fid2oc[fids[0]] = oc
                used.add(fids[0])

        # Fallback by remaining non-double-chance outcome factors (by id order)
        if len(fid2oc) < 3:
            all_ok: List[int] = []
            draw_fid = None
            for fid, info in (fmap or {}).items():
                mkt = str(info.get("market") or "")
                base = mkt[:-3] if mkt.endswith("_1h") else mkt
                if base != "outcomes":
                    continue
                if want_1h:
                    if not mkt.endswith("_1h"):
                        continue
                else:
                    if mkt.endswith("_1h"):
                        continue

                lbl = str(info.get("label") or "")
                up = lbl.upper()
                if "ИЛИ" in up or re.search(r"\b(1X|X2|12)\b", up):
                    continue
                all_ok.append(int(fid))
                if draw_fid is None and ("НИЧ" in up or up.strip() in ("X", "Х", "Н", "DRAW", "D")):
                    draw_fid = int(fid)

            all_ok = sorted(set(all_ok))

            if draw_fid is not None and draw_fid not in used and "X" not in fid2oc.values():
                fid2oc[draw_fid] = "X"
                used.add(draw_fid)

            remaining = [fid for fid in all_ok if fid not in used]
            if remaining and "1" not in fid2oc.values():
                fid2oc[remaining[0]] = "1"
                used.add(remaining[0])
                remaining = [fid for fid in remaining if fid not in used]
            if remaining and "2" not in fid2oc.values():
                fid2oc[remaining[-1]] = "2"
                used.add(remaining[-1])

        return fid2oc

    def _build_side_map(base_market: str) -> Dict[int, str]:
        groups: Dict[float, List[int]] = {}
        for fid, info in (fmap or {}).items():
            mkt = str(info.get("market") or "")
            base = mkt[:-3] if mkt.endswith("_1h") else mkt
            if base != base_market:
                continue
            if want_1h:
                if not mkt.endswith("_1h"):
                    continue
            else:
                if mkt.endswith("_1h"):
                    continue

            line = info.get("param")
            try:
                line_f = float(str(line).replace(",", ".")) if line not in (None, "") else None
            except Exception:
                line_f = None
            if line_f is None:
                line_f = _fonbet_parse_line(str(info.get("label") or ""))
            if line_f is None:
                continue

            groups.setdefault(line_f, []).append(int(fid))

        side_map: Dict[int, str] = {}
        for line, fids in groups.items():
            fids = sorted(set(fids))
            if len(fids) >= 2:
                if base_market == "handicap":
                    side_map[fids[0]] = "home"
                    side_map[fids[1]] = "away"
                else:
                    side_map[fids[0]] = "over"
                    side_map[fids[1]] = "under"
        return side_map

    outcome_fid_map = _build_outcome_fid_map()
    hcp_fid_side = _build_side_map("handicap")
    tot_fid_side = _build_side_map("total")

    # helper: pick label/market/param for fid
    def get_label(fid: int, r: dict) -> str:
        lbl = r.get("label")
        if lbl:
            return str(lbl)
        info = fmap.get(fid) or {}
        return str(info.get("label") or f"factor {fid}")

    def get_market(fid: int, r: dict) -> str:
        info = fmap.get(fid) or {}
        m = str(info.get("market") or "")
        if not m:
            m = _fonbet_classify_market(get_label(fid, r))
        # extra heuristic: Fonbet 1X2 factors часто имеют label = team name / draw without keywords
        if (not m) or m == "other":
            _lbl = get_label(fid, r)
            _nl = _norm_team_name(_lbl)
            if _nl and (("нич" in _nl) or _nl in ("x","х","н","draw","d") or (t1n and _nl == t1n) or (t2n and _nl == t2n)):
                m = "outcomes_1h" if want_1h else "outcomes"

        # respect half toggle
        if want_1h and m in ("outcomes_1h", "handicap_1h", "total_1h"):
            return m
        if (not want_1h) and m.endswith("_1h"):
            # ignore HT markets in FT mode
            return "other"
        return m

    def get_param(fid: int, r: dict) -> Optional[float]:
        # 1) row param column (different schemas)
        for k in ("param", "p", "line", "value", "handicap", "total"):
            pv = r.get(k)
            if pv not in (None, ""):
                try:
                    return float(str(pv).replace(",", "."))
                except Exception:
                    pass
        # 2) fmap param
        info = fmap.get(fid) or {}
        pv2 = info.get("param")
        if pv2 not in (None, ""):
            try:
                return float(str(pv2).replace(",", "."))
            except Exception:
                pass
        # 3) parse from label
        return _fonbet_parse_line(get_label(fid, r))

    # normalize/parse side for handicap/total when label doesn't specify it
    def hcp_side_from_label(lbl: str) -> Optional[str]:
        t = (lbl or "").lower()
        if any(x in t for x in ("ф1", "home", "хозя", "1(", "1 (")):
            return "home"
        if any(x in t for x in ("ф2", "away", "гост", "2(", "2 (")):
            return "away"
        return None

    def tot_side_from_label(lbl: str) -> Optional[str]:
        t = _norm_team_name(lbl)
        if ("тб" in t) or ("over" in t) or ("больше" in t) or re.match(r"^б\b", t) or t.startswith("б "):
            return "over"
        if ("тм" in t) or ("under" in t) or ("меньше" in t) or re.match(r"^м\b", t) or t.startswith("м "):
            return "under"
        if re.search(r"\bou\s*\(", t) or re.search(r"\bo\s*\(", t):
            return "over"
        if re.search(r"\bun\s*\(", t) or re.search(r"\bu\s*\(", t):
            return "under"
        return None

    # Group rows by ts (already ordered by ts asc in SQL, but be safe)
    # Expect ts in r["ts"] as string "YYYY-MM-DD HH:MM:SS"
    # We'll keep stable order.
    rows_sorted = sorted(rows or [], key=lambda x: str(x.get("ts") or ""))

    # current state
    cur_out: Dict[str, float] = {}  # "1"/"X"/"2" -> odd
    cur_hcp: Dict[float, Dict[str, float]] = {}  # line -> {"home":odd, "away":odd}
    cur_tot: Dict[float, Dict[str, float]] = {}  # line -> {"over":odd, "under":odd}

    # for lines where label doesn't specify side, map by fid order
    hcp_fid_order: Dict[float, List[int]] = {}
    hcp_home_line: Dict[float, float] = {}  # abs_line -> signed line for HOME side
    tot_fid_order: Dict[float, List[int]] = {}

    # snapshots collected per ts
    snap_out: List[Dict[str, Any]] = []
    snap_hcp_by_line: Dict[float, List[Dict[str, Any]]] = {}
    snap_tot_by_line: Dict[float, List[Dict[str, Any]]] = {}

    # iterate by ts groups
    i = 0
    while i < len(rows_sorted):
        ts = str(rows_sorted[i].get("ts") or "")
        # update with all rows in this ts
        j = i
        while j < len(rows_sorted) and str(rows_sorted[j].get("ts") or "") == ts:
            r = rows_sorted[j]
            fid = int(r.get("factor_id") or 0)
            odd = safe_float(r.get("odd"))
            lbl = get_label(fid, r)
            market = get_market(fid, r)

            # ignore empty/invalid odds
            if odd is None:
                j += 1
                continue

            base_m = market[:-3] if market.endswith("_1h") else market

            if base_m == "outcomes":
                oc = outcome_fid_map.get(fid) or _fonbet_norm_outcome(lbl)
                if oc is None:
                    nl = _norm_team_name(lbl)
                    # avoid double chance / combos
                    if ("или" in nl) or (" or " in nl) or re.search(r"\b(1x|x2|12)\b", nl):
                        oc = None
                    elif t1n and nl == t1n:
                        oc = "1"
                    elif t2n and nl == t2n:
                        oc = "2"
                    elif ("нич" in nl) or nl in ("x","х","н","draw","d"):
                        oc = "X"

                if oc is None:
                    nl = _norm_team_name(lbl)
                    if t1n and nl == t1n:
                        oc = "1"
                    elif t2n and nl == t2n:
                        oc = "2"
                # ignore double chance / other outcomes (we need only 1/X/2)
                if oc in ("1", "X", "2"):
                    cur_out[oc] = odd

            elif base_m == "handicap":
                line = get_param(fid, r)
                if line is None:
                    j += 1
                    continue
                abs_line = abs(line)
                side = hcp_fid_side.get(fid) or hcp_side_from_label(lbl)
                if side is None:
                    nl = _norm_team_name(lbl)
                    # label может содержать линию в скобках: "Team (+1)" -> используем contains
                    if t1n and (nl == t1n or (t1n in nl)):
                        side = "home"
                    elif t2n and (nl == t2n or (t2n in nl)):
                        side = "away"
                # if still unknown, heuristic by sign (common: home=-abs, away=+abs)
                if side is None:
                    if line < 0:
                        side = "home"
                    elif line > 0:
                        side = "away"
                if side is None:
                    # infer by fid order within this line
                    arr = hcp_fid_order.setdefault(abs_line, [])
                    if fid not in arr:
                        arr.append(fid)
                    side = "home" if arr and arr[0] == fid else ("away" if len(arr) > 1 and arr[1] == fid else None)
                if side in ("home", "away"):
                    cur_hcp.setdefault(abs_line, {})[side] = odd
                    # keep signed home-line for display (Inforadar shows home side line)
                    if side == "home":
                        hcp_home_line[abs_line] = float(line)
                    elif side == "away":
                        hcp_home_line.setdefault(abs_line, float(-line))

                # heuristic: if we have one handicap factor and another unknown label with same param, it might be the other side
                # (handled naturally by fid order above)

            elif base_m == "total":
                line = get_param(fid, r)
                if line is None:
                    j += 1
                    continue
                side = tot_fid_side.get(fid) or tot_side_from_label(lbl)
                if side is None:
                    arr = tot_fid_order.setdefault(line, [])
                    if fid not in arr:
                        arr.append(fid)
                    side = "over" if arr and arr[0] == fid else ("under" if len(arr) > 1 and arr[1] == fid else None)
                if side in ("over", "under"):
                    cur_tot.setdefault(line, {})[side] = odd

            j += 1

        # after updates at this ts, emit snapshot rows
        if cur_out:
            snap_out.append({
                "Time": ts,
                "1": cur_out.get("1"),
                "X": cur_out.get("X"),
                "2": cur_out.get("2"),
            })

        for line, d in cur_hcp.items():
            if "home" in d or "away" in d:
                snap_hcp_by_line.setdefault(line, []).append({
                    "Time": ts,
                    "Home": d.get("home"),
                    "Handicap": line,
                    "Away": d.get("away"),
                })

        for line, d in cur_tot.items():
            if "over" in d or "under" in d:
                snap_tot_by_line.setdefault(line, []).append({
                    "Time": ts,
                    "Over": d.get("over"),
                    "Total": line,
                    "Under": d.get("under"),
                })

        i = j

    # choose mainline: line with max rows having both sides present
        def best_line(snaps: Dict[float, List[Dict[str, Any]]], key_a: str, key_b: str) -> Optional[float]:
            """Pick a mainline similar to Fonbet UI: the most recent complete line, then the most 'balanced'."""
            best: Optional[float] = None
            best_key: Optional[tuple] = None

            for line, arr in snaps.items():
                both = [r for r in arr if (r.get(key_a) is not None) and (r.get(key_b) is not None)]
                if not both:
                    continue

                # Most recent timestamp where both sides exist
                last_time = max(str(r.get("Time") or "") for r in both)
                last_row = next((r for r in reversed(both) if str(r.get("Time") or "") == last_time), both[-1])

                try:
                    a = float(last_row.get(key_a))
                    b = float(last_row.get(key_b))
                except Exception:
                    continue

                bal = abs(a - b)                        # closer to each other
                clos = abs(a - 2.0) + abs(b - 2.0)      # closer to ~2.00 each (typical mainline)

                # Compare: newer time, then closer-to-2, then more balanced, then more history, then smaller abs(line)
                key = (last_time, -clos, -bal, len(both), -abs(float(line)))
                if (best_key is None) or (key > best_key):
                    best_key = key
                    best = float(line)

            return best

    # Prefer mainlines from eventView mapping (Inforadar-like).
    mm_main_h = market_map.get("main_hcp")
    mm_main_t = market_map.get("main_total")

    main_h: Optional[float] = None
    main_t: Optional[float] = None
    if mm_main_h is not None:
        try:
            main_h = float(mm_main_h)
        except Exception:
            main_h = None
    if mm_main_t is not None:
        try:
            main_t = float(mm_main_t)
        except Exception:
            main_t = None

    # Fallback to history-based heuristic if mapping is missing
    if main_h is None:
        main_h = best_line(snap_hcp_by_line, "Home", "Away")
    if main_t is None:
        main_t = best_line(snap_tot_by_line, "Over", "Under")

    # convert abs-line key -> signed line for HOME side (Fonbet often stores +X for away and -X for home as separate params)
    main_h_display: Optional[float] = None
    if main_h is not None:
        try:
            mh = float(main_h)
        except Exception:
            mh = None
        if mh is not None:
            if mh == 0:
                main_h_display = 0.0
            else:
                main_h_display = hcp_home_line.get(mh)
                if main_h_display is None:
                    main_h_display = -mh

    # compute Alg1/Alg2 relative to first complete row
    handicap: List[Dict[str, Any]] = []
    if main_h is not None:
        arr = snap_hcp_by_line.get(main_h) or []
        base_home = base_away = None
        for r in arr:
            if r.get("Home") is not None and r.get("Away") is not None:
                base_home, base_away = r.get("Home"), r.get("Away")
                break
        for r in arr:
            if r.get("Home") is None or r.get("Away") is None:
                continue
            handicap.append({
                "Time": r["Time"],
                "Home": r["Home"],
                "Handicap": main_h_display,
                "Hcp": main_h_display,
                "Away": r["Away"],
                "Alg1": (r["Home"] - base_home) if (base_home is not None and r.get("Home") is not None) else None,
                "Alg2": (r["Away"] - base_away) if (base_away is not None and r.get("Away") is not None) else None,
            })

    total: List[Dict[str, Any]] = []
    if main_t is not None:
        arr = snap_tot_by_line.get(main_t) or []
        base_over = base_under = None
        for r in arr:
            if r.get("Over") is not None and r.get("Under") is not None:
                base_over, base_under = r.get("Over"), r.get("Under")
                break
        for r in arr:
            if r.get("Over") is None or r.get("Under") is None:
                continue
            total.append({
                "Time": r["Time"],
                "Over": r["Over"],
                "Total": main_t,
                "Under": r["Under"],
                "Alg1": (r["Over"] - base_over) if (base_over is not None and r.get("Over") is not None) else None,
                "Alg2": (r["Under"] - base_under) if (base_under is not None and r.get("Under") is not None) else None,
            })

    outcomes = snap_out

    return {
        "outcomes": outcomes,
        "handicap": handicap,
        "total": total,
        "meta": {
            "half": half,
            "snapshots": len(set(str(r.get("ts") or r.get("Time") or "") for r in rows_sorted)) if rows_sorted else 0,
            "raw_rows": len(rows_sorted),
            "main_handicap": main_h_display,
            "main_total": main_t,
        }
    }


# ------------------------------
# FONBET: STRICT "like Inforadar" TABLES (FT only) using eventView mapping
# ------------------------------

def _fonbet_tables_from_rows_strict_inforadar(
    rows: List[dict],
    market_map: Dict[str, Any],
) -> Dict[str, Any]:
    """Build FT tables strictly limited to:
    - 1X2 outcomes
    - Match goals total (O/U)
    - Match asian handicap (home sign preserved)

    market_map must come from build_market_map_from_eventview(eventView).
    """

    def fnum(x: Any) -> Optional[float]:
        if x is None:
            return None
        if isinstance(x, (int, float)):
            return float(x)
        s = str(x).strip().replace(",", ".")
        if not s:
            return None
        try:
            return float(s)
        except Exception:
            return None

    # Build factor_id -> (kind, line_key, side)
    fid_map: Dict[int, Tuple[str, str, str]] = {}

    outcomes: Dict[str, int] = market_map.get("outcomes") or {}
    for oc, fid in outcomes.items():
        try:
            fid_map[int(fid)] = ("outcomes", oc, oc)
        except Exception:
            continue

    total_pairs: Dict[str, Tuple[int, int]] = market_map.get("total_pairs") or {}
    for line, pair in total_pairs.items():
        try:
            fo, fu = pair
            fid_map[int(fo)] = ("total", str(line), "Over")
            fid_map[int(fu)] = ("total", str(line), "Under")
        except Exception:
            continue

    asian_rows: List[Dict[str, Any]] = market_map.get("asian_hcp_rows") or []
    for r in asian_rows:
        try:
            hcp = str(r.get("hcp"))
            fid_map[int(r["home_factorId"])] = ("handicap", hcp, "Home")
            fid_map[int(r["away_factorId"])] = ("handicap", hcp, "Away")
        except Exception:
            continue

    # Filter rows to only allowed factorIds
    rows2 = []
    for r in rows or []:
        fid = safe_int(r.get("factor_id") or 0, 0)
        if fid and fid in fid_map:
            rows2.append(r)

    rows_sorted = sorted(rows2, key=lambda x: str(x.get("ts") or ""))

    odds_by_fid: Dict[int, float] = {}
    cur_out: Dict[str, Optional[float]] = {"1": None, "X": None, "2": None}

    # Helpers to get current values for a line from odds_by_fid
    def _cur_total(line: str) -> Tuple[Optional[float], Optional[float]]:
        pair = total_pairs.get(line)
        if not pair:
            return None, None
        fo, fu = int(pair[0]), int(pair[1])
        return odds_by_fid.get(fo), odds_by_fid.get(fu)

    def _cur_hcp(hcp: str) -> Tuple[Optional[float], Optional[float]]:
        for rr in asian_rows:
            if str(rr.get("hcp")) == str(hcp):
                fo, fu = int(rr["home_factorId"]), int(rr["away_factorId"])
                return odds_by_fid.get(fo), odds_by_fid.get(fu)
        return None, None

    # Outputs
    outcomes_tbl: List[Dict[str, Any]] = []
    total_tbl: List[Dict[str, Any]] = []

    def _append_if_changed(tbl, row, keys):
        """Append `row` only when any of `keys` changed vs previous row (rounded)."""
        if not tbl:
            tbl.append(row)
            return
        prev = tbl[-1]
        for k in keys:
            a = prev.get(k)
            b = row.get(k)
            if a is None and b is None:
                continue
            if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                # odds/lines can have tiny float noise; round before compare
                if round(float(a), 4) != round(float(b), 4):
                    tbl.append(row)
                    return
            else:
                if a != b:
                    tbl.append(row)
                    return
        # unchanged -> skip (keeps the time of the last actual change)
    hcp_tbl: List[Dict[str, Any]] = []

    base_total_line: Optional[str] = None
    base_over = base_under = None

    base_hcp_line: Optional[str] = None
    base_home = base_away = None

    # Iterate by timestamps and forward-fill current state
    i = 0
    while i < len(rows_sorted):
        ts = str(rows_sorted[i].get("ts") or "")
        j = i
        while j < len(rows_sorted) and str(rows_sorted[j].get("ts") or "") == ts:
            r = rows_sorted[j]
            fid = safe_int(r.get("factor_id") or 0, 0)
            odd = fnum(r.get("odd"))
            if not fid or odd is None:
                j += 1
                continue

            odds_by_fid[fid] = float(odd)

            kind, line_key, side = fid_map.get(fid, ("", "", ""))
            if kind == "outcomes" and side in ("1", "X", "2"):
                cur_out[side] = float(odd)

            j += 1

        # Outcomes snapshot (always show row once we have at least one value)
        if any(v is not None for v in cur_out.values()):
            _append_if_changed(outcomes_tbl, {
                "Time": ts,
                "1": cur_out.get("1"),
                "X": cur_out.get("X"),
                "2": cur_out.get("2"),
            }, ["1","X","2"])

        # Choose mainlines *for this snapshot* (allows switching 2.5 -> 3.0 etc.)
        cur_main_total = None
        cur_main_hcp = None
        if _HAS_FONBET_INFORADAR_MARKETS and choose_mainline_total and total_pairs:
            try:
                cur_main_total = choose_mainline_total(total_pairs, odds_by_fid)
            except Exception:
                cur_main_total = None
        if _HAS_FONBET_INFORADAR_MARKETS and choose_mainline_asian_hcp and asian_rows:
            try:
                cur_main_hcp = choose_mainline_asian_hcp(asian_rows, odds_by_fid)
            except Exception:
                cur_main_hcp = None

        # Total row
        if cur_main_total:
            over, under = _cur_total(str(cur_main_total))
            if over is not None and under is not None:
                if base_total_line != str(cur_main_total):
                    base_total_line = str(cur_main_total)
                    base_over, base_under = over, under
                _append_if_changed(total_tbl, {
                    "Time": ts,
                    "Over": over,
                    "Total": fnum(cur_main_total),
                    "Under": under,
                    "Alg1": (over - base_over) if (base_over is not None) else None,
                    "Alg2": (under - base_under) if (base_under is not None) else None,
                }, ["Total","Over","Under"])

        # Handicap row
        if cur_main_hcp:
            home, away = _cur_hcp(str(cur_main_hcp))
            if home is not None and away is not None:
                hcp_val = fnum(cur_main_hcp)
                if base_hcp_line != str(cur_main_hcp):
                    base_hcp_line = str(cur_main_hcp)
                    base_home, base_away = home, away
                _append_if_changed(hcp_tbl, {
                    "Time": ts,
                    "Home": home,
                    "Handicap": hcp_val,
                    "Hcp": hcp_val,  # Inforadar: home handicap with sign
                    "Away": away,
                    "Alg1": (home - base_home) if (base_home is not None) else None,
                    "Alg2": (away - base_away) if (base_away is not None) else None,
                }, ["Handicap","Home","Away"])

        i = j

    # Meta: last chosen lines
    last_total = total_tbl[-1]["Total"] if total_tbl else None
    last_hcp = hcp_tbl[-1]["Handicap"] if hcp_tbl else None

    return {
        "outcomes": outcomes_tbl,
        "handicap": hcp_tbl,
        "total": total_tbl,
        "meta": {
            "strict_mode": True,
            "event_id": market_map.get("event_id"),
            "team1": market_map.get("team1"),
            "team2": market_map.get("team2"),
            "snapshots": len(set(str(r.get("ts") or r.get("Time") or "") for r in rows_sorted)) if rows_sorted else 0,
            "raw_rows": len(rows_sorted),
            "allowed_factor_ids": len(market_map.get("allowed_factor_ids") or []),
            "main_handicap": last_hcp,
            "main_total": last_total,
        }
    }


@app.route("/api/fonbet/event/<int:event_id>/eventView")
def api_fonbet_event_view(event_id: int):
    """
    Debug helper: proxy Fonbet eventView payload (current markets/odds) used for enrichment.
    """
    try:
        lang = _env("FONBET_LANG", default="ru") or "ru"
        sys_id = int(_env("FONBET_SYS_ID", default="21") or "21")
        ev = _fonbet_fetch_event_view(lang=lang, sys_id=sys_id, event_id=event_id)
        return jsonify(ev)
    except Exception as e:
        return jsonify({"error": str(e), "event_id": event_id}), 502

# -----------------------------------------------------------------------------
# Fonbet: resolve 1st-half (HT) sub-event id (Fonbet часто хранит 1H в отдельном event_id)
# Strategy:
#   1) try base eventView -> find child where parentId==base and kind/name indicates 1st half
#   2) fallback to DB siblings by (sport_id, category_id, start_ts) and verify via eventView for candidates
# Cache: short TTL to avoid повторных запросов на eventView.
_FONBET_HALF_EVENT_CACHE: Dict[tuple, tuple] = {}  # (base_event_id, half) -> (effective_event_id, ts_unix)

def _fonbet_norm_half(half_raw: Any) -> str:
    h = str(half_raw or "ft").strip().lower()
    if h in ("undefined", "null", "none", ""):
        return "ft"
    # common aliases from UI / users
    if h in ("ht", "1ht", "1h", "1half", "1sthalf", "firsthalf", "1-half", "1_half"):
        return "1h"
    if h in ("ft", "full", "match", "0"):
        return "ft"
    # tolerant parsing
    if ("1" in h) and (("h" in h) or ("ht" in h) or ("half" in h)):
        return "1h"
    return "ft"

def _fonbet_ev_name_is_1h(name: str) -> bool:
    n = (name or "").strip().lower()
    if not n:
        return False
    # ru/en patterns
    if ("1" in n or "перв" in n or "1st" in n) and ("тайм" in n or "half" in n or "полов" in n):
        return True
    return False

def _fonbet_ev_find_1h_child(ev: Any, base_event_id: int) -> Optional[int]:
    if not isinstance(ev, dict):
        return None
    events = ev.get("events")
    if not isinstance(events, list):
        return None
    # kind 100201 is commonly used by Fonbet for 1st half (based on historical dumps)
    for e in events:
        if not isinstance(e, dict):
            continue
        if safe_int(e.get("parentId"), 0) == int(base_event_id) and safe_int(e.get("kind"), 0) == 100201:
            cid = safe_int(e.get("id"), 0)
            if cid:
                return cid
    # fallback by name
    for e in events:
        if not isinstance(e, dict):
            continue
        if safe_int(e.get("parentId"), 0) != int(base_event_id):
            continue
        if _fonbet_ev_name_is_1h(str(e.get("name") or "")):
            cid = safe_int(e.get("id"), 0)
            if cid:
                return cid
    return None

def _fonbet_ev_is_1h_event(ev: Any, cand_event_id: int, base_event_id: int) -> bool:
    if not isinstance(ev, dict):
        return False
    events = ev.get("events")
    if not isinstance(events, list):
        return False
    for e in events:
        if not isinstance(e, dict):
            continue
        eid = safe_int(e.get("id"), 0)
        if eid != int(cand_event_id):
            continue
        # If this event is explicitly marked as 1H or named like it, accept
        if safe_int(e.get("kind"), 0) == 100201:
            return True
        if safe_int(e.get("parentId"), 0) == int(base_event_id) and _fonbet_ev_name_is_1h(str(e.get("name") or "")):
            return True
        if _fonbet_ev_name_is_1h(str(e.get("name") or "")):
            return True
    # Sometimes event itself has name in root fields
    if _fonbet_ev_name_is_1h(str(ev.get("name") or "")):
        return True
    return False

def _fonbet_resolve_1h_event_id(base_event_id: int, *, lang: str, sys_id: int) -> int:
    key = (int(base_event_id), "1h")
    now = time.time()
    cached = _FONBET_HALF_EVENT_CACHE.get(key)
    if cached and (now - float(cached[1])) < 120.0:
        return int(cached[0])

    # 1) best: fetch base eventView and look for a child 1H
    try:
        ev_base = _fonbet_fetch_event_view(lang=lang, sys_id=sys_id, event_id=int(base_event_id))
        cid = _fonbet_ev_find_1h_child(ev_base, int(base_event_id))
        if cid:
            _FONBET_HALF_EVENT_CACHE[key] = (int(cid), now)
            return int(cid)
    except Exception:
        pass

    # 2) fallback: DB siblings (sport_id, category_id, start_ts)
    candidates: List[Dict[str, Any]] = []
    try:
        with db_connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT sport_id, category_id, start_ts FROM fonbet_events WHERE event_id=%s LIMIT 1", (int(base_event_id),))
                base = cur.fetchone() or {}
                sport_id = safe_int(base.get("sport_id"), 0)
                category_id = safe_int(base.get("category_id"), 0)
                start_ts = safe_int(base.get("start_ts"), 0)
                if not category_id or not start_ts:
                    _FONBET_HALF_EVENT_CACHE[key] = (int(base_event_id), now)
                    return int(base_event_id)

                cur.execute(
                    "SELECT event_id, team1, team2 FROM fonbet_events "
                    "WHERE sport_id=%s AND category_id=%s AND start_ts=%s AND event_id<>%s "
                    "LIMIT 25",
                    (sport_id, category_id, start_ts, int(base_event_id)),
                )
                sibs = cur.fetchall() or []
                for s in sibs:
                    eid = safe_int(s.get("event_id"), 0)
                    if not eid:
                        continue
                    # history count
                    cur.execute("SELECT COUNT(*) AS c FROM fonbet_odds_history WHERE event_id=%s", (eid,))
                    c = safe_int((cur.fetchone() or {}).get("c"), 0)
                    t1 = str(s.get("team1") or "").strip()
                    t2 = str(s.get("team2") or "").strip()
                    null_team = (not t1) or (not t2)
                    # score: prioritize NULL teams (sub-event), then history density, then closeness by id
                    score = (1000000 if null_team else 0) + (c * 10) - int(abs(eid - int(base_event_id)) / 1000)
                    candidates.append({"event_id": eid, "score": score, "hist": c, "null_team": null_team})
    except Exception:
        candidates = []

    candidates.sort(key=lambda x: x.get("score", 0), reverse=True)
    top_ids = [int(c["event_id"]) for c in (candidates[:5] if candidates else []) if safe_int(c.get("event_id"), 0) > 0]

    # 3) verify candidates via their own eventView (точнее, но тяжелее)
    for eid in top_ids:
        try:
            ev_c = _fonbet_fetch_event_view(lang=lang, sys_id=sys_id, event_id=int(eid))
            if _fonbet_ev_is_1h_event(ev_c, int(eid), int(base_event_id)):
                _FONBET_HALF_EVENT_CACHE[key] = (int(eid), now)
                return int(eid)
        except Exception:
            continue

    # 4) fallback: best DB candidate
    if top_ids:
        _FONBET_HALF_EVENT_CACHE[key] = (int(top_ids[0]), now)
        return int(top_ids[0])

    _FONBET_HALF_EVENT_CACHE[key] = (int(base_event_id), now)
    return int(base_event_id)

@app.route("/api/fonbet/event/<int:event_id>/eventViewTables")
def api_fonbet_event_view_tables(event_id: int):
    # alias for compatibility with older debug calls
    return api_fonbet_event_tables(event_id)


@app.route("/api/fonbet/event/<int:event_id>/tables")
def api_fonbet_event_tables(event_id: int):
    """
    Inforadar-like history tables for one event.
    Query params:
      hours (default 6)
      limit (default 8000) - raw rows cap from DB
      half: ft | 1h
    """
    hours = safe_int(request.args.get("hours", 6), 6)
    limit = safe_int(request.args.get("limit", 8000), 8000)
    half = _fonbet_norm_half(request.args.get("half"))
    # Defaults for Fonbet eventView fetch (used for enrichment)
    lang = _env("FONBET_LANG", default="ru") or "ru"
    sys_id = int(_env("FONBET_SYS_ID", default="21") or "21")

    base_event_id = int(event_id)
    effective_event_id = base_event_id
    if half == "1h":
        # Fonbet часто использует отдельный event_id для рынков 1-го тайма
        effective_event_id = _fonbet_resolve_1h_event_id(base_event_id, lang=lang, sys_id=sys_id)


    try:
        with db_connect() as conn:
            with conn.cursor() as cur:
                ts_col = _fonbet_ts_col(cur)
                cond, params = _fonbet_ts_where(cur, ts_col, int(hours))
                ts_select = _fonbet_ts_select_expr(cur, ts_col)
                label_col = _fonbet_label_col(cur)
                label_select = f", {label_col} AS label" if label_col else ""
                param_col = _fonbet_param_col(cur)
                param_select = f", {param_col} AS param" if param_col else ""

                cur.execute(
                    f"""
                    SELECT factor_id, odd, {ts_select} AS ts{label_select}{param_select}
                    FROM fonbet_odds_history
                    WHERE event_id=%s AND {cond}
                    ORDER BY {ts_col} ASC
                    LIMIT %s
                    """,
                    [effective_event_id] + list(params) + [int(limit)],
                )
                rows = cur.fetchall() or []

        # Strict FT tables via eventView mapping (goals total + match asian handicap only)
        if (half in ("ft", "full", "")) and _HAS_FONBET_INFORADAR_MARKETS and build_market_map_from_eventview:
            try:
                ev_strict = _fonbet_fetch_event_view(lang=lang, sys_id=sys_id, event_id=event_id)
                mm = build_market_map_from_eventview(ev_strict, event_id)
                allowed = set(mm.get("allowed_factor_ids") or [])
                if allowed:
                    rows_strict = [r for r in (rows or []) if safe_int(r.get("factor_id") or 0, 0) in allowed]
                    
                    # Current snapshot from eventView (factorId -> odd)
                    vals = _fonbet_extract_factor_values(ev_strict) or {}
                    now_ts = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
                    
                    # Seed missing factorIds so 1X2/handicap don't stay empty when only totals changed in history
                    if not rows_strict:
                        seed_ts = now_ts
                    else:
                        seed_ts = rows_strict[0].get("ts") or now_ts
                        try:
                            seed_ts = _dt_to_str(seed_ts) or now_ts
                        except Exception:
                            seed_ts = str(seed_ts) if seed_ts else now_ts
                    
                    present = {safe_int(r.get("factor_id") or 0, 0) for r in (rows_strict or [])}
                    missing = []
                    for fid in allowed:
                        fid_i = safe_int(fid, 0)
                        if not fid_i or fid_i in present:
                            continue
                        odd = vals.get(fid_i)
                        if odd is None:
                            continue
                        missing.append({"ts": seed_ts, "factor_id": fid_i, "odd": odd})
                    
                    if missing:
                        rows_strict = list(rows_strict or []) + missing
                    elif not rows_strict:
                        # Nothing in history and nothing seeded -> keep empty
                        rows_strict = []
                    
                    data_strict = _fonbet_tables_from_rows_strict_inforadar(rows_strict, mm)
                    return jsonify(data_strict)
            except Exception:
                # fallback to legacy classifier below
                pass

        # Global catalog map
        fmap = fonbet_factor_catalog_map(force=False) or {}


        # Coverage diagnostics
        factor_ids = sorted({int(r.get("factor_id") or 0) for r in rows if int(r.get("factor_id") or 0) > 0})
        covered = sum(1 for fid in factor_ids if fid in fmap)
        coverage = (covered / max(1, len(factor_ids)))

        # EventView settings (used for mapping/enrichment)
        lang = _env("FONBET_LANG", default="ru") or "ru"
        sys_id = int(_env("FONBET_SYS_ID", default="21") or "21")

        # If coverage is poor OR we miss labels/params for handicap/total, try eventView fallback
        needs_ev = False
        if rows and (coverage < 0.30 or len(fmap) == 0):
            needs_ev = True

        # If some factor IDs have no label in the global catalog, eventView usually has it
        if rows and not needs_ev:
            for fid in factor_ids[:400]:
                info = fmap.get(fid) or {}
                if not str(info.get("label") or "").strip():
                    needs_ev = True
                    break

        if rows and not needs_ev:
            # if we have handicap/total markets but no param info, we can't build mainline tables
            for fid in factor_ids[:250]:
                info = fmap.get(fid) or {}
                lbl = str(info.get("label") or "")
                mkt = str(info.get("market") or "") or _fonbet_classify_market(lbl)
                has_param = info.get("param") not in (None, "", 0)
                if mkt in ("handicap", "total", "handicap_1h", "total_1h") and (not has_param) and (_fonbet_parse_line(lbl) is None):
                    needs_ev = True
                    break

        ev = None
        if needs_ev:
            ev = _fonbet_fetch_event_view(lang=lang, sys_id=sys_id, event_id=effective_event_id)
            if isinstance(ev, (dict, list)):
                ev_map = _fonbet_extract_factor_map(ev, only_event_id=effective_event_id, base_event_id=base_event_id, half=half) or {}
                if ev_map:
                    fmap = {**fmap, **ev_map}


        # event teams (for mapping outcome labels that come as team names)
        team1 = ""
        team2 = ""
        try:
            with mysql_cursor(dict=True) as cur:
                cur.execute("SELECT * FROM fonbet_events WHERE event_id=%s LIMIT 1", (base_event_id,))
                erow = cur.fetchone() or {}
                team1 = (erow.get("team1") or erow.get("home") or erow.get("h") or "").strip()
                team2 = (erow.get("team2") or erow.get("away") or erow.get("a") or "").strip()
        except Exception:
            team1 = ""
            team2 = ""

        half_rows = half
        if half == "1h" and effective_event_id != base_event_id:
            # если 1H хранится отдельным event_id, рынки могут быть без суффикса _1h -> не фильтруем их
            half_rows = "ft"
        data = _fonbet_tables_from_rows(rows, fmap, half=half_rows, team1=team1, team2=team2)


        # If some markets are missing/incomplete in history, try to enrich with *current* odds from eventView (single snapshot).
        def _need_outcomes(d: dict) -> bool:
            outs = d.get("outcomes") or []
            if not outs:
                return True
            has1 = any(r.get("1") not in (None, "") for r in outs)
            hasx = any(r.get("X") not in (None, "") for r in outs)
            has2 = any(r.get("2") not in (None, "") for r in outs)
            return (not has1) or (not hasx) or (not has2)

        def _need_handicap(d: dict) -> bool:
            h = d.get("handicap") or []
            if not h:
                return True
            has_home = any(r.get("Home") not in (None, "") for r in h)
            has_away = any(r.get("Away") not in (None, "") for r in h)
            has_hcp = any((r.get("Handicap") is not None) or (r.get("Hcp") is not None) for r in h)
            return (not has_home) or (not has_away) or (not has_hcp)

        def _need_total(d: dict) -> bool:
            t = d.get("total") or []
            if not t:
                return True
            has_over = any(r.get("Over") not in (None, "") for r in t)
            has_under = any(r.get("Under") not in (None, "") for r in t)
            has_line = any(r.get("Total") is not None for r in t)
            return (not has_over) or (not has_under) or (not has_line)

        need_out = _need_outcomes(data)
        need_hcp = _need_handicap(data)
        need_tot = _need_total(data)

        if need_out or need_hcp or need_tot:
            try:
                if ev is None:
                    ev = _fonbet_fetch_event_view(lang=lang, sys_id=sys_id, event_id=effective_event_id)

                # Merge per-event factor map (labels/params/markets) and rebuild using history rows
                if isinstance(ev, (dict, list)):
                    ev_map = _fonbet_extract_factor_map(ev, only_event_id=effective_event_id, base_event_id=base_event_id, half=half) or {}
                    if ev_map:
                        fmap = {**fmap, **ev_map}
                        data = _fonbet_tables_from_rows(rows, fmap, half=half, team1=team1, team2=team2)

                # Re-check after merging mapping
                need_out = _need_outcomes(data)
                need_hcp = _need_handicap(data)
                need_tot = _need_total(data)

                # Add a single "current" snapshot for missing parts
                vals = _fonbet_extract_factor_values(ev, only_event_id=effective_event_id, base_event_id=base_event_id, half=half) if isinstance(ev, (dict, list)) else {}
                if vals and (need_out or need_hcp or need_tot):
                    now_ts = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
                    extra_rows: List[dict] = []
                    t1n_local = _norm_team_name(team1 or "")
                    t2n_local = _norm_team_name(team2 or "")
                    for fid, odd in vals.items():
                        info = fmap.get(fid) or {}
                        lbl = str(info.get("label") or "")
                        mkt = str(info.get("market") or "") or _fonbet_classify_market(lbl)
                        nl = _norm_team_name(lbl)

                        oc_norm = _fonbet_norm_outcome(lbl) or _fonbet_norm_outcome(nl)
                        is_out = (
                            mkt.startswith("outcomes")
                            or (oc_norm in ("1", "X", "2"))
                            or (nl and (("нич" in nl) or nl in ("x","х","н","draw","d") or (t1n_local and t1n_local in nl) or (t2n_local and t2n_local in nl)))
                        )
                        is_hcp = (
                            ("handicap" in mkt)
                            or ("hcp" in nl)
                            or ("фора" in nl)
                            or (re.search(r"\bф[12]\b", nl) is not None)
                            or (re.search(r"\(([-+])\s*\d+(?:\.\d+)?\)", nl) is not None)
                            or (re.search(r"\((0(?:\.0+)?)\)", nl) is not None)
                        )
                        is_tot = ("total" in mkt) or ("тб" in nl) or ("тм" in nl) or ("over" in nl) or ("under" in nl)

                        if (need_out and is_out) or (need_hcp and is_hcp) or (need_tot and is_tot):
                            extra_rows.append({"ts": now_ts, "factor_id": fid, "odd": odd, "label": lbl})

                    if extra_rows:
                        data = _fonbet_tables_from_rows(rows + extra_rows, fmap, half=half, team1=team1, team2=team2)
            except Exception:
                pass

        data.setdefault("meta", {})
        data["meta"]["base_event_id"] = base_event_id
        data["meta"]["effective_event_id"] = effective_event_id
        data["meta"]["half"] = half
        data["meta"]["half_resolved"] = bool(effective_event_id != base_event_id)
        data["meta"]["factor_ids_total"] = len(factor_ids)
        data["meta"]["factor_ids_covered"] = sum(1 for fid in factor_ids if fid in (fmap or {}))
        data["meta"]["coverage"] = round((data["meta"]["factor_ids_covered"] / max(1, data["meta"]["factor_ids_total"])) * 100, 2)

        return jsonify(data)

    except Exception as e:
        return jsonify({"error": str(e), "meta": {"event_id": event_id}, "outcomes": [], "handicap": [], "total": []}), 500

@app.route("/fonbet")
def page_fonbet():
    # Inject ENV football sport_id so UI can default to football even if the id is not in top list for the current window
    env_sid = safe_int(os.environ.get("FONBET_FOOTBALL_SPORT_ID"), 0)
    html = FONBET_LIST_INLINE.replace("__ENV_FOOTBALL_SID__", str(env_sid))
    return render_template_string(html)

@app.route("/fonbet_event/<int:event_id>")
def page_fonbet_event(event_id: int):
    # server-side fetch event header
    event = {"event_id": event_id, "team1": "?", "team2": "?", "league_name": "-", "start_time": "-"}
    try:
        with db_connect() as conn:
            with conn.cursor() as cur:
                has_sport = _table_has_col(cur, "fonbet_events", "sport_id")
                select_sport = ", sport_id" if has_sport else ""
                cur.execute(
                    f"SELECT event_id, league_name, team1, team2{select_sport}, "
                    "CASE WHEN start_ts > 2000000000 THEN FROM_UNIXTIME(FLOOR(start_ts/1000)) "
                    "ELSE FROM_UNIXTIME(start_ts) END AS start_time "
                    "FROM fonbet_events WHERE event_id=%s",
                    (event_id,),
                )
                event = cur.fetchone() or event
    except Exception:
        pass

        # Always use inline event UI to ensure FT/HT + 3 tables on one page
    return render_template_string(FONBET_EVENT_INLINE, event=event)


if __name__ == "__main__":
    print("=" * 70)
    print("Inforadar Pro - Prematch UI")
    print("→ http://localhost:5000/prematch (22BET)")
    print("→ http://localhost:5000/prematch (22BET)_simple (always works, for debug)")
    print("=" * 70)
    app.run(host="0.0.0.0", port=5000, debug=True)
