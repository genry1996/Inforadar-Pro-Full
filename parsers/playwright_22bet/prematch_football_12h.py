# -*- coding: utf-8 -*-
"""
22bet / 1xBet mirrors — Football prematch (LineFeed) + MySQL latest + history

What this script does
- Pulls 1x2 via LineFeed Get1x2_VZip (fast)
- Pulls Totals + Handicaps via LineFeed GetGameZip (fast-ish; limited per cycle)
- Saves latest rows + history snapshots only when odds changed

Tables (MySQL, schema auto-created)
- odds_22bet                (latest 1x2)
- odds_22bet_history        (1x2 history)
- odds_22bet_lines          (latest totals + handicaps)
- odds_22bet_lines_history  (totals + handicaps history)

Why your previous run had lines=0
- Many mirrors return GetGameZip payloads that *omit market blocks* unless you pass
  the same query parameters (country/partner/gr/mode/tz/getEmpty/lng) as in Get1x2_VZip.
- This build automatically extracts those parameters from LINEFEED_1X2_URL and merges them into GetGameZip calls.

ENV (.env in this folder or project root)
# MySQL
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=...
MYSQL_DB=inforadar
(or DB_HOST/DB_PORT/DB_USER/DB_PASSWORD/DB_NAME)

# Proxy
PROXY=http://user:pass@ip:port
or
PROXY_SERVER=http://ip:port
PROXY_USERNAME=...
PROXY_PASSWORD=...

# LineFeed (IMPORTANT)
LINEFEED_1X2_URL=...Get1x2_VZip?...   (use the exact URL you captured)
LINEFEED_GAME_URL_TEMPLATE=https://22betluck.com/LineFeed/GetGameZip?id={id}&lng=en_GB

Debug
- Set DEBUG_DUMP_GAMEJSON=1 to dump one GameZip JSON when lines=0
  Output: ./netdump_linefeed/game_<id>.json
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
from urllib.parse import urlsplit, urlunsplit, parse_qs, urlencode

import pymysql
import requests

try:
    from zoneinfo import ZoneInfo  # py3.9+
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore


# ----------------------------
# .env loader (dotenv optional)
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
    project_root = here.parent.parent  # .../parsers/playwright_22bet -> .../Inforadar_Pro
    loaded = False
    for p in (here / ".env", project_root / ".env"):
        loaded = _load_env_file(p, override=False) or loaded
    if loaded:
        print(f"[env] loaded from: {here / '.env'} | {project_root / '.env'}")


load_env_candidates()


def _env(*names: str, default: str = "") -> str:
    for n in names:
        v = (os.getenv(n) or "").strip()
        if v:
            return v
    return default


# ----------------------------
# Models
# ----------------------------

@dataclass
class EventOdds:
    event_id: int
    league: str
    event_name: str
    home_team: Optional[str]
    away_team: Optional[str]
    match_time: Optional[dt.datetime]  # naive local
    odd_1: Optional[float]
    odd_x: Optional[float]
    odd_2: Optional[float]


@dataclass
class LineOdds:
    event_id: int
    league: str
    event_name: str
    match_time: Optional[dt.datetime]  # naive local
    market_type: str        # total | handicap
    line_value: float
    side_1: str            # over/home
    side_2: str            # under/away
    odd_1: Optional[float]
    odd_2: Optional[float]


# ----------------------------
# Time helpers
# ----------------------------

def now_local(tz_name: str) -> dt.datetime:
    if ZoneInfo is None:
        return dt.datetime.now()
    return dt.datetime.now(ZoneInfo(tz_name))


def within_hours(match_time: Optional[dt.datetime], tz_name: str, hours: int) -> bool:
    if match_time is None:
        return False
    now = now_local(tz_name).replace(tzinfo=None)
    return now <= match_time <= (now + dt.timedelta(hours=hours))


# ----------------------------
# Proxy + headers
# ----------------------------

def _proxy_url() -> str:
    p = _env("PROXY", default="")
    if p:
        return p
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


def _base_from_url(url: str) -> str:
    m = re.match(r"^(https?://[^/]+)", url.strip())
    if not m:
        raise ValueError(f"Bad url: {url}")
    return m.group(1)


# --- Filtering helpers (exclude "special bets", team vs player, Home vs Away etc.) ---

_SPECIAL_SUBSTRINGS = [
    "special bet", "special bets", "специальн", "specials",
    "team vs player", "team vs team", "player vs team",
    "winner", "outright", "to win", "champion", "tournament winner",
    "top scorer", "goalscorer", "first goalscorer", "anytime scorer",
    "1st teams vs 2nd teams", "1st team", "2nd team",
]

_GENERIC_TEAMS = {
    "home", "away", "hosts", "guests", "host", "guest",
    "хозяева", "гости", "хозяин", "гость",
}

def _norm_team(x: Optional[str]) -> str:
    if x is None:
        return ""
    s = str(x).strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s

def _is_special_event(league: str, name: str, home: Optional[str], away: Optional[str]) -> bool:
    """Heuristics to keep only real team-vs-team matches."""
    h = _norm_team(home)
    a = _norm_team(away)
    if not h or not a:
        return True
    if h in _GENERIC_TEAMS or a in _GENERIC_TEAMS:
        return True
    # numeric/ID-like "teams" (often outrights)
    if re.fullmatch(r"\d{3,}", h) or re.fullmatch(r"\d{3,}", a):
        return True

    blob = " ".join([str(league or ""), str(name or ""), h, a]).lower()
    if any(ss in blob for ss in _SPECIAL_SUBSTRINGS):
        return True
    # Common explicit markers
    if "(special" in blob or "special)" in blob or "special bets" in blob:
        return True
    if " vs " not in (name or "").lower():
        # Most real matches have "vs" in the name we build
        return True
    return False


def _tune_linefeed_1x2_url(url: str, hours: int) -> str:
    """
    If you paste a captured LINEFEED_1X2_URL, it often contains small tf/count.
    We keep the same host/params, but override:
      - count  (default from LINEFEED_COUNT)
      - tf     (hours window in ms)
    """
    try:
        sp = urlsplit(url)
        qs = parse_qs(sp.query, keep_blank_values=True)
        # override / ensure
        tf = str(max(3_000_000, int(hours) * 3600 * 1000))
        count = _env("LINEFEED_COUNT", default="500") or "500"
        qs["tf"] = [tf]
        qs["count"] = [count]
        # flatten query
        new_q = urlencode({k: v[-1] if isinstance(v, list) else v for k, v in qs.items()})
        return urlunsplit((sp.scheme, sp.netloc, sp.path, new_q, sp.fragment))
    except Exception:
        return url

def _headers(base: str) -> Dict[str, str]:
    # Do NOT request brotli
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "en,ru;q=0.9",
        "Accept-Encoding": "gzip, deflate",
        "Referer": base.rstrip("/") + "/",
        "Origin": base,
        "X-Requested-With": "XMLHttpRequest",
        "Connection": "keep-alive",
    }


# ----------------------------
# VZip decoding + JSON
# ----------------------------

def _decode_vzip_bytes(raw: bytes) -> bytes:
    if not raw:
        return raw

    if raw[:2] == b"VZ":  # some mirrors prefix this
        import zlib
        payload = raw[2:]
        for wbits in (zlib.MAX_WBITS, -zlib.MAX_WBITS, zlib.MAX_WBITS | 16):
            try:
                return zlib.decompress(payload, wbits)
            except Exception:
                pass

    if raw[:2] == b"\x1f\x8b":  # gzip
        import gzip
        return gzip.decompress(raw)

    import zlib
    for wbits in (zlib.MAX_WBITS | 16, zlib.MAX_WBITS, -zlib.MAX_WBITS):
        try:
            return zlib.decompress(raw, wbits)
        except Exception:
            pass

    return raw


def _diag(resp: requests.Response, raw: bytes) -> str:
    ct = resp.headers.get("content-type", "")
    ce = resp.headers.get("content-encoding", "")
    head = raw[:120]
    try:
        preview = head.decode("utf-8", errors="replace").replace("\r", " ").replace("\n", " ")
    except Exception:
        preview = str(head)
    return f"status={resp.status_code} ct={ct} ce={ce} head={preview!r}"


def _safe_json(resp: requests.Response) -> Any:
    try:
        return resp.json()
    except Exception:
        pass

    raw = resp.content or b""
    if raw[:1] == b"<" or b"<html" in raw[:400].lower():
        raise RuntimeError("LineFeed returned HTML (blocked/wrong URL). " + _diag(resp, raw))

    data = _decode_vzip_bytes(raw)
    if data[:1] == b"<" or b"<html" in data[:400].lower():
        raise RuntimeError("LineFeed decode produced HTML (blocked). " + _diag(resp, data))

    try:
        return json.loads(data.decode("utf-8", errors="replace"))
    except Exception as e:
        raise RuntimeError(f"LineFeed decode failed: {e}. " + _diag(resp, data))


# ----------------------------
# JSON traversal helpers
# ----------------------------

def _iter_dicts(obj: Any) -> Iterable[Dict[str, Any]]:
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _iter_dicts(v)
    elif isinstance(obj, list):
        for it in obj:
            yield from _iter_dicts(it)


def _pick(d: Dict[str, Any], keys: List[str]) -> Any:
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return None


def _to_int(x: Any) -> Optional[int]:
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


def _to_float(x: Any) -> Optional[float]:
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


# ----------------------------
# LineFeed param merging (KEY FIX)
# ----------------------------

_KEEP_PARAMS = {
    "lng", "lang", "tz", "tf", "mode", "country", "partner", "gr", "getEmpty", "isSubGames", "subGames"
}

def _extract_params_from_1x2_url(url: str) -> Dict[str, str]:
    """Extract important query params from LINEFEED_1X2_URL to reuse in GetGameZip."""
    try:
        q = parse_qs(urlsplit(url).query, keep_blank_values=True)
        out: Dict[str, str] = {}
        for k, v in q.items():
            if k in _KEEP_PARAMS and v:
                out[k] = str(v[-1])
        return out
    except Exception:
        return {}


def _merge_url_params(url: str, extra: Dict[str, str]) -> str:
    """Add params from extra if not present in url (do not overwrite explicit url params)."""
    try:
        sp = urlsplit(url)
        q = parse_qs(sp.query, keep_blank_values=True)
        for k, v in extra.items():
            if k not in q:
                q[k] = [v]
        new_q = urlencode({k: q[k][-1] for k in q}, doseq=False)
        return urlunsplit((sp.scheme, sp.netloc, sp.path, new_q, sp.fragment))
    except Exception:
        return url


# ----------------------------
# 1x2 extractor
# ----------------------------

def _guess_start_time(game: Dict[str, Any], tz_name: str) -> Optional[dt.datetime]:
    t = _pick(game, ["S", "Start", "StartTime", "TS", "Time", "T", "StartTs"])
    ti = _to_int(t)
    if ti is None:
        return None

    if ti > 10_000_000_000:
        dtu = dt.datetime.utcfromtimestamp(ti / 1000.0)
    elif ti > 1_000_000_000:
        dtu = dt.datetime.utcfromtimestamp(ti)
    else:
        return None

    if ZoneInfo is None:
        return dtu
    return dtu.replace(tzinfo=dt.timezone.utc).astimezone(ZoneInfo(tz_name)).replace(tzinfo=None)


def _build_event_name(game: Dict[str, Any]) -> Tuple[str, Optional[str], Optional[str]]:
    home = _pick(game, ["O1", "Home", "Team1", "HomeTeam", "O1E", "P1", "T1"])
    away = _pick(game, ["O2", "Away", "Team2", "AwayTeam", "O2E", "P2", "T2"])
    hs = str(home).strip() if home is not None else ""
    as_ = str(away).strip() if away is not None else ""
    if hs and as_:
        return f"{hs} vs {as_}", hs, as_
    nm = _pick(game, ["N", "Name", "NM", "GameName", "EN"])
    if nm:
        s = str(nm).strip()
        parts = re.split(r"\s+(?:vs\.?|v\.?|-)\s+", s, flags=re.IGNORECASE)
        if len(parts) >= 2:
            return s, parts[0].strip(), parts[1].strip()
        return s, None, None
    return "Unknown vs Unknown", None, None


def _guess_league(game: Dict[str, Any]) -> str:
    x = _pick(game, ["L", "LE", "League", "LG", "LeagueName", "LName", "CN", "CH", "Champ", "ChampName", "CT", "Tournament", "TN"])
    return str(x).strip() if x else ""


def _extract_1x2_odds(game: Dict[str, Any]) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    odd1 = _to_float(_pick(game, ["C1", "Odd1", "K1", "P1"]))
    oddx = _to_float(_pick(game, ["CX", "OddX", "KX", "PX", "Draw"]))
    odd2 = _to_float(_pick(game, ["C2", "Odd2", "K2", "P2"]))
    if odd1 is not None or oddx is not None or odd2 is not None:
        return odd1, oddx, odd2
    return None, None, None


def fetch_1x2_linefeed(prematch_url: str, tz_name: str, hours: int, timeout: int = 25) -> List[EventOdds]:
    base = _base_from_url(prematch_url)

    url = _env("LINEFEED_1X2_URL", default="").strip()
    if url:
        url = _tune_linefeed_1x2_url(url, hours)
    if not url:
        # best-effort fallback (but you SHOULD set LINEFEED_1X2_URL)
        country = _env("LINEFEED_COUNTRY", default="207")
        partner = _env("LINEFEED_PARTNER", default="151")
        gr = _env("LINEFEED_GR", default=partner)
        lng = _env("LINEFEED_LNG", default="en_GB")
        tz = _env("LINEFEED_TZ", default="3")
        tf = _env("LINEFEED_TF", default=str(max(3_000_000, hours * 3600 * 1000)))
        count = _env("LINEFEED_COUNT", default="200")
        url = (
            f"{base}/LineFeed/Get1x2_VZip?"
            f"sports=1&count={count}&lng={lng}&tf={tf}&tz={tz}&mode=4&country={country}&partner={partner}&getEmpty=true&gr={gr}"
        )

    r = requests.get(url, headers=_headers(base), proxies=_proxies(), timeout=timeout)
    r.raise_for_status()
    data = _safe_json(r)

    games: List[Dict[str, Any]] = []
    for d in _iter_dicts(data):
        gid = _to_int(_pick(d, ["I", "Id", "ID", "GameId", "GI"]))
        if gid is None or gid < 1000:
            continue
        if _pick(d, ["O1", "O2", "O1E", "O2E", "Team1", "Team2", "HomeTeam", "AwayTeam", "T1", "T2", "P1", "P2", "N", "Name", "NM", "EN"]) is None:
            continue
        games.append(d)

    out: List[EventOdds] = []
    seen: set = set()
    for g in games:
        gid = _to_int(_pick(g, ["I", "Id", "ID", "GameId", "GI"]))
        if gid is None or gid in seen:
            continue
        seen.add(gid)

        mt = _guess_start_time(g, tz_name)
        if not within_hours(mt, tz_name, hours):
            continue

        league = _guess_league(g)
        name, home, away = _build_event_name(g)
        if _is_special_event(league, name, home, away):
            continue
        o1, ox, o2 = _extract_1x2_odds(g)

        out.append(EventOdds(gid, league, name, home, away, mt, o1, ox, o2))

    return out


# ----------------------------
# GameZip fetcher (Totals/Handicaps)
# ----------------------------

def _candidate_game_urls(base: str, game_id: int) -> List[str]:
    tpl = _env("LINEFEED_GAME_URL_TEMPLATE", default="").strip()
    lng = _env("LINEFEED_LNG", default="en_GB")
    if tpl:
        return [tpl.format(id=game_id)]
    return [
        f"{base}/LineFeed/GetGameZip?id={game_id}&lng={lng}",
        f"{base}/LineFeed/GetGameZip?gameId={game_id}&lng={lng}",
        f"{base}/LineFeed/GetGameZip?Id={game_id}&lng={lng}",
        f"{base}/LineFeed/GetGame_VZip?id={game_id}&lng={lng}",
        f"{base}/LineFeed/GetGame?id={game_id}&lng={lng}",
        f"{base}/LineFeed/GetGame?gameId={game_id}&lng={lng}",
    ]


def fetch_game_json(base: str, game_id: int, extra_params: Dict[str, str], timeout: int = 25) -> Tuple[Optional[Any], Optional[str]]:
    for raw_url in _candidate_game_urls(base, game_id):
        u = _merge_url_params(raw_url, extra_params)
        try:
            r = requests.get(u, headers=_headers(base), proxies=_proxies(), timeout=timeout)
            if r.status_code != 200:
                continue
            return _safe_json(r), u
        except Exception:
            continue
    return None, None


# ----------------------------
# Market parsing (robust heuristics)
# ----------------------------

_TOTAL_RE = re.compile(r"(?:\bтб\b|\bтм\b|over|under|total|тотал)", re.I)
_HANDI_RE = re.compile(r"(?:\bф1\b|\bф2\b|handicap|фора|h1|h2)", re.I)

def _extract_bet_nodes(game_json: Any) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for d in _iter_dicts(game_json):
        coef = _to_float(_pick(d, ["C", "K", "Coef", "coef", "odd", "odds"]))
        if coef is None:
            continue
        # Keep node if it has some identifying keys
        if _pick(d, ["N", "Name", "NM", "T", "TN", "Type", "G", "Group", "GroupId", "P", "Param", "H", "Handicap", "Total", "Line"]) is None:
            continue
        out.append(d)
    return out


def parse_totals_handicaps(game_json: Any) -> Tuple[Dict[float, Dict[str, Optional[float]]], Dict[float, Dict[str, Optional[float]]]]:
    """
    Returns:
      totals[line]    -> {'over': coef, 'under': coef}
      handicaps[line] -> {'home': coef, 'away': coef}
    """
    totals: Dict[float, Dict[str, Optional[float]]] = {}
    handicaps: Dict[float, Dict[str, Optional[float]]] = {}

    nodes = _extract_bet_nodes(game_json)

    # First pass: detect which "group ids" look like handicap by negative params
    group_params: Dict[int, List[float]] = {}
    for n in nodes:
        gid = _to_int(_pick(n, ["G", "Group", "GroupId", "GI"]))
        pv = _to_float(_pick(n, ["P", "Param", "H", "Handicap", "Total", "Line"]))
        if gid is None or pv is None:
            continue
        group_params.setdefault(gid, []).append(float(pv))

    handicap_groups: set = set()
    for gid, ps in group_params.items():
        if any(p < 0 for p in ps):
            handicap_groups.add(gid)

    for n in nodes:
        coef = _to_float(_pick(n, ["C", "K", "Coef", "coef", "odd", "odds"]))
        if coef is None:
            continue

        name = _pick(n, ["N", "Name", "NM", "TN"])
        name_s = str(name).strip() if isinstance(name, str) else ""
        name_l = name_s.lower()

        param = _pick(n, ["P", "Param", "H", "Handicap", "Total", "Line"])
        lv = _to_float(param)
        if lv is None and name_s:
            m = re.search(r"([+-]?\d+(?:[.,]\d+)?)", name_s)
            if m:
                lv = _to_float(m.group(1))
        if lv is None:
            continue
        lvf = float(lv)

        gid = _to_int(_pick(n, ["G", "Group", "GroupId", "GI"])) or 0
        tcode = _to_int(_pick(n, ["T", "Type", "TT"])) or 0

        # Decide market type
        is_total = bool(name_s and _TOTAL_RE.search(name_s))
        is_hand = bool(name_s and _HANDI_RE.search(name_s))
        if not (is_total or is_hand):
            # fallback by group / param sign
            if gid in handicap_groups or lvf < 0:
                is_hand = True
            else:
                # if group has only positive params -> likely totals on this mirror
                is_total = True

        # Decide side
        if is_total:
            side = None
            if name_s:
                if "тб" in name_l or "over" in name_l or "больше" in name_l:
                    side = "over"
                elif "тм" in name_l or "under" in name_l or "меньше" in name_l:
                    side = "under"
            if side is None:
                # fallback: use tcode ordering (stable)
                # We'll temporarily store into a list then pair later.
                totals.setdefault(lvf, {"over": None, "under": None, "_tmp": []})  # type: ignore
                totals[lvf]["_tmp"].append((tcode, coef))  # type: ignore
            else:
                totals.setdefault(lvf, {"over": None, "under": None})
                totals[lvf][side] = coef
            continue

        if is_hand:
            side = None
            if name_s:
                if "ф1" in name_l or "h1" in name_l or "home" in name_l:
                    side = "home"
                elif "ф2" in name_l or "h2" in name_l or "away" in name_l:
                    side = "away"
            if side is None:
                handicaps.setdefault(lvf, {"home": None, "away": None, "_tmp": []})  # type: ignore
                handicaps[lvf]["_tmp"].append((tcode, coef))  # type: ignore
            else:
                handicaps.setdefault(lvf, {"home": None, "away": None})
                handicaps[lvf][side] = coef
            continue

    # Pair tmp lists (when labels weren't informative)
    def _pair_tmp(d: Dict[float, Dict[str, Any]], a: str, b: str) -> Dict[float, Dict[str, Optional[float]]]:
        out2: Dict[float, Dict[str, Optional[float]]] = {}
        for lv, row in d.items():
            tmp = row.pop("_tmp", None)  # type: ignore
            if tmp and (row.get(a) is None or row.get(b) is None):
                tmp_sorted = sorted(tmp, key=lambda x: x[0])
                if len(tmp_sorted) >= 2:
                    row[a] = row.get(a) if row.get(a) is not None else tmp_sorted[0][1]
                    row[b] = row.get(b) if row.get(b) is not None else tmp_sorted[1][1]
                elif len(tmp_sorted) == 1:
                    # put into first side only
                    row[a] = row.get(a) if row.get(a) is not None else tmp_sorted[0][1]
            out2[lv] = {"%s" % a: row.get(a), "%s" % b: row.get(b)}
        return out2

    totals2 = _pair_tmp(totals, "over", "under")
    handicaps2 = _pair_tmp(handicaps, "home", "away")
    return totals2, handicaps2


# ----------------------------
# MySQL schema + writes
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


def _column_exists(cur, table: str, col: str) -> bool:
    cur.execute(
        "SELECT COUNT(*) c FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s AND COLUMN_NAME=%s",
        (table, col),
    )
    return (cur.fetchone() or {}).get("c", 0) > 0


def _index_exists(cur, table: str, index_name: str) -> bool:
    cur.execute(
        "SELECT COUNT(*) c FROM INFORMATION_SCHEMA.STATISTICS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s AND INDEX_NAME=%s",
        (table, index_name),
    )
    return (cur.fetchone() or {}).get("c", 0) > 0


def ensure_schema(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS odds_22bet (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                bookmaker VARCHAR(50) NOT NULL,
                sport VARCHAR(50) NOT NULL,
                league VARCHAR(255) NULL,
                event_name VARCHAR(512) NOT NULL,
                market_type VARCHAR(50) NOT NULL DEFAULT '1x2',
                odd_1 DECIMAL(10,3) NULL,
                odd_x DECIMAL(10,3) NULL,
                odd_2 DECIMAL(10,3) NULL,
                match_time DATETIME NULL,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
            """
        )

        if not _column_exists(cur, "odds_22bet", "event_id"):
            cur.execute("ALTER TABLE odds_22bet ADD COLUMN event_id BIGINT NULL AFTER event_name")
        if not _column_exists(cur, "odds_22bet", "home_team"):
            cur.execute("ALTER TABLE odds_22bet ADD COLUMN home_team VARCHAR(255) NULL AFTER event_id")
        if not _column_exists(cur, "odds_22bet", "away_team"):
            cur.execute("ALTER TABLE odds_22bet ADD COLUMN away_team VARCHAR(255) NULL AFTER home_team")
        if not _index_exists(cur, "odds_22bet", "uk_odds_22bet_event_market"):
            cur.execute("CREATE UNIQUE INDEX uk_odds_22bet_event_market ON odds_22bet(event_id, market_type, bookmaker, sport)")

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS odds_22bet_history (
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
                INDEX idx_hist_event_time (event_id, captured_at),
                INDEX idx_hist_event_market (event_id, market_type)
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS odds_22bet_lines (
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
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
            """
        )
        if not _index_exists(cur, "odds_22bet_lines", "uk_lines_event_market_line"):
            cur.execute("CREATE UNIQUE INDEX uk_lines_event_market_line ON odds_22bet_lines(event_id, market_type, line_value, bookmaker, sport)")

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS odds_22bet_lines_history (
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
                INDEX idx_lines_hist_event_time (event_id, captured_at),
                INDEX idx_lines_hist_event_market (event_id, market_type)
            ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
            """
        )


def _eq(a, b) -> bool:
    try:
        return (a is None and b is None) or (a is not None and b is not None and float(a) == float(b))
    except Exception:
        return False


def upsert_1x2(conn, ev: EventOdds) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO odds_22bet (event_id, bookmaker, sport, league, event_name, home_team, away_team, market_type,
                                   odd_1, odd_x, odd_2, match_time)
            VALUES (%s,'22bet','Football',%s,%s,%s,%s,'1x2',%s,%s,%s,%s)
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


def hist_1x2_if_changed(conn, ev: EventOdds) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT odd_1, odd_x, odd_2
            FROM odds_22bet_history
            WHERE event_id=%s AND bookmaker='22bet' AND sport='Football' AND market_type='1x2'
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
            INSERT INTO odds_22bet_history (event_id, bookmaker, sport, league, event_name, market_type, odd_1, odd_x, odd_2, match_time)
            VALUES (%s,'22bet','Football',%s,%s,'1x2',%s,%s,%s,%s)
            """,
            (ev.event_id, ev.league or None, ev.event_name, ev.odd_1, ev.odd_x, ev.odd_2, ev.match_time),
        )


def upsert_line(conn, ln: LineOdds) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO odds_22bet_lines (event_id, bookmaker, sport, league, event_name, market_type, line_value, side_1, side_2,
                                         odd_1, odd_2, match_time)
            VALUES (%s,'22bet','Football',%s,%s,%s,%s,%s,%s,%s,%s,%s)
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


def hist_line_if_changed(conn, ln: LineOdds) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT odd_1, odd_2
            FROM odds_22bet_lines_history
            WHERE event_id=%s AND bookmaker='22bet' AND sport='Football' AND market_type=%s AND line_value=%s
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
            INSERT INTO odds_22bet_lines_history (event_id, bookmaker, sport, league, event_name, market_type, line_value,
                                                 side_1, side_2, odd_1, odd_2, match_time)
            VALUES (%s,'22bet','Football',%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (ln.event_id, ln.league or None, ln.event_name, ln.market_type, ln.line_value, ln.side_1, ln.side_2, ln.odd_1, ln.odd_2, ln.match_time),
        )


def last_lines_updated_at(conn, event_id: int) -> Optional[dt.datetime]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT MAX(updated_at) t FROM odds_22bet_lines WHERE event_id=%s AND bookmaker='22bet' AND sport='Football'",
            (event_id,),
        )
        row = cur.fetchone() or {}
        return row.get("t")


# ----------------------------
# Debug dump
# ----------------------------

def _maybe_dump_game_json(game_id: int, game_json: Any) -> None:
    if (_env("DEBUG_DUMP_GAMEJSON", default="0") or "").strip() not in ("1", "true", "TRUE", "yes", "YES"):
        return
    outdir = Path(__file__).resolve().parent / "netdump_linefeed"
    outdir.mkdir(parents=True, exist_ok=True)
    fp = outdir / f"game_{game_id}.json"
    try:
        fp.write_text(json.dumps(game_json, ensure_ascii=False), encoding="utf-8")
        print(f"🧾 dumped game json: {fp}")
    except Exception:
        pass


# ----------------------------
# Main loop
# ----------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True, help="Prematch football page URL (mirror)")
    ap.add_argument("--tz", default="Europe/Paris")
    ap.add_argument("--hours", type=int, default=12)
    ap.add_argument("--interval", type=int, default=60)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--markets-max-events", type=int, default=25)
    ap.add_argument("--markets-stale-sec", type=int, default=300)
    args = ap.parse_args()

    base = _base_from_url(args.url)

    # Key fix: reuse params from LINEFEED_1X2_URL in GetGameZip
    p1x2 = _env("LINEFEED_1X2_URL", default="").strip()
    extra_params = _extract_params_from_1x2_url(p1x2) if p1x2 else {}

    print(f"⚽ 22bet PREMATCH Football | LineFeed | window={args.hours}h | interval={args.interval}s | tz={args.tz}")
    print(f"🌍 Proxy: {_proxy_url() or 'none'}")
    if extra_params:
        print(f"🔧 GameZip params inherited: {', '.join(sorted(extra_params.keys()))}")

    conn = mysql_connect()
    ensure_schema(conn)
    print("✅ MySQL connected")

    warned = False

    while True:
        started = time.time()
        try:
            events = fetch_1x2_linefeed(args.url, tz_name=args.tz, hours=args.hours)

            for ev in events:
                upsert_1x2(conn, ev)
                hist_1x2_if_changed(conn, ev)

            # choose which events to refresh markets for
            now_naive = now_local(args.tz).replace(tzinfo=None)
            candidates: List[EventOdds] = []
            for ev in events:
                if ev.match_time is None:
                    continue
                if not (now_naive <= ev.match_time <= now_naive + dt.timedelta(hours=args.hours)):
                    continue
                last = last_lines_updated_at(conn, ev.event_id)
                if last is None:
                    candidates.append(ev)
                else:
                    age = (now_naive - last).total_seconds()
                    if age >= args.markets_stale_sec:
                        candidates.append(ev)

            def key_fn(e: EventOdds):
                t = last_lines_updated_at(conn, e.event_id)
                return t or dt.datetime(1970, 1, 1)

            candidates.sort(key=key_fn)
            candidates = candidates[: max(0, args.markets_max_events)]

            lines_saved = 0
            ok = 0
            fail = 0
            first_endpoint: Optional[str] = None
            dumped = False

            for ev in candidates:
                game_json, used = fetch_game_json(base, ev.event_id, extra_params=extra_params)
                if game_json is None:
                    fail += 1
                    continue

                if used and first_endpoint is None:
                    first_endpoint = used

                totals, handicaps = parse_totals_handicaps(game_json)

                if (not totals) and (not handicaps) and (not dumped):
                    _maybe_dump_game_json(ev.event_id, game_json)
                    dumped = True

                for lv, d in totals.items():
                    ln = LineOdds(ev.event_id, ev.league, ev.event_name, ev.match_time, "total", float(lv), "over", "under", d.get("over"), d.get("under"))
                    upsert_line(conn, ln)
                    hist_line_if_changed(conn, ln)
                    lines_saved += 1

                for lv, d in handicaps.items():
                    ln = LineOdds(ev.event_id, ev.league, ev.event_name, ev.match_time, "handicap", float(lv), "home", "away", d.get("home"), d.get("away"))
                    upsert_line(conn, ln)
                    hist_line_if_changed(conn, ln)
                    lines_saved += 1

                ok += 1

            dt_s = time.time() - started
            if first_endpoint:
                print(f"ℹ️ markets endpoint: {first_endpoint}")
            print(f"✅ Saved: 1x2={len(events)} | lines(total+handicap)={lines_saved} | markets_ok={ok} fail={fail} | {dt_s:.1f}s")

            if len(events) > 0 and ok > 0 and lines_saved == 0 and not warned:
                print("⚠️ Lines parsed=0. Set DEBUG_DUMP_GAMEJSON=1 to dump a GameZip payload for exact parsing.")
                warned = True

        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"[ERR] {e}")

        if args.once:
            break

        sleep_for = max(1, args.interval - int(time.time() - started))
        print(f"⏳ Waiting {sleep_for}s...")
        time.sleep(sleep_for)

    try:
        conn.close()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
