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

import pymysql
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

def _is_special_row(r: Dict[str, Any]) -> bool:
    eid = r.get("event_id")
    if eid is None:
        return True
    h = str(r.get("home_team") or "").strip().lower()
    a = str(r.get("away_team") or "").strip().lower()
    if not h or not a:
        return True
    if h in _GENERIC_TEAMS or a in _GENERIC_TEAMS:
        return True
    if re.fullmatch(r"\d{3,}", h) or re.fullmatch(r"\d{3,}", a):
        return True
    league = str(r.get("league") or "").lower()
    name = str(r.get("event_name") or "").lower()
    blob = " ".join([league, name, h, a])
    return any(ss in blob for ss in _SPECIAL_ROW_SUBSTRINGS)


# ------------------------------
# Env loading (python-dotenv if available, fallback otherwise)
# ------------------------------

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
        return int(x)
    except Exception:
        return default


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
    sport_id = safe_int(request.args.get("sport_id", 0), 0)  # 0 = no filter

    with db_connect() as conn:
        with conn.cursor() as cur:
            rows = _sql_fonbet_events(cur, hours=hours, q=q, limit=limit, sport_id=sport_id)

    items = []
    for r in rows or []:
        items.append({
            "event_id": r.get("event_id"),
            "league_name": r.get("league_name") or "",
            "team1": r.get("team1") or "",
            "team2": r.get("team2") or "",
            "start_time": str(r.get("start_time") or ""),
            "drops": int(r.get("drops") or 0),
            "max_drop": r.get("max_drop"),
        })
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
                cur.execute(q, (sport, limit))
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
                _FONBET_TS_COL_CACHE = c
                return c
    except Exception:
        pass
    _FONBET_TS_COL_CACHE = "ts"
    return _FONBET_TS_COL_CACHE


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
let timer=null;

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

  const sportIdInput = ($('sportId')?.value || localStorage.getItem('fonbet_sport_id') || '').toString().trim();
  const sportId = sportIdInput ? Number(sportIdInput) : 0;
  let url = `/api/fonbet/events?hours=${encodeURIComponent(hours)}&limit=${encodeURIComponent(limit)}&q=${encodeURIComponent(q)}`;
  if (sportId && sportId > 0) url += `&sport_id=${encodeURIComponent(String(sportId))}`;
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

