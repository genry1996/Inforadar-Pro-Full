from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import pymysql

from inforadar_parser.utils.proxy import build_proxy_url
from inforadar_parser.parsers.fonbet.fonbet_client import FonbetClient, FonbetConfig

# ==========================================================
# Fonbet parser (safe defaults + DB port + endpoint fallback)
# ==========================================================
#
# Goals of this version:
# - Do NOT crash if endpoints are wrapped in quotes in .env
# - Support both styles of endpoints:
#   * https://.../line/eventView  (params are passed separately)
#   * https://.../line/eventView?eventId=  (eventId appended)
# - Read MYSQL_PORT from env (your .env uses 3307)
# - Avoid breaking legacy schemas: try to write into either
#   (matches/odds/odds_history) OR (fonbet_matches/fonbet_odds/fonbet_odds_history)
# - If DB is down, keep loop alive and print a clear error.


def _strip_quotes(s: str) -> str:
    s = (s or "").strip()
    if len(s) >= 2 and ((s[0] == s[-1] == '"') or (s[0] == s[-1] == "'")):
        return s[1:-1].strip()
    return s


BOOKMAKER = _strip_quotes(os.getenv("FONBET_BOOKMAKER", "fonbet") or "fonbet")
SPORT = _strip_quotes(os.getenv("FONBET_SPORT", "football") or "football")
IS_LIVE = int(os.getenv("FONBET_LIVE", "0") or "0")
INTERVAL_SEC = float(os.getenv("FONBET_INTERVAL_SEC", "10") or "10")

ENDPOINT_EVENTS = _strip_quotes(os.getenv("FONBET_ENDPOINT_EVENTS", "") or "")
ENDPOINT_EVENT_VIEW = _strip_quotes(os.getenv("FONBET_ENDPOINT_EVENT_VIEW", "") or "")
EVENT_ID_PARAM = _strip_quotes(os.getenv("FONBET_EVENT_ID_PARAM", "eventId") or "eventId")

FONBET_NO_DB = int(os.getenv("FONBET_NO_DB", "0") or "0")

PROXY_URL = build_proxy_url("FONBET")


def _derive_base(url: str) -> str:
    """Return scheme://host from URL, or empty string."""
    url = (url or "").strip()
    if not url:
        return ""
    try:
        u = urlparse(url)
        if u.scheme and u.netloc:
            return f"{u.scheme}://{u.netloc}"
    except Exception:
        return ""
    return ""


def _load_endpoints_from_file() -> Tuple[str, str]:
    """Optional endpoints.json near this file: {"events":..., "event_view":...}"""
    p = Path(__file__).with_name("endpoints.json")
    if not p.exists():
        return "", ""
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        ev = _strip_quotes(str(data.get("events") or ""))
        vw = _strip_quotes(str(data.get("event_view") or ""))
        return ev, vw
    except Exception:
        return "", ""


def _ensure_endpoints() -> Tuple[str, str]:
    """Resolve endpoints from env -> endpoints.json -> base default."""
    global ENDPOINT_EVENTS, ENDPOINT_EVENT_VIEW

    if ENDPOINT_EVENTS and ENDPOINT_EVENT_VIEW:
        return ENDPOINT_EVENTS, ENDPOINT_EVENT_VIEW

    fe, fv = _load_endpoints_from_file()
    ENDPOINT_EVENTS = ENDPOINT_EVENTS or fe
    ENDPOINT_EVENT_VIEW = ENDPOINT_EVENT_VIEW or fv

    if ENDPOINT_EVENTS and ENDPOINT_EVENT_VIEW:
        return ENDPOINT_EVENTS, ENDPOINT_EVENT_VIEW

    # Fallback: derive base either from target url or env base
    target = _strip_quotes(os.getenv("FONBET_TARGET_URL", "") or "")
    base = _strip_quotes(os.getenv("FONBET_API_BASE", "") or "")
    base = base or _derive_base(ENDPOINT_EVENTS) or _derive_base(ENDPOINT_EVENT_VIEW) or _derive_base(target) or "https://fonbet.com.cy"

    ENDPOINT_EVENTS = f"{base}/line/listBase"
    ENDPOINT_EVENT_VIEW = f"{base}/line/eventView"
    return ENDPOINT_EVENTS, ENDPOINT_EVENT_VIEW


def db_connect() -> Optional[pymysql.connections.Connection]:
    if FONBET_NO_DB:
        return None

    host = os.getenv("MYSQL_HOST", "127.0.0.1")
    user = os.getenv("MYSQL_USER", "root")
    password = os.getenv("MYSQL_PASSWORD", "")
    database = os.getenv("MYSQL_DB", "inforadar")
    port = int(os.getenv("MYSQL_PORT", "3306") or "3306")

    try:
        return pymysql.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
            autocommit=True,
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
            connect_timeout=5,
            read_timeout=10,
            write_timeout=10,
        )
    except Exception as e:
        # Keep parser alive; DB might be temporarily down
        print(f"[db] ERROR: can't connect to MySQL at {host}:{port} db={database} user={user} -> {e}")
        return None


