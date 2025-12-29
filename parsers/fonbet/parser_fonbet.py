from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pymysql

from inforadar_parser.utils.proxy import build_proxy_url
from inforadar_parser.parsers.fonbet.fonbet_client import FonbetClient, FonbetConfig

BOOKMAKER = (os.getenv("FONBET_BOOKMAKER", "fonbet") or "fonbet").strip()
SPORT = (os.getenv("FONBET_SPORT", "football") or "football").strip()
IS_LIVE = int(os.getenv("FONBET_LIVE", "0") or "0")
INTERVAL_SEC = int(os.getenv("FONBET_INTERVAL_SEC", "10") or "10")

ENDPOINT_EVENTS = (os.getenv("FONBET_ENDPOINT_EVENTS", "") or "").strip()
ENDPOINT_EVENT_VIEW = (os.getenv("FONBET_ENDPOINT_EVENT_VIEW", "") or "").strip()
EVENT_ID_PARAM = (os.getenv("FONBET_EVENT_ID_PARAM", "eventId") or "eventId").strip()

PROXY_URL = build_proxy_url("FONBET")

def _load_endpoints_from_file() -> None:
    global ENDPOINT_EVENTS, ENDPOINT_EVENT_VIEW
    if ENDPOINT_EVENTS and ENDPOINT_EVENT_VIEW:
        return
    p = Path(__file__).with_name("endpoints.json")
    if not p.exists():
        return
    data = json.loads(p.read_text(encoding="utf-8"))
    ENDPOINT_EVENTS = ENDPOINT_EVENTS or (data.get("events") or "").strip()
    ENDPOINT_EVENT_VIEW = ENDPOINT_EVENT_VIEW or (data.get("event_view") or "").strip()

_load_endpoints_from_file()

def db():
    return pymysql.connect(
        host=os.getenv("MYSQL_HOST", "localhost"),
        user=os.getenv("MYSQL_USER", "root"),
        password=os.getenv("MYSQL_PASSWORD", ""),
        database=os.getenv("MYSQL_DB", "inforadar"),
        autocommit=True,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )

def upsert_match(cur, bookmaker: str, event_id: str, sport: str, league: str, team1: str, team2: str, start_ts: int, is_live: int):
    cur.execute(
        """
        INSERT INTO matches (bookmaker, event_id, sport, league, team1, team2, start_time, is_live, updated_at)
        VALUES (%s,%s,%s,%s,%s,%s,FROM_UNIXTIME(%s),%s,NOW())
        ON DUPLICATE KEY UPDATE
            league=VALUES(league),
            team1=VALUES(team1),
            team2=VALUES(team2),
            start_time=VALUES(start_time),
            is_live=VALUES(is_live),
            updated_at=NOW()
        """,
        (bookmaker, event_id, sport, league, team1, team2, start_ts, is_live),
    )

def upsert_odds(cur, bookmaker: str, event_id: str, market_key: str, outcome_key: str, odd: float, limit_val: Optional[float]):
    cur.execute(
        """
        INSERT INTO odds (bookmaker, event_id, market_key, outcome_key, odd, limit_value, updated_at)
        VALUES (%s,%s,%s,%s,%s,%s,NOW())
        ON DUPLICATE KEY UPDATE
            odd=VALUES(odd),
            limit_value=VALUES(limit_value),
            updated_at=NOW()
        """,
        (bookmaker, event_id, market_key, outcome_key, odd, limit_val),
    )
    cur.execute(
        """
        INSERT INTO odds_history (bookmaker, event_id, market_key, outcome_key, odd, limit_value, ts)
        VALUES (%s,%s,%s,%s,%s,%s,NOW())
        """,
        (bookmaker, event_id, market_key, outcome_key, odd, limit_val),
    )

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

        out.append({
            "event_id": str(eid),
            "sport": SPORT,
            "league": str(league) if league is not None else "",
            "team1": str(team1) if team1 is not None else "",
            "team2": str(team2) if team2 is not None else "",
            "start_ts": start_ts,
            "is_live": live_val,
        })
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

def run_loop(client: FonbetClient, interval_sec: int):
    if not ENDPOINT_EVENTS or not ENDPOINT_EVENT_VIEW:
        raise RuntimeError(
            "Fonbet endpoints are not set.\n"
            "Set env FONBET_ENDPOINT_EVENTS and FONBET_ENDPOINT_EVENT_VIEW,\n"
            "or edit endpoints.json next to parser_fonbet.py"
        )

    while True:
        started = time.time()
        try:
            events_json = client.get_json(ENDPOINT_EVENTS)
            events = parse_events(events_json)

            with db() as conn, conn.cursor() as cur:
                for ev in events:
                    upsert_match(cur, BOOKMAKER, ev["event_id"], ev["sport"], ev["league"], ev["team1"], ev["team2"], ev["start_ts"], ev["is_live"])
                    params = {EVENT_ID_PARAM: ev["event_id"]}
                    event_view_json = client.get_json(ENDPOINT_EVENT_VIEW, params=params)
                    outcomes = parse_markets(event_view_json)
                    for o in outcomes:
                        upsert_odds(cur, BOOKMAKER, ev["event_id"], o["market_key"], o["outcome_key"], o["odd"], o["limit"])

            print(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}] fonbet ok: events={len(events)}")

        except Exception as e:
            print(f"[fonbet] ERROR: {e}")

        time.sleep(max(0.0, interval_sec - (time.time() - started)))

def main():
    cfg = FonbetConfig(base_headers=FonbetClient.default_headers(), cookies={})
    with FonbetClient(cfg, proxy_url=PROXY_URL) as client:
        run_loop(client, interval_sec=INTERVAL_SEC)

if __name__ == "__main__":
    main()