$("btn").addEventListener("click", ()=>{ load(); startTimer(); });
$("btnNow").addEventListener("click", ()=>{
  $("q").value=""; $("hours").value=12; $("limit").value=200; $("refresh").value=10;
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
    .topbar{position:sticky;top:0;z-index:10;background:rgba(255,255,255,.85);backdrop-filter:blur(10px);border-bottom:1px solid var(--border);}
    .topbar-inner{max-width:1200px;margin:0 auto;padding:12px 16px;display:flex;align-items:center;justify-content:space-between;gap:12px;}
    .brand{display:flex;align-items:center;gap:10px;font-weight:900;letter-spacing:.2px;}
    .dot{width:12px;height:12px;border-radius:50%;background:var(--brand);box-shadow:0 0 0 6px rgba(43,108,255,.14);}
    .nav{display:flex;gap:10px;align-items:center;font-size:13px;}
    .nav a{color:var(--muted);text-decoration:none;padding:6px 10px;border-radius:999px;border:1px solid transparent}
    .nav a:hover{border-color:var(--border);background:#fff}
    .nav a.active{color:var(--brand);border-color:#d6e4ff;background:#f1f4ff;font-weight:700}
    .wrap{max-width:1200px;margin:0 auto;padding:18px 16px;}
    .card{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);box-shadow:var(--shadow);margin-bottom:14px;}
    .card-h{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:14px 16px;border-bottom:1px solid var(--border);}
    .card-h h1{margin:0;font-size:18px}
    .meta{font-size:12px;color:var(--muted);margin-top:2px}
    .controls{display:flex;gap:10px;flex-wrap:wrap;align-items:end}
    label{font-size:12px;color:var(--muted);display:block;margin:0 0 6px}
    input{height:34px;border:1px solid var(--border);border-radius:10px;padding:0 10px;font-size:13px;outline:none;background:#fff}
    .btn{height:34px;border-radius:10px;border:1px solid #c2d4ff;background:var(--brand);color:#fff;padding:0 12px;font-weight:700;cursor:pointer}
    .btn.secondary{background:#fff;color:var(--brand)}
    .table-wrap{overflow:auto}
    table{width:100%;border-collapse:collapse;font-size:13px}
    th,td{padding:10px 12px;border-bottom:1px solid var(--border);vertical-align:middle}
    th{background:#fff;text-align:left;font-size:12px;color:var(--muted);font-weight:700}
    .mono{font-family:var(--mono)}
    .badge{display:inline-flex;align-items:center;gap:6px;padding:2px 10px;border-radius:999px;font-size:12px;border:1px solid var(--border);background:#fff}
    .badge.bad{border-color:#ffd3d0;background:#fff5f5;color:#b42318}
    .badge.good{border-color:#b7f0cd;background:#ecfdf3;color:#027a48}
    .grid{display:grid;grid-template-columns:1fr;gap:14px;padding:12px 16px}
    @media(min-width:980px){ .grid{grid-template-columns:1fr 1fr 1fr;} }
    .small{font-size:12px;color:var(--muted)}
    .delta.bad{color:#b42318;font-weight:800}
    .delta.good{color:#027a48;font-weight:800}
  </style>
</head>
<body>
  <div class="topbar">
    <div class="topbar-inner">
      <div class="brand"><span class="dot"></span> INFORADAR <span class="badge good">FONBET · event</span></div>
      <div class="nav">
        <a href="/22bet">22BET</a>
        <a class="active" href="/fonbet">Fonbet</a>
        <a href="/betwatch">Betwatch</a>
      </div>
    </div>
  </div>

  <div class="wrap">
    <div class="card">
      <div class="card-h" style="border-bottom:none">
        <div>
          <h1 id="title">{{ event.team1 }} — {{ event.team2 }}</h1>
          <div class="meta">
            <span class="mono">start:</span> <span class="mono">{{ event.start_time }}</span>
            &nbsp;·&nbsp; <span class="mono">event_id:</span> <span class="mono">{{ event.event_id }}</span>
            &nbsp;·&nbsp; <span class="mono">league:</span> {{ event.league_name or "-" }}
          </div>
        </div>
        <div class="controls">
          <div>
            <label>Hours history</label>
            <input id="hours" type="number" min="1" max="48" value="6"/>
          </div>
          <div>
            <label>Limit factors</label>
            <input id="limit" type="number" min="50" max="5000" value="1500"/>
          </div>
          <div>
            <label>Refresh (sec)</label>
            <input id="refresh" type="number" min="3" max="60" value="10"/>
          </div>
          <button class="btn" id="btn">Refresh</button>
          <a class="btn secondary" href="/fonbet">← Back</a>
          <span class="badge" id="status">—</span>
        </div>
      </div>

      <div class="grid">
        <div class="card" style="margin:0">
          <div class="card-h"><b>1X2 / Исходы</b><span class="small">latest vs prev</span></div>
          <div class="table-wrap">
            <table>
              <thead><tr><th>Bet</th><th class="mono">Odd</th><th class="mono">Prev</th><th class="mono">Δ</th></tr></thead>
              <tbody id="outcomes"><tr><td colspan="4" class="small">Loading…</td></tr></tbody>
            </table>
          </div>
        </div>
        <div class="card" style="margin:0">
          <div class="card-h"><b>Handicap / Фора</b><span class="small">latest vs prev</span></div>
          <div class="table-wrap">
            <table>
              <thead><tr><th>Bet</th><th class="mono">Odd</th><th class="mono">Prev</th><th class="mono">Δ</th></tr></thead>
              <tbody id="handicap"><tr><td colspan="4" class="small">Loading…</td></tr></tbody>
            </table>
          </div>
        </div>
        <div class="card" style="margin:0">
          <div class="card-h"><b>Total / Тотал</b><span class="small">latest vs prev</span></div>
          <div class="table-wrap">
            <table>
              <thead><tr><th>Bet</th><th class="mono">Odd</th><th class="mono">Prev</th><th class="mono">Δ</th></tr></thead>
              <tbody id="total"><tr><td colspan="4" class="small">Loading…</td></tr></tbody>
            </table>
          </div>
        </div>
      </div>

      <div style="padding:0 16px 14px">
        <div class="card" style="margin:0">
          <div class="card-h"><b>Other factors</b><span class="small">если фактор не распознан как исход/фора/тотал</span></div>
          <div class="table-wrap" style="max-height:42vh">
            <table>
              <thead><tr><th>Factor</th><th class="mono">Odd</th><th class="mono">Prev</th><th class="mono">Δ</th><th class="mono">ts</th></tr></thead>
              <tbody id="other"><tr><td colspan="5" class="small">Loading…</td></tr></tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  </div>

<script>
const $ = (id)=>document.getElementById(id);
let timer=null;

function cellDelta(v){
  if(v===null||v===undefined||v==="") return `<span class="mono">—</span>`;
  const n=Number(v);
  if(!isFinite(n)) return `<span class="mono">—</span>`;
  const cls = n<0 ? "bad" : "good";
  const sign = n<0 ? "" : "+";
  return `<span class="mono delta ${cls}">${sign}${n.toFixed(3)}</span>`;
}
function cellOdd(v){
  if(v===null||v===undefined||v==="") return `<span class="mono">—</span>`;
  const n=Number(v);
  if(!isFinite(n)) return `<span class="mono">—</span>`;
  return `<span class="mono">${n.toFixed(3)}</span>`;
}
function fmtTs(s){ return (s||"-").replace("T"," ").slice(0,19); }

async function load(){
  const hours = Number($("hours").value||6);
  const limit = Number($("limit").value||1500);
  const url = `/api/fonbet/event/{{ event.event_id }}?hours=${encodeURIComponent(hours)}&limit=${encodeURIComponent(limit)}`;
  const t0=performance.now();
  try{
    $("status").textContent="loading…";
    const res=await fetch(url,{cache:"no-store"});
    const js=await res.json();
    const ms=Math.round(performance.now()-t0);
    $("status").textContent=`factors: ${js.count} · catalog: ${js.catalog_count||0} · ${ms}ms`;

    // update title if server has better data
    if(js.event && js.event.team1 && js.event.team2){
      $("title").textContent = `${js.event.team1} — ${js.event.team2}`;
    }

    function fill(tbodyId, arr, showTs=false){
      const tbody=$(tbodyId);
      if(!arr || !arr.length){
        tbody.innerHTML = `<tr><td colspan="${showTs?5:4}" class="small">No data</td></tr>`;
        return;
      }
      tbody.innerHTML = arr.map(r=>{
        const label = r.label || (`factor ${r.factor_id}`);
        const tds = showTs
          ? `<td>${label}</td><td>${cellOdd(r.odd)}</td><td>${cellOdd(r.prev_odd)}</td><td>${cellDelta(r.delta)}</td><td class="mono">${fmtTs(r.ts)}</td>`
          : `<td>${label}</td><td>${cellOdd(r.odd)}</td><td>${cellOdd(r.prev_odd)}</td><td>${cellDelta(r.delta)}</td>`;
        return `<tr>${tds}</tr>`;
      }).join("");
    }

    fill("outcomes", js.markets.outcomes, false);
    fill("handicap", js.markets.handicap, false);
    fill("total", js.markets.total, false);
    fill("other", js.markets.other, true);
  }catch(err){
    $("status").textContent="error";
    $("other").innerHTML = `<tr><td colspan="5"><pre class="small">${String(err)}</pre></td></tr>`;
  }
}

function stopTimer(){ if(timer){clearInterval(timer);timer=null;} }
function startTimer(){
  stopTimer();
  const sec = Math.max(3, Math.min(60, Number($("refresh").value||10)));
  timer=setInterval(load, sec*1000);
}

$("btn").addEventListener("click", ()=>{ load(); startTimer(); });
load(); startTimer();
</script>
</body>
</html>
"""



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


def _fonbet_classify_market(text: str) -> str:
    t = (text or "").lower()
    if any(x in t for x in ("тотал", "total", "over", "under", "тб", "тм")):
        return "total"
    if any(x in t for x in ("фора", "handicap", "asian", "ah")):
        return "handicap"
    if any(x in t for x in ("исход", "1x2", "результ", "п1", "п2", "нич", "draw", "win")):
        return "outcomes"
    return "other"


def _fonbet_extract_factor_map(obj: Any) -> Dict[int, Dict[str, str]]:
    """
    Recursively walk factorsCatalog/eventViewTables JSON and try to extract factorId->label + market.
    This is heuristic by design (structure may change).
    """
    out: Dict[int, Dict[str, str]] = {}

    def pick_label(d: dict) -> Optional[str]:
        for k in ("shortTitle", "caption", "title", "name", "text", "label", "t", "st", "n", "c"):
            v = d.get(k)
            if isinstance(v, str) and 0 < len(v) <= 64:
                return v.strip()
        return None

    def pick_param(d: dict) -> Optional[str]:
        for k in ("param", "p", "line", "value"):
            v = d.get(k)
            if isinstance(v, (int, float)) and -1000 < float(v) < 1000:
                # avoid ids
                if abs(float(v)) < 200:
                    return str(v)
            if isinstance(v, str) and len(v) <= 16:
                try:
                    float(v.replace(",", "."))
                    return v
                except Exception:
                    continue
        return None

    def walk(node: Any, ctx: List[str]) -> None:
        if isinstance(node, dict):
            # update ctx with meaningful titles
            ctx2 = ctx
            for k in ("sectionTitle", "groupTitle", "tableTitle", "title", "name"):
                v = node.get(k)
                if isinstance(v, str) and 0 < len(v) <= 80:
                    vv = v.strip()
                    if any(x in vv.lower() for x in ("тотал", "фора", "исход", "1x2", "handicap", "total", "результ")):
                        ctx2 = ctx + [vv]
                        break

            # possible factorId keys
            for key in ("factorId", "factor_id", "factorID", "idFactor", "f"):
                fid = node.get(key)
                try:
                    fid_int = int(fid)
                except Exception:
                    fid_int = None
                if fid_int and fid_int > 0:
                    label = pick_label(node) or f"factor {fid_int}"
                    param = pick_param(node)
                    if param and param not in label:
                        # "ТБ" / "ТМ" and others
                        label = f"{label} {param}"
                    market = _fonbet_classify_market(" | ".join(ctx2 + [label]))
                    out.setdefault(fid_int, {"label": label, "market": market})
                    break

            for v in node.values():
                walk(v, ctx2)

        elif isinstance(node, list):
            for it in node:
                walk(it, ctx)

    walk(obj, [])
    return out


def fonbet_factor_catalog_map(force: bool = False) -> Dict[int, Dict[str, str]]:
    """
    Cache factor mapping for football view tables (sysId=21 by default).
    """
    now = time.time()
    if (not force) and _FONBET_CATALOG_CACHE["map"] and (now - _FONBET_CATALOG_CACHE["ts"] < _FONBET_CATALOG_TTL_SEC):
        return _FONBET_CATALOG_CACHE["map"] or {}

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
    IMPORTANT: do NOT over-filter here (fonbet data often has league_name='-' or state='prematch').
    """
    has_sport = _table_has_col(cur, "fonbet_events", "sport_id")

    where = [
        "e.start_ts IS NOT NULL",
        "CASE WHEN e.start_ts > 2000000000 THEN FLOOR(e.start_ts/1000) ELSE e.start_ts END >= UNIX_TIMESTAMP(NOW())",
        "CASE WHEN e.start_ts > 2000000000 THEN FLOOR(e.start_ts/1000) ELSE e.start_ts END <= UNIX_TIMESTAMP(NOW()) + %s",
        # keep team placeholders (like '?') - we can hide them in UI later
        "e.team1 IS NOT NULL AND e.team1 <> '' AND e.team1 <> '?'",
        "e.team2 IS NOT NULL AND e.team2 <> '' AND e.team2 <> '?'",
    ]
    params: List[Any] = [hours * 3600]

    # sport_id=0 means "any"
    if has_sport and int(sport_id) > 0:
        # some rows may have NULL sport_id - don't lose them
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
      FROM_UNIXTIME(CASE WHEN e.start_ts > 2000000000 THEN FLOOR(e.start_ts/1000) ELSE e.start_ts END) AS start_time,
      e.start_ts
    FROM fonbet_events e
    WHERE {' AND '.join(where)}
    ORDER BY league_name ASC, e.start_ts ASC
    LIMIT %s
    """
    params.append(int(limit))
    cur.execute(sql, params)
    return cur.fetchall() or []


def _sql_fonbet_drops_map(cur, ts_col: str) -> Dict[int, dict]:
    """
    For each event_id: count factors where last odd < prev odd; also min delta among dropped factors.
    Uses MySQL 8 window functions.
    """
    try:
        cur.execute(
            f"""
            WITH last2 AS (
              SELECT event_id, factor_id, odd, {ts_col} AS ts,
                     ROW_NUMBER() OVER (PARTITION BY event_id, factor_id ORDER BY {ts_col} DESC) rn
              FROM fonbet_odds_history
              WHERE {ts_col} >= NOW() - INTERVAL 6 HOUR
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
            """
        )
        rows = cur.fetchall() or []
        return {int(r["event_id"]): r for r in rows if r.get("event_id") is not None}
    except Exception:
        return {}


def _sql_fonbet_event_factors(cur, event_id: int, hours: int, ts_col: str) -> List[dict]:
    """
    Latest + previous odds for each factor in the time window.
    """
    cur.execute(
        f"""
        WITH last2 AS (
          SELECT event_id, factor_id, odd, {ts_col} AS ts,
                 ROW_NUMBER() OVER (PARTITION BY factor_id ORDER BY {ts_col} DESC) rn
          FROM fonbet_odds_history
          WHERE event_id=%s AND {ts_col} >= NOW() - INTERVAL %s HOUR
        ),
        p AS (
          SELECT
            factor_id,
            MAX(CASE WHEN rn=1 THEN odd END) AS odd,
            MAX(CASE WHEN rn=2 THEN odd END) AS prev_odd,
            MAX(CASE WHEN rn=1 THEN ts END) AS ts
          FROM last2
          WHERE rn <= 2
          GROUP BY factor_id
        )
        SELECT factor_id, odd, prev_odd, ts, (odd - prev_odd) AS delta
        FROM p
        ORDER BY factor_id ASC
        """,
        (event_id, int(hours)),
    )
    return cur.fetchall() or []


# ------------------------------
# FONBET routes
# ------------------------------



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
    return jsonify({"items": items, "hours": hours, "limit": limit})


@app.route("/api/fonbet/event/<int:event_id>")
def api_fonbet_event(event_id: int):
    hours = safe_int(request.args.get("hours", 6), 6)
    limit = safe_int(request.args.get("limit", 1500), 1500)

    try:
        with db_connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT event_id, league_name, team1, team2, FROM_UNIXTIME(start_ts) AS start_time "
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
            label = meta.get("label") or f"factor {fid_int}"
            market = meta.get("market") or "other"
            if market not in markets:
                market = "other"
            row = {
                "factor_id": fid,
                "label": label,
                "odd": r.get("odd"),
                "prev_odd": r.get("prev_odd"),
                "delta": r.get("delta"),
                "ts": r.get("ts"),
            }
            markets[market].append(row)

        # keep only reasonable sizes for main markets
        markets["outcomes"] = markets["outcomes"][:20]
        markets["handicap"] = markets["handicap"][:60]
        markets["total"] = markets["total"][:60]
        markets["other"] = markets["other"][:500]

        return jsonify({"event": event, "markets": markets, "count": len(factors), "catalog_count": catalog_count})

    except Exception as e:
        return jsonify({"error": str(e), "event": {"event_id": event_id}, "markets": {"outcomes": [], "handicap": [], "total": [], "other": []}, "count": 0}), 500


@app.route("/fonbet")
def page_fonbet():
    return render_template_string(FONBET_LIST_INLINE)

@app.route("/fonbet_event/<int:event_id>")
def page_fonbet_event(event_id: int):
    # server-side fetch event header
    event = {"event_id": event_id, "team1": "?", "team2": "?", "league_name": "-", "start_time": "-"}
    try:
        with db_connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT event_id, league_name, team1, team2, FROM_UNIXTIME(start_ts) AS start_time "
                    "FROM fonbet_events WHERE event_id=%s",
                    (event_id,),
                )
                event = cur.fetchone() or event
    except Exception:
        pass

    for tpl in ("fonbet_event.html",):
        try:
            return render_template(tpl, event=event)
        except Exception:
            continue

    return render_template_string(FONBET_EVENT_INLINE, event=event)


if __name__ == "__main__":
    print("=" * 70)
    print("Inforadar Pro - Prematch UI")
    print("→ http://localhost:5000/prematch (22BET)")
    print("→ http://localhost:5000/prematch (22BET)_simple (always works, for debug)")
    print("=" * 70)
    app.run(host="0.0.0.0", port=5000, debug=True)
