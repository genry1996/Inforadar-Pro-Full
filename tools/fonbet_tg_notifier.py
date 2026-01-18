#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fonbet Telegram notifier (Inforadar-Pro) — PREMATCH (FT) в стиле MafiaBet.

Что делает:
- Берёт кандидатов из /api/fonbet/events (футбол prematch ближайшие N часов, без кибер/виртуал/эспорт).
- Для каждого кандидата тянет /api/fonbet/event/<id>/tables?half=ft и строит сигнал:
    * Total Over/Under drop (old -> new) - XX.X% (+ line shift если линия сместилась)
    * Handicap Home/Away drop (old -> new) - XX.X% (+ line shift)
- Отправляет ОДНО сообщение = ОДНА игра = ОДИН лучший сигнал (чтобы не было “простыней”).
- Warmup по умолчанию: при первом старте только запоминает состояние (не спамит).

Запуск пример:
  python fonbet_tg_notifier.py --interval 10 --hours 12 --min-drop-pct 11

ENV:
  TG_BOT_TOKEN, TG_CHAT_ID
  FONBET_UI_BASE_URL=http://localhost:5000
  FONBET_PUBLIC_URL=http://167.71.255.125   (чтобы ссылки в сообщениях были публичные)
  TG_TITLE="MAFIA.BET - Fonbet"             (опционально, заголовок в сообщении)
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

import requests

# Single session, ignore any system proxies (important on Windows)
HTTP = requests.Session()
HTTP.trust_env = False


# -----------------------------
# .env loader (без зависимостей)
# -----------------------------
def _strip_quotes(v: str) -> str:
    v = v.strip()
    if (len(v) >= 2) and ((v[0] == v[-1]) and v[0] in ("'", '"')):
        return v[1:-1]
    return v


def load_dotenv(path: str) -> None:
    if not path or not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = _strip_quotes(v.strip())
                os.environ.setdefault(k, v)
    except Exception:
        return


def auto_load_env(cli_env: str = "") -> None:
    """
    1) Если передали --env, грузим его.
    2) Иначе ищем .env вверх по директориям относительно файла скрипта.
    """
    if cli_env:
        load_dotenv(cli_env)
        return

    start = os.path.dirname(os.path.abspath(__file__))
    cur = start
    for _ in range(6):
        cand = os.path.join(cur, ".env")
        if os.path.exists(cand):
            load_dotenv(cand)
            return
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent


# -----------------------------
# Utils
# -----------------------------
def html_escape(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def to_float(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        if isinstance(x, (int, float)):
            return float(x)
        s = str(x).strip().replace(",", ".")
        if s in ("", "-", "—", "None", "null"):
            return None
        return float(s)
    except Exception:
        return None


def parse_dt(s: str) -> Optional[dt.datetime]:
    s = (s or "").strip()
    if not s:
        return None
    # expected: "YYYY-MM-DD HH:MM:SS" (как в UI)
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return dt.datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def fmt_start_msk(s: str) -> str:
    d = parse_dt(s)
    if not d:
        return s
    return d.strftime("%Y-%m-%d МСК-%H.%M")


def now_local() -> dt.datetime:
    return dt.datetime.now()


# -----------------------------
# Filters
# -----------------------------
_ESPORT_WORDS = (
    "esports", "e-sport", "e sport", "кибер", "киберспорт", "virtual", "виртуал",
    "fifa", "efootball", "pro evolution", "pes", "nba2k", "rocket league"
)

def is_esport_or_virtual(match: str) -> bool:
    p = (match or "").strip()
    if not p:
        return True

    low = p.lower()
    if any(w in low for w in _ESPORT_WORDS):
        return True

    # markers: "vs", nicknames in (), underscores, "Home/Away", "Хозяева/Гости"
    if re.search(r"\bvs\b", low):
        return True
    if "(" in p and ")" in p:
        return True
    if "_" in p:
        return True
    if "home" in low and "away" in low:
        return True
    if "хозя" in low and "гост" in low:
        return True

    # mixed latin+digits like Player123
    if re.search(r"[A-Za-z]", p) and re.search(r"\d", p):
        return True

    return False


# -----------------------------
# HTTP
# -----------------------------
def fetch_events(base_url: str, hours: int, min_pct_forward: float, timeout: tuple = (3.0, 10.0), debug: bool = False) -> Tuple[List[Dict[str, Any]], str]:
    base_url = base_url.rstrip("/")
    url = f"{base_url}/api/fonbet/events"
    params = {"hours": int(hours), "min_pct": float(min_pct_forward)}
    if debug:
        print(f"[http] GET {url} params={params}", flush=True)
    r = HTTP.get(url, params=params, timeout=timeout)
    note = f"HTTP {r.status_code} {r.url}"
    r.raise_for_status()
    data: Any = r.json()
    if isinstance(data, list):
        return data, note
    if isinstance(data, dict):
        for k in ("events", "data", "items", "result"):
            if k in data and isinstance(data[k], list):
                return data[k], note
    raise RuntimeError(f"unexpected json shape; {note}")


def fetch_tables(base_url: str, event_id: str, hours: int, half: str = "ft", limit: int = 8000, timeout: tuple = (3.0, 10.0), debug: bool = False) -> Dict[str, Any]:
    base_url = base_url.rstrip("/")
    url = f"{base_url}/api/fonbet/event/{event_id}/tables"
    params = {"half": half, "hours": int(hours), "limit": int(limit)}
    if debug:
        print(f"[http] GET {url} params={params}", flush=True)
    r = HTTP.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    data: Any = r.json()
    if not isinstance(data, dict):
        raise RuntimeError(f"tables: unexpected json type {type(data)}")
    return data


# -----------------------------
# Signal extraction
# -----------------------------
def _sort_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    def key(r: Dict[str, Any]) -> float:
        t = parse_dt(str(r.get("Time") or ""))
        return t.timestamp() if t else 0.0
    return sorted(rows, key=key)


def _pick_prev_now(rows: List[Dict[str, Any]]) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    if not rows:
        return None, None
    s = _sort_rows(rows)
    if len(s) == 1:
        return s[0], s[0]
    return s[-2], s[-1]


def _pct_drop(old: float, new: float) -> float:
    if old <= 0:
        return 0.0
    return (old - new) / old * 100.0



# -----------------------------
# Betwatch-style "interest" filters (ticks + implied probability)
# Why: same % drop at high odds is often less meaningful than at low odds.
# We keep "Mafia style" formatting (drop %), but filter by:
#   - percent drop (min_drop_pct) OR
#   - implied probability gain (min_delta_p) OR
#   - Betfair tick-moves (min_ticks / range-based required ticks)
# -----------------------------
_TICK_LADDER = [
    (1.01, 2.00, 0.01),
    (2.00, 3.00, 0.02),
    (3.00, 4.00, 0.05),
    (4.00, 6.00, 0.10),
    (6.00, 10.00, 0.20),
    (10.00, 20.00, 0.50),
    (20.00, 30.00, 1.00),
    (30.00, 50.00, 2.00),
    (50.00, 100.00, 5.00),
    (100.00, 1000.00, 10.00),
]

def _betfair_tick_count(old_odds: float, new_odds: float) -> float:
    """Approx tick moves between odds using Betfair ladder segments."""
    if old_odds is None or new_odds is None:
        return 0.0
    try:
        old = float(old_odds)
        new = float(new_odds)
    except Exception:
        return 0.0
    if old <= 0 or new <= 0:
        return 0.0
    lo = min(old, new)
    hi = max(old, new)
    ticks = 0.0
    for seg_lo, seg_hi, step in _TICK_LADDER:
        a = max(lo, seg_lo)
        b = min(hi, seg_hi)
        if b > a:
            ticks += (b - a) / step
    return ticks

def _delta_p(old_odds: float, new_odds: float) -> float:
    """Implied probability delta: 1/new - 1/old (positive for odds drop)."""
    if old_odds is None or new_odds is None:
        return 0.0
    try:
        old = float(old_odds)
        new = float(new_odds)
    except Exception:
        return 0.0
    if old <= 0 or new <= 0:
        return 0.0
    return (1.0 / new) - (1.0 / old)

def _required_ticks_for_odds(o: float) -> int:
    """Range-aware tick threshold.

    We borrow Betfair tick ladder to quantify how "big" a move is.
    For high odds a few ticks is usually noise, so we require more ticks.

    You can still override globally with --min-ticks (we take max()).
    """
    try:
        o = float(o or 0.0)
    except Exception:
        return 6

    if o < 2.0:
        return 5
    if o < 3.0:
        return 4
    if o < 6.0:
        return 4
    if o < 10.0:
        return 5
    if o < 20.0:
        return 6
    return 8

def _required_min_drop_pct(old_odds: float) -> float:
    """Range-based minimum drop threshold (in %).

    These defaults are tuned to be stricter on high odds (where large % moves
    are common/noisy) and more sensitive on low odds (where the same absolute
    move is harder to achieve).

    NOTE: user CLI --min-pct / --min-drop-pct is applied first.
    """
    if old_odds < 1.50:
        return 4.0
    if old_odds < 2.00:
        return 8.0
    if old_odds < 3.00:
        return 10.0
    if old_odds < 4.00:
        return 12.0
    if old_odds < 6.00:
        return 14.0
    if old_odds < 10.00:
        return 20.0
    if old_odds < 20.00:
        return 25.0
    return 30.0

def _passes_interest_filters(
    old_odds: float,
    new_odds: float,
    drop_pct: float,
    min_drop_pct: float,
    min_delta_p: float,
    min_ticks: int,
    use_ticks: bool,
) -> bool:
    """Return True if a move is "interesting enough" to notify.

    Rules:
    1) Always require user-specified drop_pct >= min_drop_pct.
    2) Then we accept the move if ANY of the following holds:
       - drop_pct >= max(min_drop_pct, required_pct_by_old_odds)
       - implied probability delta >= min_delta_p
       - ticks >= max(min_ticks, required_ticks_by_old_odds)  (if use_ticks)
    """
    try:
        old_odds = float(old_odds)
        new_odds = float(new_odds)
        drop_pct = float(drop_pct)
    except Exception:
        return False

    if drop_pct <= 0:
        return False

    # Always respect user's global % filter
    if drop_pct < float(min_drop_pct):
        return False

    # Range-aware % threshold (Mafia/Betwatch style)
    pct_need = max(float(min_drop_pct), _required_min_drop_pct(old_odds))
    if drop_pct >= pct_need:
        return True

    # Alternative: implied probability delta
    dp = max(0.0, _delta_p(old_odds, new_odds))
    if dp >= float(min_delta_p):
        return True

    # Alternative: ticks (range-aware)
    # NOTE: for high odds (>= 8.0) we ignore ticks-only moves (usually noise).
    if use_ticks and old_odds < 8.0:
        ticks = _betfair_tick_count(old_odds, new_odds)
        ticks_need = max(int(min_ticks or 0), int(_required_ticks_for_odds(old_odds)))
        if ticks >= ticks_need:
            return True

    return False

def _almost_eq(a: Optional[float], b: Optional[float]) -> bool:
    if a is None or b is None:
        return False
    return abs(a - b) < 1e-9


class Signal:
    def __init__(self, market: str, side: str, drop_pct: float, old_odds: float, new_odds: float,
                 old_line: Optional[float], new_line: Optional[float],
                 table_kind: str, table_rows: List[Dict[str, Any]], now_time: str):
        self.market = market          # "total" | "handicap"
        self.side = side              # "over"|"under"|"home"|"away"
        self.drop_pct = drop_pct
        self.old_odds = old_odds
        self.new_odds = new_odds
        self.old_line = old_line
        self.new_line = new_line
        self.table_kind = table_kind  # "total" | "handicap"
        self.table_rows = table_rows
        self.now_time = now_time      # row["Time"] (для дедупа)


def best_signal_from_tables(
    tables: Dict[str, Any],
    min_drop_pct: float,
    min_delta_p: float = 0.03,
    min_ticks: Optional[int] = None,
    use_ticks: bool = True,
    allow_crossline: bool = False,
) -> Optional[Signal]:
    """
    MafiaBet-поведение (prematch):
      - drop% считаем ТОЛЬКО по одной и той же линии (тотал/фора) — это "та же ставка".
      - если линия сменилась между последними snapshot'ами:
          * по умолчанию НЕ считаем drop% (иначе получаются гигантские проценты на другой ставке),
          * можно включить старое поведение флагом allow_crossline=True (считать по prev->now даже при смене линии).
      - 1X2: линии нет, поэтому drop% считаем по prev->now для каждого исхода (1/X/2).
    """
    best: Optional[Signal] = None

    # ---------------- TOTAL ----------------
    tot_rows = tables.get("total") or []
    if isinstance(tot_rows, list) and tot_rows:
        s = _sort_rows([r for r in tot_rows if isinstance(r, dict)])
        if len(s) >= 2:
            now = s[-1]
            prev = s[-2]

            new_line = to_float(now.get("Total"))
            old_line_prev = to_float(prev.get("Total"))

            base_prev = prev
            old_line = old_line_prev

            # Если линия поменялась — ищем последнюю строку с тем же Total, что и сейчас
            if (
                old_line is not None
                and new_line is not None
                and not _almost_eq(old_line, new_line)
                and not allow_crossline
            ):
                base_prev = None
                for i in range(len(s) - 2, -1, -1):
                    cand = s[i]
                    cl = to_float(cand.get("Total"))
                    if cl is not None and _almost_eq(cl, new_line):
                        base_prev = cand
                        old_line = cl
                        break

            if base_prev is not None:
                old_over = to_float(base_prev.get("Over"))
                new_over = to_float(now.get("Over"))
                old_under = to_float(base_prev.get("Under"))
                new_under = to_float(now.get("Under"))

                if old_over is not None and new_over is not None and new_over < old_over:
                    dp = _pct_drop(old_over, new_over)
                    if _passes_interest_filters(old_over, new_over, dp, min_drop_pct, min_delta_p, min_ticks, use_ticks):
                        cand = Signal(
                            "total", "over", dp,
                            old_over, new_over,
                            old_line, new_line,
                            "total", tot_rows, str(now.get("Time") or "")
                        )
                        if best is None or cand.drop_pct > best.drop_pct:
                            best = cand

                if old_under is not None and new_under is not None and new_under < old_under:
                    dp = _pct_drop(old_under, new_under)
                    if _passes_interest_filters(old_under, new_under, dp, min_drop_pct, min_delta_p, min_ticks, use_ticks):
                        cand = Signal(
                            "total", "under", dp,
                            old_under, new_under,
                            old_line, new_line,
                            "total", tot_rows, str(now.get("Time") or "")
                        )
                        if best is None or cand.drop_pct > best.drop_pct:
                            best = cand

    # ---------------- HANDICAP ----------------
    hcp_rows = tables.get("handicap") or []
    if isinstance(hcp_rows, list) and hcp_rows:
        s = _sort_rows([r for r in hcp_rows if isinstance(r, dict)])
        if len(s) >= 2:
            now = s[-1]
            prev = s[-2]

            key_line = "Handicap" if ("Handicap" in now or "Handicap" in prev) else "Hcp"
            new_line = to_float(now.get(key_line))
            old_line_prev = to_float(prev.get(key_line))

            base_prev = prev
            old_line = old_line_prev

            if (
                old_line is not None
                and new_line is not None
                and not _almost_eq(old_line, new_line)
                and not allow_crossline
            ):
                base_prev = None
                for i in range(len(s) - 2, -1, -1):
                    cand = s[i]
                    cl = to_float(cand.get(key_line))
                    if cl is not None and _almost_eq(cl, new_line):
                        base_prev = cand
                        old_line = cl
                        break

            if base_prev is not None:
                old_home = to_float(base_prev.get("Home"))
                new_home = to_float(now.get("Home"))
                old_away = to_float(base_prev.get("Away"))
                new_away = to_float(now.get("Away"))

                if old_home is not None and new_home is not None and new_home < old_home:
                    dp = _pct_drop(old_home, new_home)
                    if _passes_interest_filters(old_home, new_home, dp, min_drop_pct, min_delta_p, min_ticks, use_ticks):
                        cand = Signal(
                            "handicap", "home", dp,
                            old_home, new_home,
                            old_line, new_line,
                            "handicap", hcp_rows, str(now.get("Time") or "")
                        )
                        if best is None or cand.drop_pct > best.drop_pct:
                            best = cand

                if old_away is not None and new_away is not None and new_away < old_away:
                    dp = _pct_drop(old_away, new_away)
                    if _passes_interest_filters(old_away, new_away, dp, min_drop_pct, min_delta_p, min_ticks, use_ticks):
                        cand = Signal(
                            "handicap", "away", dp,
                            old_away, new_away,
                            old_line, new_line,
                            "handicap", hcp_rows, str(now.get("Time") or "")
                        )
                        if best is None or cand.drop_pct > best.drop_pct:
                            best = cand

    # ---------------- 1X2 (outcomes) ----------------
    out_rows = tables.get("outcomes") or tables.get("1x2") or []
    if isinstance(out_rows, list) and out_rows:
        s = _sort_rows([r for r in out_rows if isinstance(r, dict)])
        if len(s) >= 2:
            now = s[-1]
            prev = s[-2]
            for side_key in ("1", "X", "2"):
                old_o = to_float(prev.get(side_key))
                new_o = to_float(now.get(side_key))
                if old_o is None or new_o is None:
                    continue
                if new_o < old_o:
                    dp = _pct_drop(old_o, new_o)
                    if _passes_interest_filters(old_o, new_o, dp, min_drop_pct, min_delta_p, min_ticks, use_ticks):
                        cand = Signal(
                            "outcomes", side_key, dp,
                            old_o, new_o,
                            None, None,
                            "outcomes", out_rows, str(now.get("Time") or "")
                        )
                        if best is None or cand.drop_pct > best.drop_pct:
                            best = cand

    return best




def _pre_move_same_line_drop(
    tables: Dict[str, Any],
    market: str,
    old_line: float,
    *,
    min_drop_pct: float,
    min_delta_p: float,
    min_ticks: Optional[int],
    use_ticks: bool,
) -> Optional[Signal]:
    """
    When mainline changes between the last two snapshots (old_line -> new_line),
    the "cross-line drop%" is not meaningful.

    Inforadar-like logic:
      - Try to detect a REAL odds drop on the *previous* line (old_line) right before the move,
        i.e. compare the last two snapshots where the mainline was still == old_line.
      - If such a drop exists (passes thresholds), return that Signal (with old_line==new_line==old_line).
      - Otherwise return None (no alert for pure line move).
    """
    rows = tables.get(market) or []
    if not isinstance(rows, list) or len(rows) < 3:
        return None

    s = _sort_rows([r for r in rows if isinstance(r, dict)])
    if len(s) < 3:
        return None

    now = s[-1]
    prev = s[-2]  # last snapshot with old_line

    if market == "total":
        key_line = "Total"
        side_map = {"over": "Over", "under": "Under"}
    elif market == "handicap":
        key_line = "Handicap" if ("Handicap" in prev or "Handicap" in now) else "Hcp"
        side_map = {"home": "Home", "away": "Away"}
    else:
        return None

    prev_line = to_float(prev.get(key_line))
    if prev_line is None or not _almost_eq(prev_line, old_line):
        return None

    # Find the previous snapshot where line was still old_line (same bet)
    base_prev = None
    for i in range(len(s) - 3, -1, -1):
        cand = s[i]
        cl = to_float(cand.get(key_line))
        if cl is not None and _almost_eq(cl, old_line):
            base_prev = cand
            break
        # stop early if we've clearly moved away for a while
        # (keeps scan small on long histories)
        if cl is not None and not _almost_eq(cl, old_line):
            # don't break: old_line could appear earlier again (oscillations),
            # but usually base_prev is adjacent; keep scanning anyway.
            continue

    if base_prev is None:
        return None

    best: Optional[Signal] = None
    prev_time = str(prev.get("Time") or "")

    for side, col in side_map.items():
        o = to_float(base_prev.get(col))
        n = to_float(prev.get(col))
        if o is None or n is None:
            continue
        if n >= o:
            continue

        dp = _pct_drop(o, n)
        if _passes_interest_filters(o, n, dp, min_drop_pct, min_delta_p, min_ticks, use_ticks):
            cand = Signal(
                market, side, dp,
                o, n,
                float(old_line), float(old_line),
                market, rows, prev_time
            )
            if best is None or cand.drop_pct > best.drop_pct:
                best = cand

    return best

def signals_per_market_from_tables(
    tables: Dict[str, Any],
    min_drop_pct: float,
    min_delta_p: float = 0.03,
    min_ticks: Optional[int] = None,
    use_ticks: bool = True,
    allow_crossline: bool = False,
) -> List[Signal]:
    """Return up to 3 signals (one per market): 1X2, Handicap, Total.

    Mafia-style: if a match has drops in multiple markets, we return multiple signals and main
    sends a separate Telegram message for each market where the drop happened.
    """
    res: List[Signal] = []
    for market in ("outcomes", "handicap", "total"):
        part: Dict[str, Any] = {market: tables.get(market) or []}
        sig = best_signal_from_tables(
            part,
            min_drop_pct=min_drop_pct,
            min_delta_p=min_delta_p,
            min_ticks=min_ticks,
            use_ticks=use_ticks,
            allow_crossline=allow_crossline,
        )
        if sig is not None:
            res.append(sig)
    return res


def store_baseline_from_tables(signals_state: Dict[str, Any], event_id: str, tables: Dict[str, Any]) -> None:
    """Warmup baseline: remember last snapshot time per market+side to avoid first-run spam."""
    eid = str(event_id or "")
    if not eid:
        return

    def _set(key: str, t: str) -> None:
        cur = signals_state.get(key) or {}
        signals_state[key] = {
            "last_time": t,
            "last_sent_ts": int(cur.get("last_sent_ts") or 0),
        }

    # outcomes (1X2)
    out_rows = tables.get("outcomes") or []
    if isinstance(out_rows, list) and out_rows:
        s = _sort_rows([r for r in out_rows if isinstance(r, dict)])
        if s:
            t = str(s[-1].get("Time") or "")
            for side in ("1", "X", "2"):
                _set(f"{eid}:outcomes:{side}", t)

    # total (Over/Under)
    tot_rows = tables.get("total") or []
    if isinstance(tot_rows, list) and tot_rows:
        s = _sort_rows([r for r in tot_rows if isinstance(r, dict)])
        if s:
            t = str(s[-1].get("Time") or "")
            for side in ("over", "under"):
                _set(f"{eid}:total:{side}", t)

    # handicap (Home/Away)
    hcp_rows = tables.get("handicap") or []
    if isinstance(hcp_rows, list) and hcp_rows:
        s = _sort_rows([r for r in hcp_rows if isinstance(r, dict)])
        if s:
            t = str(s[-1].get("Time") or "")
            for side in ("home", "away"):
                _set(f"{eid}:handicap:{side}", t)


def _tables_have_any_market(tables: Optional[Dict[str, Any]]) -> bool:
    if not isinstance(tables, dict):
        return False
    for k in ("outcomes", "handicap", "total"):
        v = tables.get(k)
        if isinstance(v, list) and len(v) > 0:
            return True
    return False


def _event_group_key(ev: Dict[str, Any]) -> str:
    """Group potentially duplicated events to recover from rare 'No data' on a single event_id."""
    cat = ev.get("category_id") or ev.get("league_id") or ev.get("category") or ""
    start = ev.get("start_ts") or ev.get("start_time") or ev.get("start") or ""
    if isinstance(start, (int, float)):
        start_key = str(int(start))
    else:
        d = parse_dt(str(start))
        start_key = str(int(d.timestamp())) if d else str(start)

    t1 = ev.get("team1") or ev.get("home_team") or ""
    t2 = ev.get("team2") or ev.get("away_team") or ""
    match = ev.get("match")
    if (not t1 or not t2) and isinstance(match, str):
        parts = re.split(r"\s*[—\-–]\s*", match.strip())
        if len(parts) >= 2:
            t1 = t1 or parts[0]
            t2 = t2 or parts[1]

    def norm(s: str) -> str:
        s = (s or "").strip().lower()
        s = re.sub(r"\s+", " ", s)
        return s

    return f"{cat}|{start_key}|{norm(str(t1))}|{norm(str(t2))}"


def build_event_groups(events: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    groups: Dict[str, List[str]] = {}
    for ev in events:
        eid = str(ev.get("event_id") or "")
        if not eid:
            continue
        k = _event_group_key(ev)
        if not k:
            continue
        groups.setdefault(k, [])
        if eid not in groups[k]:
            groups[k].append(eid)
    return groups



# -----------------------------
# MOVE anti-spam (Inforadar-like)
# -----------------------------
# Goal:
# - Keep current "MOVE" alerts (cross-line) but avoid spam on line jitter (2.5 <-> 3.0).
# - Do NOT send MOVE immediately: first we register it as "pending", then confirm on a newer snapshot.
# - Suppress reverse MOVE shortly after the first one (line bounced back).
#
# State structure:
#   state["moves"][f"{eid}:{market}"] = {
#       "last_sent_ts": int,
#       "last_from": float,
#       "last_to": float,
#       "pending": {
#           "<side>": {"from_line": float, "to_line": float, "old_odds": float,
#                      "first_seen_time": str, "first_seen_ts": int}
#       }
#   }

def _moves_meta_key(eid: str, market: str) -> str:
    return f"{str(eid)}:{str(market)}"


def _extract_latest_snapshot_for_market(
    tables: Dict[str, Any],
    market: str,
    side: str,
) -> Tuple[Optional[float], Optional[float], str, List[Dict[str, Any]]]:
    """Return (line, odds, time_str, rows) for the latest snapshot of a market.

    market: "total" or "handicap"
    side:
      total: "over"|"under"
      handicap: "home"|"away"
    """
    rows = tables.get(market) or []
    if not isinstance(rows, list) or not rows:
        return None, None, "", []

    s = _sort_rows([r for r in rows if isinstance(r, dict)])
    if not s:
        return None, None, "", []

    now = s[-1]
    t = str(now.get("Time") or "")

    if market == "total":
        line = to_float(now.get("Total"))
        odds = to_float(now.get("Over" if side == "over" else "Under"))
        return line, odds, t, rows

    # handicap
    key_line = "Handicap" if ("Handicap" in now) else "Hcp"
    line = to_float(now.get(key_line))
    odds = to_float(now.get("Home" if side == "home" else "Away"))
    return line, odds, t, rows


def _register_pending_move(
    moves_state: Dict[str, Any],
    *,
    eid: str,
    sig: Signal,
    now_ts: int,
) -> None:
    """Register a cross-line MOVE as pending (do not send yet)."""
    if sig.market not in ("total", "handicap"):
        return
    if sig.old_line is None or sig.new_line is None:
        return
    if _almost_eq(sig.old_line, sig.new_line):
        return

    meta_key = _moves_meta_key(eid, sig.market)
    meta = moves_state.get(meta_key) or {}
    pending = meta.get("pending") or {}
    if not isinstance(pending, dict):
        pending = {}

    # overwrite / upsert pending for this side
    pending[str(sig.side)] = {
        "from_line": float(sig.old_line),
        "to_line": float(sig.new_line),
        "old_odds": float(sig.old_odds),
        "first_seen_time": str(sig.now_time or ""),
        "first_seen_ts": int(now_ts),
    }
    meta["pending"] = pending
    moves_state[meta_key] = meta


def _flush_pending_moves_for_event(
    *,
    eid: str,
    ev: Dict[str, Any],
    tables: Dict[str, Any],
    moves_state: Dict[str, Any],
    signals_state: Dict[str, Any],
    state: Dict[str, Any],
    state_path: str,
    token: str,
    chat_id: str,
    public_base: str,
    title: str,
    silent: bool,
    timeout: Tuple[float, float],
    debug_http: bool,
    # interest filters:
    min_drop_pct: float,
    min_delta_p: float,
    min_ticks: Optional[int],
    use_ticks: bool,
    cooldown_sec: int,
    # anti-spam:
    move_ttl_sec: int,
    move_reverse_suppress_sec: int,
    # cap:
    max_to_send: int,
) -> int:
    """Try to confirm and send pending MOVE alerts. Returns messages sent."""
    if max_to_send <= 0:
        return 0

    sent = 0
    now_ts = int(dt.datetime.utcnow().timestamp())

    for market in ("total", "handicap"):
        meta_key = _moves_meta_key(eid, market)
        meta = moves_state.get(meta_key)
        if not isinstance(meta, dict):
            continue
        pending = meta.get("pending")
        if not isinstance(pending, dict) or not pending:
            continue

        # iterate sides pending
        for side in list(pending.keys()):
            if sent >= max_to_send:
                break

            pend = pending.get(side) or {}
            if not isinstance(pend, dict):
                pending.pop(side, None)
                continue

            first_seen_ts = int(pend.get("first_seen_ts") or 0)
            if first_seen_ts and (now_ts - first_seen_ts) > int(move_ttl_sec):
                # stale pending -> drop
                pending.pop(side, None)
                continue

            try:
                from_line = float(pend.get("from_line"))
                to_line = float(pend.get("to_line"))
                old_odds = float(pend.get("old_odds"))
                first_seen_time = str(pend.get("first_seen_time") or "")
            except Exception:
                pending.pop(side, None)
                continue

            # latest snapshot on this market+side
            cur_line, cur_odds, cur_time, rows = _extract_latest_snapshot_for_market(tables, market, str(side))
            if cur_line is None or cur_odds is None or not cur_time:
                continue

            # confirm: we need a newer snapshot on the target line
            if not _almost_eq(cur_line, to_line):
                continue
            if first_seen_time and cur_time == first_seen_time:
                continue

            # suppress reverse MOVE shortly after last MOVE
            last_sent_ts = int(meta.get("last_sent_ts") or 0)
            last_from = meta.get("last_from")
            last_to = meta.get("last_to")
            if (
                last_sent_ts
                and last_from is not None
                and last_to is not None
                and _almost_eq(from_line, float(last_to))
                and _almost_eq(to_line, float(last_from))
                and (now_ts - last_sent_ts) < int(move_reverse_suppress_sec)
            ):
                pending.pop(side, None)
                continue

            # keep "as-is": MOVE is only interesting if odds are still lower vs the original side odds
            if cur_odds >= old_odds:
                pending.pop(side, None)
                continue

            dp = _pct_drop(old_odds, cur_odds)
            if not _passes_interest_filters(old_odds, cur_odds, dp, min_drop_pct, min_delta_p, min_ticks, use_ticks):
                # not interesting anymore, but keep pending until TTL (it may drop more)
                continue

            # per-signal dedupe/cooldown
            sig_key = f"{eid}:{market}:{side}"
            prev = signals_state.get(sig_key) or {}
            last_time = str(prev.get("last_time") or "")
            last_sent_sig_ts = int(prev.get("last_sent_ts") or 0)

            # already processed this snapshot
            if last_time and cur_time == last_time:
                pending.pop(side, None)
                continue

            if last_sent_sig_ts and (now_ts - last_sent_sig_ts) < int(cooldown_sec):
                # update last_time (so we don't loop on same snapshot)
                signals_state[sig_key] = {"last_time": cur_time, "last_sent_ts": last_sent_sig_ts}
                continue

            # build confirmed MOVE signal (we keep "move (...@line -> ...@line)" formatting)
            sig = Signal(
                market=market,
                side=str(side),
                drop_pct=dp,
                old_odds=old_odds,
                new_odds=cur_odds,
                old_line=from_line,
                new_line=to_line,
                table_kind=market,
                table_rows=rows,
                now_time=cur_time,
            )

            text_msg = build_message(ev, sig, public_base=public_base, title=title)
            try:
                tg_send(
                    token, chat_id, text_msg,
                    silent=silent,
                    timeout=timeout,
                    debug=debug_http,
                )
                sent += 1
                signals_state[sig_key] = {"last_time": cur_time, "last_sent_ts": now_ts}
                # update move meta and clear pending
                meta["last_sent_ts"] = now_ts
                meta["last_from"] = from_line
                meta["last_to"] = to_line
                pending.pop(side, None)
                meta["pending"] = pending
                moves_state[meta_key] = meta
                save_state(state_path, state)
            except Exception as e:
                print(f"[error] telegram send failed (move): {e}", file=sys.stderr)

        # persist pending updates for this market
        meta["pending"] = pending
        moves_state[meta_key] = meta

    return sent


# -----------------------------
# Rendering (MafiaBet-like)
# -----------------------------
def _fmt_time_short(ts: str) -> str:
    d = parse_dt(ts)
    if not d:
        return ts
    return d.strftime("%H:%M")


def _format_table(signal: Signal, max_lines: int = 18) -> str:
    rows = [r for r in signal.table_rows if isinstance(r, dict)]
    rows = _sort_rows(rows)
    rows = rows[-max_lines:][::-1]  # newest first

    if signal.table_kind == "total":
        header = "Time | Score | Line | Over | Under"
        lines = [header]
        for r in rows:
            t = _fmt_time_short(str(r.get("Time") or ""))
            line = r.get("Total")
            over = r.get("Over")
            under = r.get("Under")
            lines.append(f"{t:>4} |  -   | {str(line):>4} | {str(over):>4} | {str(under):>4}")
        return "\n".join(lines)

    if signal.table_kind == "outcomes":
        header = "Time | Score |  1  |  X  |  2"
        lines = [header]
        for r in rows:
            t = _fmt_time_short(str(r.get("Time") or ""))
            o1 = r.get("1")
            ox = r.get("X")
            o2 = r.get("2")
            lines.append(f"{t:>4} |  -   | {str(o1):>4} | {str(ox):>4} | {str(o2):>4}")
        return "\n".join(lines)

    # handicap
    key_line = "Handicap" if any("Handicap" in r for r in rows) else "Hcp"
    header = "Time | Score | Line | Home | Away"
    lines = [header]
    for r in rows:
        t = _fmt_time_short(str(r.get("Time") or ""))
        line = r.get(key_line)
        home = r.get("Home")
        away = r.get("Away")
        lines.append(f"{t:>4} |  -   | {str(line):>4} | {str(home):>4} | {str(away):>4}")
    return "\n".join(lines)




def build_message(ev: Dict[str, Any], sig: Signal, public_base: str, title: str) -> str:
    match = ev.get("match") or f"{ev.get('team1','?')} — {ev.get('team2','?')}"
    league = ev.get("league") or ""
    start_ts = ev.get("start_time")
    start_line = ""
    if start_ts:
        start_line = str(start_ts)

    # detect cross-line move (handicap/total where line changed)
    line_changed = False
    if sig.market in ("handicap", "total") and sig.old_line is not None and sig.new_line is not None:
        line_changed = not _almost_eq(sig.old_line, sig.new_line)

    # label + main line
    if sig.market == "total":
        label = "Total Over" if sig.side == "over" else "Total Under"
    elif sig.market in ("1x2", "outcomes"):
        if sig.side == "1":
            label = "1X2 Home"
        elif sig.side.upper() == "X":
            label = "1X2 Draw"
        else:
            label = "1X2 Away"
    else:
        label = "Handicap Home" if sig.side == "home" else "Handicap Away"

    # message line
    if line_changed:
        # For line shift we DO NOT call it a "% drop" (different bet now).
        dp_pp = _delta_p(sig.old_odds, sig.new_odds) * 100.0
        drop_line = (
            f"{label} move ({sig.old_odds:.2f}@{sig.old_line:g} -> {sig.new_odds:.2f}@{sig.new_line:g})"
            f" | Δp {dp_pp:.1f}p"
        )
        shift = ""
    else:
        drop_line = f"{label} drop ({sig.old_odds:.2f} -> {sig.new_odds:.2f}) - {sig.drop_pct:.1f}%"
        shift = ""

    dash = public_base.rstrip("/") + f"/#/dashboard/football/game/{ev.get('event_id')}"
    pre = _format_table(sig)

    parts = []
    parts.append(f"<b>{html_escape(title)}</b>")
    parts.append("⚽ <b>FONBET</b> ⚽")
    parts.append("· Prematch")
    parts.append("")
    parts.append(f"· {html_escape(drop_line)}{html_escape(shift)}")
    parts.append("")
    if league:
        parts.append(html_escape(str(league)))
    parts.append(f"<b>{html_escape(str(match))}</b>")
    if start_line:
        parts.append(html_escape(start_line))
    parts.append("")
    parts.append("<pre>" + html_escape(pre) + "</pre>")
    parts.append("")
    parts.append(html_escape(dash))
    return "\n".join(parts)



# -----------------------------
# Telegram
# -----------------------------
def tg_send(token: str, chat_id: str, text: str, silent: bool = False, timeout: tuple = (3.0, 10.0), debug: bool = False) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
        "disable_notification": bool(silent),
    }
    if debug:
        print(f"[http] POST {url} chat_id={chat_id}", flush=True)
    r = HTTP.post(url, json=payload, timeout=timeout)
    if r.status_code != 200:
        raise RuntimeError(f"telegram send failed HTTP {r.status_code}: {r.text[:300]!r}")


# -----------------------------
# State
# -----------------------------
def load_state(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        return {"warmup_done": False, "signals": {}}
    try:
        with open(path, "r", encoding="utf-8") as f:
            s = json.load(f)
            if isinstance(s, dict):
                s.setdefault("warmup_done", False)
                s.setdefault("signals", {})
                return s
    except Exception:
        pass
    return {"warmup_done": False, "signals": {}}


def save_state(path: str, state: Dict[str, Any]) -> None:
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# -----------------------------
# Main
# -----------------------------
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=float, default=10.0, help="poll interval seconds")
    ap.add_argument("--hours", type=int, default=12, help="prematch window, hours")
    ap.add_argument("--min-pct", type=float, default=11.0, dest="min_pct",
                    help="min drop threshold in %% (alias: --min-drop-pct)")
    ap.add_argument("--min-delta-p", type=float, default=0.03,
                    help="Min implied probability gain (1/new-1/old) to notify, used Betwatch-like (default: 0.03)")
    ap.add_argument("--min-ticks", type=int, default=None,
                    help="Override Betwatch tick filter: require at least N Betfair ticks (default: auto by odds range)")
    ap.add_argument("--no-ticks", action="store_true",
                    help="Disable Betwatch tick filter (leave only percent drop / delta-p)")
    ap.add_argument("--min-drop-pct", type=float, default=None, dest="min_drop_pct",
                    help="min drop threshold in %% (preferred name)")
    # Cross-line behavior: Mafia-style alert usually allows line move (e.g., 0 -> 1.5).
    # Default: ALLOW cross-line. Disable with --no-crossline.
    cg = ap.add_mutually_exclusive_group()
    cg.add_argument("--allow-crossline", dest="allow_crossline", action="store_true", default=True,
                    help="Allow drop%% computation across a line move (old_line != new_line). Default: ON.")
    cg.add_argument("--no-crossline", dest="allow_crossline", action="store_false",
                    help="Disallow cross-line drop%% (require same line).")
    ap.add_argument("--cooldown-sec", dest="cooldown_sec", type=int, default=300,
                    help="Per-signal cooldown (seconds) before sending another alert for the same game/market/side.")
    ap.add_argument("--move-ttl-sec", dest="move_ttl_sec", type=int, default=300,
                    help="MOVE anti-spam: pending confirmation TTL in seconds (default: 300).")
    ap.add_argument("--move-reverse-suppress-sec", dest="move_reverse_suppress_sec", type=int, default=1800,
                    help="MOVE anti-spam: suppress reverse line-move alerts within N seconds (default: 1800).")
    ap.add_argument("--max-per-poll", type=int, default=8, dest="max_per_poll",
                    help="max messages per poll (hard cap)")
    ap.add_argument("--base-url", type=str, default=os.environ.get("FONBET_UI_BASE_URL", "http://localhost:5000"))
    ap.add_argument("--timeout-connect", type=float, default=3.0, dest="timeout_connect",
                    help="HTTP connect timeout (seconds) for UI/Telegram calls")
    ap.add_argument("--timeout-read", type=float, default=10.0, dest="timeout_read",
                    help="HTTP read timeout (seconds) for UI/Telegram calls")
    ap.add_argument("--tables-limit", type=int, default=2000, dest="tables_limit",
                    help="Max rows per /api/fonbet/event/<id>/tables fetch. Lower=faster, less history. Default 2000.")
    ap.add_argument("--tables-retries", type=int, default=1, dest="tables_retries",
                    help="Retries for table fetch on timeout/connection errors. Default 1.")
    ap.add_argument("--debug-http", action="store_true", help="print requested URLs (debug)")
    ap.add_argument("--env", type=str, default="", help="optional path to .env file to load")
    ap.add_argument("--silent", action="store_true", help="send silently (no sound)")
    ap.add_argument("--once", action="store_true", help="run once and exit")
    ap.add_argument("--no-warmup", action="store_true", help="disable warmup (send immediately)")
    args = ap.parse_args()

    auto_load_env(args.env)

    token = os.environ.get("TG_BOT_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN") or ""
    chat_id = os.environ.get("TG_CHAT_ID") or os.environ.get("TELEGRAM_CHAT_ID") or ""
    if not token or not chat_id:
        print("[fatal] Telegram creds missing. Set TG_BOT_TOKEN and TG_CHAT_ID in .env or environment.", file=sys.stderr)
        return 2
    base_url = args.base_url
    public_base = os.environ.get("FONBET_PUBLIC_URL") or os.environ.get("PUBLIC_URL") or args.base_url
    title = os.environ.get("TG_TITLE") or "ODDLY.BET - Fonbet"

    min_drop_pct = float(args.min_drop_pct) if args.min_drop_pct is not None else float(args.min_pct)
    allow_crossline = bool(getattr(args, 'allow_crossline', False))
    use_ticks = not bool(getattr(args, 'no_ticks', False))
    min_ticks = getattr(args, 'min_ticks', None)
    print(f"[cfg] base_url={args.base_url} | public_base={public_base} | min_drop_pct={min_drop_pct} | allow_crossline={allow_crossline}", flush=True)
    print(f"[cfg] timeouts connect={args.timeout_connect}s read={args.timeout_read}s | debug_http={args.debug_http}", flush=True)

    state_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonbet_tg_state.json")
    state = load_state(state_path)
    warmup_enabled = (not args.no_warmup)

    # Forwarded to /api/fonbet/events for candidate reduction
    min_pct_forward = min(3.0, min_drop_pct)

    while True:
        try:
            events, note = fetch_events(args.base_url, args.hours, min_pct_forward,
                                      timeout=(args.timeout_connect, args.timeout_read),
                                      debug=args.debug_http)
        except Exception as e:
            print(f"[error] /api/fonbet/events failed: {e}", file=sys.stderr)
            if args.once:
                return 1
            time.sleep(max(1.0, args.interval))
            continue

        now = now_local()
        horizon = now + dt.timedelta(hours=args.hours)

        # filter prematch football only (hard)
        filtered: List[Dict[str, Any]] = []
        for ev in events:
            if not isinstance(ev, dict):
                continue
            if ev.get("sport_id") not in (1, "1", None):
                continue
            match = str(ev.get("match") or "")
            if is_esport_or_virtual(match):
                continue

            st = parse_dt(str(ev.get("start_time") or ""))
            if st and not (now <= st <= horizon):
                continue

            filtered.append(ev)

        # Group duplicates by (category,start,teams) to recover from rare 'No data' event_id
        event_groups = build_event_groups(filtered)

        signals_state: Dict[str, Any] = state.setdefault("signals", {})
        moves_state: Dict[str, Any] = state.setdefault("moves", {})
        sent = 0

        for ev in filtered:
            eid = str(ev.get("event_id") or "")
            if not eid:
                continue

            # fetch detailed tables (can be heavy; retry with smaller limit on timeout)
            tables = None
            err = None
            lim = int(getattr(args, 'tables_limit', 2000) or 0)
            retries = int(getattr(args, 'tables_retries', 1) or 0)
            tables = None
            err = None
            for attempt in range(max(1, retries + 1)):
                # Always define lim_eff so we can safely use it in retry/backoff logic
                lim_eff = lim if lim > 0 else 8000
                if attempt > 0:
                    # exponential backoff on heavy queries
                    lim_eff = max(200, int(lim_eff * (0.6 ** attempt)))
                try:
                    read_to = float(args.timeout_read) * (2.0 if attempt > 0 else 1.0)
                    tables = fetch_tables(
                        base_url=base_url,
                        event_id=str(eid),
                        hours=int(args.hours),
                        half='ft',
                        limit=lim_eff,
                        timeout=(args.timeout_connect, read_to),
                        debug=args.debug_http,
                    )
                    if tables is not None:
                        err = None
                        break
                except Exception as e:
                    err = e
                # next attempt: reduce limit a bit to avoid app_22bet heavy queries
                lim = max(200, int(lim_eff * 0.6))
                time.sleep(0.15)
            if tables is None:
                if err:
                    print(f"[warn] tables failed for {eid}: {err}", file=sys.stderr)
                continue

            # Rare case: one event_id may return empty tables even though match exists on site.
            # Try a sibling event_id from the same (category,start,teams) group.
            if not _tables_have_any_market(tables):
                try:
                    gk = _event_group_key(ev)
                    alt_ids = event_groups.get(gk) or []
                except Exception:
                    alt_ids = []
                for alt_id in alt_ids:
                    alt_id = str(alt_id)
                    if not alt_id or alt_id == str(eid):
                        continue
                    try:
                        tables_alt = fetch_tables(
                            base_url=base_url,
                            event_id=alt_id,
                            hours=int(args.hours),
                            half='ft',
                            limit=min(int(lim_eff), 2000),
                            timeout=(args.timeout_connect, read_to),
                            debug=args.debug_http,
                        )
                        if _tables_have_any_market(tables_alt):
                            tables = tables_alt
                            eid = alt_id
                            ev = dict(ev)
                            ev['event_id'] = eid
                            break
                    except Exception:
                        continue

            # warmup: store baseline snapshot times (per market+side) and skip first-run sending
            if warmup_enabled and not state.get('warmup_done', False):
                store_baseline_from_tables(signals_state, eid, tables)
                continue

            sigs = signals_per_market_from_tables(
                tables,
                min_drop_pct=min_drop_pct,
                min_delta_p=getattr(args, 'min_delta_p', 0.03),
                min_ticks=min_ticks,
                use_ticks=use_ticks,
                allow_crossline=allow_crossline,
            )
            for sig in (sigs or []):
                # signal key for dedupe (per market+side)
                key = f"{eid}:{sig.market}:{sig.side}"
                prev = signals_state.get(key) or {}
                last_sent_ts = int(prev.get('last_sent_ts') or 0)
                last_time = str(prev.get('last_time') or '')

                # if already sent for this exact snapshot time -> skip
                if sig.now_time and last_time and sig.now_time == last_time:
                    continue

                # cooldown
                now_ts = int(dt.datetime.utcnow().timestamp())
                # Line move handling (Inforadar-like):
                # If last two snapshots have different lines, don't alert on pure MOVE.
                # Try to derive a REAL odds drop on the previous line right before the move.
                if (
                    sig.market in ("handicap", "total")
                    and sig.old_line is not None
                    and sig.new_line is not None
                    and not _almost_eq(sig.old_line, sig.new_line)
                ):
                    orig_key = key
                    orig_last_sent_ts = last_sent_ts
                    orig_now_time = sig.now_time

                    alt = _pre_move_same_line_drop(
                        tables,
                        sig.market,
                        float(sig.old_line),
                        min_drop_pct=min_drop_pct,
                        min_delta_p=getattr(args, 'min_delta_p', 0.03),
                        min_ticks=min_ticks,
                        use_ticks=use_ticks,
                    )

                    if alt is None:
                        # mark snapshot as seen (so we don't loop forever on same cross-line snapshot)
                        signals_state[orig_key] = {"last_time": orig_now_time, "last_sent_ts": orig_last_sent_ts}
                        continue

                    # We will send the derived DROP (same line), and still mark cross-line snapshot as seen
                    signals_state[orig_key] = {"last_time": orig_now_time, "last_sent_ts": orig_last_sent_ts}

                    sig = alt
                    key = f"{eid}:{sig.market}:{sig.side}"
                    prev = signals_state.get(key) or {}
                    last_sent_ts = int(prev.get('last_sent_ts') or 0)
                    last_time = str(prev.get('last_time') or '')

                    if sig.now_time and last_time and sig.now_time == last_time:
                        continue


                if last_sent_ts and (now_ts - last_sent_ts) < int(args.cooldown_sec):
                    # still update last_time so we don't loop forever on same snapshot
                    signals_state[key] = {
                        'last_time': sig.now_time,
                        'last_sent_ts': last_sent_ts,
                    }
                    continue

                text = build_message(ev, sig, public_base=public_base, title=title)
                try:
                    tg_send(
                        token, chat_id, text,
                        silent=args.silent,
                        timeout=(args.timeout_connect, args.timeout_read),
                        debug=args.debug_http
                    )
                    sent += 1
                    signals_state[key] = {'last_time': sig.now_time, 'last_sent_ts': now_ts}
                    save_state(state_path, state)
                except Exception as e:
                    print(f"[error] telegram send failed: {e}", file=sys.stderr)

                if sent >= int(args.max_per_poll):
                    break

            # Confirm pending MOVE (line shift) alerts with anti-spam (Inforadar-like)
            if sent < int(args.max_per_poll):
                sent += _flush_pending_moves_for_event(
                    eid=eid,
                    ev=ev,
                    tables=tables,
                    moves_state=moves_state,
                    signals_state=signals_state,
                    state=state,
                    state_path=state_path,
                    token=token,
                    chat_id=chat_id,
                    public_base=public_base,
                    title=title,
                    silent=args.silent,
                    timeout=(args.timeout_connect, args.timeout_read),
                    debug_http=args.debug_http,
                    min_drop_pct=min_drop_pct,
                    min_delta_p=getattr(args, 'min_delta_p', 0.03),
                    min_ticks=min_ticks,
                    use_ticks=use_ticks,
                    cooldown_sec=int(args.cooldown_sec),
                    move_ttl_sec=int(getattr(args, 'move_ttl_sec', 900)),
                    move_reverse_suppress_sec=int(getattr(args, 'move_reverse_suppress_sec', 1800)),
                    max_to_send=int(args.max_per_poll) - int(sent),
                )
            if sent >= int(args.max_per_poll):
                break


        if warmup_enabled and not state.get("warmup_done", False):
            state["warmup_done"] = True
            save_state(state_path, state)
            print("[ok] warmup done (baseline stored).")

        print(f"[ok] polled {len(events)} events | filtered={len(filtered)} | sent={sent} | {note}")

        if args.once:
            return 0
        time.sleep(max(1.0, args.interval))


if __name__ == "__main__":
    raise SystemExit(main())