def _first_list(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if not isinstance(payload, dict):
        return []

    for k in ("events", "event", "matches", "items", "data", "list"):
        v = payload.get(k)
        if isinstance(v, list):
            return [x for x in v if isinstance(x, dict)]

    for v in payload.values():
        if isinstance(v, dict):
            for k in ("events", "matches", "items", "data", "list"):
                vv = v.get(k)
                if isinstance(vv, list):
                    return [x for x in vv if isinstance(x, dict)]
    return []


def parse_events(payload: Any) -> List[Dict[str, Any]]:
    rows = _first_list(payload)

    def pick(d: dict, keys: List[str], default=None):
        for k in keys:
            if k in d and d[k] is not None:
                return d[k]
        return default

    out: List[Dict[str, Any]] = []

    for e in rows:
        eid = pick(e, ["id", "eventId", "event_id", "matchId", "match_id"])
        if eid is None:
            continue

        team1 = pick(e, ["team1", "home", "homeTeam", "teamHome", "player1", "p1"], "")
        team2 = pick(e, ["team2", "away", "awayTeam", "teamAway", "player2", "p2"], "")
        league = pick(e, ["league", "leagueName", "tournament", "competition", "category"], "")

        start_ts = pick(e, ["startTime", "start_time", "startTs", "start_ts", "start", "kickoff", "kickoffTime"], 0)
        try:
            start_ts = int(start_ts) if start_ts else 0
        except Exception:
            start_ts = 0

        live_val = pick(e, ["live", "isLive", "inplay", "is_live"], IS_LIVE)
        try:
            live_val = int(bool(live_val))
        except Exception:
            live_val = IS_LIVE

        out.append(
            {
                "event_id": str(eid),
                "sport": SPORT,
                "league": str(league) if league is not None else "",
                "team1": str(team1) if team1 is not None else "",
                "team2": str(team2) if team2 is not None else "",
                "start_ts": start_ts,
                "is_live": live_val,
            }
        )

    return out


def parse_markets(event_view_payload: Any) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []

    if not isinstance(event_view_payload, dict):
        return out

    markets = event_view_payload.get("markets")
    if not isinstance(markets, list):
        markets = event_view_payload.get("data") if isinstance(event_view_payload.get("data"), list) else []

    for m in markets or []:
        if not isinstance(m, dict):
            continue
        mk = m.get("key") or m.get("name") or str(m.get("id") or "")
        outcomes = m.get("outcomes") or m.get("results") or []
        if not isinstance(outcomes, list):
            continue

        for o in outcomes:
            if not isinstance(o, dict):
                continue
            ok = o.get("key") or o.get("name") or str(o.get("id") or "")
            odd = o.get("odd") or o.get("price") or o.get("coef")
            if odd is None:
                continue
            try:
                odd_val = float(odd)
            except Exception:
                continue

            lim = o.get("limit") or o.get("maxStake") or o.get("max_stake")
            try:
                lim_val = float(lim) if lim is not None else None
            except Exception:
                lim_val = None

            out.append({"market_key": mk, "outcome_key": ok, "odd": odd_val, "limit": lim_val})

    return out


def _sql_try(cur, sql: str, params: tuple) -> bool:
    try:
        cur.execute(sql, params)
        return True
    except Exception:
        return False


def upsert_match(cur, bookmaker: str, event_id: str, sport: str, league: str, team1: str, team2: str, start_ts: int, is_live: int) -> None:
    """Write match into one of known schemas."""

    # Schema A: matches (with bookmaker)
    sql_a = (
        "INSERT INTO matches (bookmaker, event_id, sport, league, team1, team2, start_time, is_live, updated_at) "
        "VALUES (%s,%s,%s,%s,%s,%s,FROM_UNIXTIME(%s),%s,NOW()) "
        "ON DUPLICATE KEY UPDATE league=VALUES(league), team1=VALUES(team1), team2=VALUES(team2), start_time=VALUES(start_time), is_live=VALUES(is_live), updated_at=NOW()"
    )
    if _sql_try(cur, sql_a, (bookmaker, event_id, sport, league, team1, team2, start_ts, is_live)):
        return

    # Schema B: fonbet_matches (without bookmaker)
    sql_b = (
        "INSERT INTO fonbet_matches (event_id, sport, league, team1, team2, start_time, is_live, updated_at) "
        "VALUES (%s,%s,%s,%s,%s,FROM_UNIXTIME(%s),%s,NOW()) "
        "ON DUPLICATE KEY UPDATE league=VALUES(league), team1=VALUES(team1), team2=VALUES(team2), start_time=VALUES(start_time), is_live=VALUES(is_live), updated_at=NOW()"
    )
    _sql_try(cur, sql_b, (event_id, sport, league, team1, team2, start_ts, is_live))


def upsert_odds(cur, bookmaker: str, event_id: str, market_key: str, outcome_key: str, odd: float, limit_val: Optional[float]) -> None:
    """Write odds into one of known schemas."""

    # Schema A: odds + odds_history (with bookmaker)
    sql_a1 = (
        "INSERT INTO odds (bookmaker, event_id, market_key, outcome_key, odd, limit_value, updated_at) "
        "VALUES (%s,%s,%s,%s,%s,%s,NOW()) "
        "ON DUPLICATE KEY UPDATE odd=VALUES(odd), limit_value=VALUES(limit_value), updated_at=NOW()"
    )
    sql_a2 = (
        "INSERT INTO odds_history (bookmaker, event_id, market_key, outcome_key, odd, limit_value, ts) "
        "VALUES (%s,%s,%s,%s,%s,%s,NOW())"
    )

    if _sql_try(cur, sql_a1, (bookmaker, event_id, market_key, outcome_key, odd, limit_val)):
        _sql_try(cur, sql_a2, (bookmaker, event_id, market_key, outcome_key, odd, limit_val))
        return

    # Schema B: fonbet_odds + fonbet_odds_history (without bookmaker)
    sql_b1 = (
        "INSERT INTO fonbet_odds (event_id, market_key, outcome_key, odd, limit_value, updated_at) "
        "VALUES (%s,%s,%s,%s,%s,NOW()) "
        "ON DUPLICATE KEY UPDATE odd=VALUES(odd), limit_value=VALUES(limit_value), updated_at=NOW()"
    )
    sql_b2 = (
        "INSERT INTO fonbet_odds_history (event_id, market_key, outcome_key, odd, limit_value, ts) "
        "VALUES (%s,%s,%s,%s,%s,NOW())"
    )

    if _sql_try(cur, sql_b1, (event_id, market_key, outcome_key, odd, limit_val)):
        _sql_try(cur, sql_b2, (event_id, market_key, outcome_key, odd, limit_val))


def _build_event_view_call(event_id: str) -> Tuple[str, Optional[Dict[str, Any]]]:
    """Support both URL styles.

    If ENDPOINT_EVENT_VIEW ends with 'eventId=' or just '=' -> append event_id.
    Else pass params={EVENT_ID_PARAM: event_id}.
    """
    ev_url = ENDPOINT_EVENT_VIEW

    if not ev_url:
        return ev_url, None

    # common case in your .env: .../eventView?eventId=
    if ev_url.endswith("="):
        return f"{ev_url}{event_id}", None

    # If already has ?eventId=... somewhere and ends with that value missing
    if ("eventId=" in ev_url or f"{EVENT_ID_PARAM}=" in ev_url) and ev_url.rstrip().endswith(("eventId=", f"{EVENT_ID_PARAM}=")):
        return f"{ev_url}{event_id}", None

    return ev_url, {EVENT_ID_PARAM: event_id}


def run_loop(client: FonbetClient, interval_sec: float) -> None:
    _ensure_endpoints()

    if not ENDPOINT_EVENTS or not ENDPOINT_EVENT_VIEW:
        raise RuntimeError(
            "Fonbet endpoints are not set.\n"
            "Set env FONBET_ENDPOINT_EVENTS and FONBET_ENDPOINT_EVENT_VIEW,\n"
            "or create endpoints.json next to parser_fonbet.py"
        )

    print(
        f"[fonbet] endpoints: events={ENDPOINT_EVENTS} | eventView={ENDPOINT_EVENT_VIEW} | proxy={'yes' if PROXY_URL else 'no'}"
    )

    while True:
        started = time.time()

        try:
            events_json = client.get_json(ENDPOINT_EVENTS)
            events = parse_events(events_json)

            conn = db_connect()
            if conn is None:
                # No DB right now: just show that parsing works
                print(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}] fonbet ok (no-db): events={len(events)}")
            else:
                with conn:
                    with conn.cursor() as cur:
                        for ev in events:
                            upsert_match(
                                cur,
                                BOOKMAKER,
                                ev["event_id"],
                                ev["sport"],
                                ev["league"],
                                ev["team1"],
                                ev["team2"],
                                ev["start_ts"],
                                ev["is_live"],
                            )

                            ev_url, params = _build_event_view_call(ev["event_id"])
                            event_view_json = client.get_json(ev_url, params=params)

                            outcomes = parse_markets(event_view_json)
                            for o in outcomes:
                                upsert_odds(
                                    cur,
                                    BOOKMAKER,
                                    ev["event_id"],
                                    o["market_key"],
                                    o["outcome_key"],
                                    o["odd"],
                                    o["limit"],
                                )

                print(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}] fonbet ok: events={len(events)}")

        except Exception as e:
            print(f"[fonbet] ERROR: {e}")

        time.sleep(max(0.0, float(interval_sec) - (time.time() - started)))


def main() -> None:
    cfg = FonbetConfig(base_headers=FonbetClient.default_headers(), cookies={})
    with FonbetClient(cfg, proxy_url=PROXY_URL) as client:
        run_loop(client, interval_sec=INTERVAL_SEC)


if __name__ == "__main__":
    main()
