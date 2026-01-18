from __future__ import annotations

import os
import time
import json
import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests
import pymysql
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


# ----------------------------
# .env loader (без зависимостей)
# ----------------------------
def load_env(repo_root: Path) -> List[str]:
    loaded: List[str] = []

    def _load(path: Path) -> bool:
        if not path.exists():
            return False
        raw = path.read_text(encoding="utf-8-sig", errors="ignore")
        for line in raw.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip()

            if len(v) >= 2 and ((v[0] == v[-1] == '"') or (v[0] == v[-1] == "'")):
                v = v[1:-1]

            if os.environ.get(k) is None:
                os.environ[k] = v
        return True

    root_env = repo_root / ".env"
    cwd_env = Path.cwd() / ".env"

    if _load(root_env):
        loaded.append(str(root_env))
    if cwd_env != root_env and _load(cwd_env):
        loaded.append(str(cwd_env))

    return loaded


def env(name: str, default: str = "") -> str:
    return (os.getenv(name, default) or "").strip()


# ----------------------------
# Proxy (как у тебя в .env)
# ----------------------------
def build_proxy_dict() -> Optional[Dict[str, str]]:
    server = env("FONBET_PROXY_SERVER")
    user = env("FONBET_PROXY_USERNAME")
    pwd = env("FONBET_PROXY_PASSWORD")
    if not server:
        return None

    p = urlparse(server)
    if user and pwd and p.scheme and p.hostname and p.port:
        proxy_url = f"{p.scheme}://{user}:{pwd}@{p.hostname}:{p.port}"
    else:
        proxy_url = server

    return {"http": proxy_url, "https": proxy_url}


# ----------------------------
# Config
# ----------------------------
@dataclass
class FonbetCfg:
    lang: str = "ru"
    scope_market: int = 1700
    line_hosts: Tuple[str, ...] = (
        "https://line01.cy8cff-resources.com",
        "https://line02.cy8cff-resources.com",
    )
    odds_divisor: int = 1000


# ----------------------------
# Requests session (retry + timeouts)
# ----------------------------
def build_session(
    lang: str,
    proxies: Optional[Dict[str, str]],
    retries: int,
    backoff: float,
) -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "Accept": "application/json, text/plain, */*",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
        ),
        "Accept-Language": f"{lang},en;q=0.8",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Connection": "keep-alive",
    })
    if proxies:
        s.proxies.update(proxies)

    retry = Retry(
        total=retries,
        connect=retries,
        read=retries,
        status=retries,
        backoff_factor=backoff,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
        raise_on_status=False,
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=50, pool_maxsize=50)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    return s


# ----------------------------
# API calls
# ----------------------------
def pick_line_base(cfg: FonbetCfg, s: requests.Session, timeout: Tuple[float, float]) -> str:
    for base in cfg.line_hosts:
        try:
            r = s.get(f"{base}/getApiState", timeout=timeout)
            if r.status_code == 200:
                return base
        except Exception:
            continue
    return cfg.line_hosts[0]


def get_list_base(cfg: FonbetCfg, s: requests.Session, base: str, timeout: Tuple[float, float]) -> Dict[str, Any]:
    r = s.get(
        f"{base}/events/listBase",
        params={"lang": cfg.lang, "scopeMarket": str(cfg.scope_market)},
        timeout=timeout,
    )
    r.raise_for_status()
    return r.json()


def get_list(cfg: FonbetCfg, s: requests.Session, base: str, version: int, timeout: Tuple[float, float]) -> Dict[str, Any]:
    r = s.get(
        f"{base}/events/list",
        params={"lang": cfg.lang, "version": str(int(version)), "scopeMarket": str(cfg.scope_market)},
        timeout=timeout,
    )
    r.raise_for_status()
    return r.json()


def get_packet_version(payload: Dict[str, Any]) -> int:
    for k in ("packetVersion", "version", "pv"):
        v = payload.get(k)
        if isinstance(v, int):
            return v
        if isinstance(v, str) and v.isdigit():
            return int(v)
    return 0


def extract_events(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    if isinstance(payload.get("events"), list):
        return payload["events"]
    if isinstance(payload.get("data"), dict) and isinstance(payload["data"].get("events"), list):
        return payload["data"]["events"]
    return []


# ----------------------------
# Normalizers
# ----------------------------
def to_epoch_sec(x: Any) -> Optional[int]:
    if x is None:
        return None
    if isinstance(x, (int, float)):
        v = int(x)
        if v > 10_000_000_000:  # ms -> sec
            v //= 1000
        return v
    return None


def norm_odd(val: Any, divisor: int) -> Optional[float]:
    if val is None:
        return None
    if isinstance(val, float):
        return float(val)
    if isinstance(val, int):
        if divisor and val >= divisor:
            return val / float(divisor)
        return float(val)
    if isinstance(val, str):
        try:
            return float(val.replace(",", "."))
        except Exception:
            return None
    return None


def norm_param(val: Any) -> Optional[float]:
    """Normalize numeric line/parameter (handicap/total) if present."""
    if val is None:
        return None
    if isinstance(val, float):
        return float(val)
    if isinstance(val, int):
        return float(val)
    if isinstance(val, str):
        s = val.strip().replace(",", ".")
        # Allow strings like '+1.5' or '-2'
        try:
            return float(s)
        except Exception:
            return None
    return None


def norm_label(val: Any, max_len: int = 255) -> Optional[str]:
    if val is None:
        return None
    try:
        s = str(val).strip()
    except Exception:
        return None
    if not s:
        return None
    if len(s) > max_len:
        s = s[:max_len]
    return s

def extract_event_id(e: Dict[str, Any]) -> Optional[int]:
    for k in ("id", "eventId", "event_id", "e"):
        v = e.get(k)
        if isinstance(v, int):
            return v
        if isinstance(v, str) and v.isdigit():
            return int(v)
    return None


def extract_teams(e: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    t1 = e.get("team1") or e.get("home") or e.get("homeTeam") or e.get("team1Name")
    t2 = e.get("team2") or e.get("away") or e.get("awayTeam") or e.get("team2Name")
    if isinstance(t1, dict):
        t1 = t1.get("name")
    if isinstance(t2, dict):
        t2 = t2.get("name")
    return (t1 if isinstance(t1, str) else None, t2 if isinstance(t2, str) else None)


def extract_factors_from_event(e: Dict[str, Any]) -> List[Tuple[int, Any, Any, Any]]:
    """Extract factors from an event in listBase payload.

    Returns tuples: (factor_id, raw_odd_value, raw_param_value, raw_label)
      - raw_odd_value is usually f['v'] (or f['value'])
      - raw_param_value is usually f['p'] for totals/handicaps (may be absent)
      - raw_label is optional text label/name/title if present (may be absent)
    """
    factors = e.get("factors")
    out: List[Tuple[int, Any, Any, Any]] = []
    if not isinstance(factors, list):
        return out
    for f in factors:
        if not isinstance(f, dict):
            continue
        fid = f.get("f") or f.get("id") or f.get("factorId")
        raw_odd = f.get("v")
        if raw_odd is None:
            raw_odd = f.get("value") or f.get("odd")
        raw_param = f.get("p")
        if raw_param is None:
            raw_param = f.get("param") or f.get("line")
        raw_label = (
            f.get("t")
            or f.get("title")
            or f.get("name")
            or f.get("caption")
            or f.get("label")
        )

        if isinstance(fid, str) and fid.isdigit():
            fid = int(fid)
        if isinstance(fid, int):
            out.append((fid, raw_odd, raw_param, raw_label))
    return out
    for f in factors:
        if not isinstance(f, dict):
            continue
        fid = f.get("f") or f.get("id") or f.get("factorId")
        val = f.get("v") or f.get("value") or f.get("p")
        if isinstance(fid, str) and fid.isdigit():
            fid = int(fid)
        if isinstance(fid, int):
            out.append((fid, val))
    return out


def extract_payload_factor_triplets(payload: Dict[str, Any]) -> List[Tuple[int, int, Any, Any, Any]]:
    """
    Частый формат у Fonbet:
      { "e": <event_id>, "factors": [ {"f": <factor_id>, "v": <odd>, "p": <param?>}, ... ] }
    Возвращает (event_id, factor_id, raw_odd, raw_param, raw_label)
    """
    out: List[Tuple[int, int, Any, Any, Any]] = []

    def consume_list(lst: Any) -> None:
        if not isinstance(lst, list) or not lst:
            return
        if not isinstance(lst[0], dict):
            return
        sample = lst[0]
        if "factors" not in sample:
            return

        for item in lst:
            if not isinstance(item, dict):
                continue
            eid = item.get("e") or item.get("eventId") or item.get("event_id")
            if isinstance(eid, str) and eid.isdigit():
                eid = int(eid)
            if not isinstance(eid, int):
                continue
            factors = item.get("factors")
            if not isinstance(factors, list):
                continue
            for f in factors:
                if not isinstance(f, dict):
                    continue
                fid = f.get("f") or f.get("id") or f.get("factorId")
                raw_odd = f.get("v")
                if raw_odd is None:
                    raw_odd = f.get("value") or f.get("odd")
                raw_param = f.get("p")
                if raw_param is None:
                    raw_param = f.get("param") or f.get("line")
                raw_label = (
                    f.get("t")
                    or f.get("title")
                    or f.get("name")
                    or f.get("caption")
                    or f.get("label")
                )

                if isinstance(fid, str) and fid.isdigit():
                    fid = int(fid)
                if isinstance(fid, int):
                    out.append((eid, fid, raw_odd, raw_param, raw_label))

    for key in ("customFactors", "eventFactors", "eventFactorList", "factors", "eventFactor"):
        if key in payload:
            consume_list(payload.get(key))

    for v in payload.values():
        consume_list(v)

    data = payload.get("data")
    if isinstance(data, dict):
        for v in data.values():
            consume_list(v)

    return out


# ----------------------------
# Catalog (sport tree) helpers
# ----------------------------
def _walk(obj: Any, cb) -> None:
    if isinstance(obj, dict):
        cb(obj)
        for v in obj.values():
            _walk(v, cb)
    elif isinstance(obj, list):
        for v in obj:
            _walk(v, cb)


def extract_catalog_nodes(payload: Dict[str, Any]) -> Dict[int, Tuple[Optional[int], str]]:
    """
    Пробуем вытащить дерево каталога из listBase:
      node_id -> (parent_id, name)
    """
    nodes: Dict[int, Tuple[Optional[int], str]] = {}

    def cb(d: Any) -> None:
        if not isinstance(d, dict):
            return
        _id = d.get("id")
        name = d.get("name")
        if isinstance(_id, str) and _id.isdigit():
            _id = int(_id)
        if not isinstance(_id, int):
            return
        if not isinstance(name, str) or not name.strip():
            return

        # избегаем "event-like" объектов
        if any(k in d for k in ("team1", "team2", "homeTeam", "awayTeam", "factors", "factorId", "startTime", "eventId")):
            return

        parent = None
        for pk in ("parentId", "parent_id", "pid", "parent", "parentID"):
            if pk in d:
                parent = d.get(pk)
                break
        if isinstance(parent, str) and parent.isdigit():
            parent = int(parent)
        if parent is not None and not isinstance(parent, int):
            parent = None

        nodes.setdefault(_id, (parent, name.strip()))

    _walk(payload, cb)
    return nodes


def resolve_root(node_id: int, nodes: Dict[int, Tuple[Optional[int], str]]) -> Tuple[int, Optional[str]]:
    cur = node_id
    seen = set()
    while True:
        if cur in seen:
            return (node_id, None)
        seen.add(cur)

        if cur not in nodes:
            return (node_id, None)

        parent, name = nodes[cur]
        if parent in (None, 0, cur) or parent not in nodes:
            return (cur, name)
        cur = parent


def find_root_ids_by_name(nodes: Dict[int, Tuple[Optional[int], str]], needle: str) -> List[int]:
    n = needle.lower()
    return [nid for nid, (_, name) in nodes.items() if isinstance(name, str) and n in name.lower()]


# ----------------------------
# MySQL
# ----------------------------

# ----------------------------
# Factor catalog helpers (factor_id -> name/raw_json)
# ----------------------------
def _as_int(x: Any) -> Optional[int]:
    try:
        if isinstance(x, bool):
            return None
        if isinstance(x, int):
            return x
        if isinstance(x, float):
            return int(x)
        if isinstance(x, str) and x.strip().isdigit():
            return int(x.strip())
    except Exception:
        return None
    return None


def extract_factor_catalog_entries(payload: Any, max_nodes: int = 300_000) -> Dict[int, Tuple[str, str]]:
    """
    Пытаемся достать справочник факторов (factor_id -> name, raw_json) из listBase/list.
    Fonbet иногда кладёт его в массивы вида:
      - customFactors / factors / factorCatalog / ... (или любые ключи содержащие 'factor')
    или в словари, где у объектов есть factorId/f/id + name/title/caption/text.

    Возвращаем dict: {factor_id: (name, raw_json_str)}.
    """
    out: Dict[int, Tuple[str, str]] = {}
    seen = 0

    def dump_obj(o: Any) -> str:
        try:
            return json.dumps(o, ensure_ascii=False, separators=(",", ":"), default=str)
        except Exception:
            return str(o)

    def add_one(fid: Any, name: Any, raw_obj: Any) -> None:
        fid_i = _as_int(fid)
        if not fid_i or fid_i <= 0:
            return
        if not isinstance(name, str):
            try:
                name_s = str(name)
            except Exception:
                return
        else:
            name_s = name
        name_s = name_s.strip()
        if not name_s:
            return
        if fid_i not in out:
            out[fid_i] = (name_s, dump_obj(raw_obj))

    stack: List[Tuple[Any, str]] = [(payload, "")]
    while stack:
        node, pkey = stack.pop()
        seen += 1
        if seen > max_nodes:
            break

        if isinstance(node, dict):
            # 1) Частый вариант: под ключом содержащим 'factor' лежит список справочника
            for k, v in node.items():
                lk = str(k).lower()
                if isinstance(v, list) and ("factor" in lk or lk in ("factors", "customfactors")):
                    for item in v:
                        if not isinstance(item, dict):
                            continue
                        # в справочниках часто id + name
                        fid = (
                            item.get("factorId")
                            or item.get("factor_id")
                            or item.get("factor")
                            or item.get("f")
                            or item.get("id")
                        )
                        nm = item.get("name") or item.get("title") or item.get("caption") or item.get("text")
                        add_one(fid, nm, item)

                # рекурсивно
                if isinstance(v, (dict, list)):
                    stack.append((v, lk))

            # 2) Общий вариант: dict содержит factorId/f + name/title/caption
            fid = node.get("factorId") or node.get("factor_id") or node.get("factor")
            if fid is None and isinstance(pkey, str) and ("factor" in pkey):
                # иногда справочник лежит как список, а элементы имеют id+name
                fid = node.get("id")
            if fid is None:
                fid = node.get("f")  # на всякий случай

            nm = node.get("name") or node.get("title") or node.get("caption") or node.get("text") or node.get("label")
            # важно: не добавляем ноды без явного имени
            if fid is not None and nm is not None:
                add_one(fid, nm, node)

        elif isinstance(node, list):
            for item in node:
                if isinstance(item, (dict, list)):
                    stack.append((item, pkey))

    return out


def upsert_factor_catalog(cur, entries: Dict[int, Tuple[str, str]]) -> int:
    if not entries:
        return 0

    rows = [(int(fid), name, raw) for fid, (name, raw) in entries.items()]
    # батчим, чтобы не словить huge packet / long query
    sql = (
        "INSERT INTO fonbet_factor_catalog (factor_id, name, raw_json) "
        "VALUES (%s,%s,%s) "
        "ON DUPLICATE KEY UPDATE "
        "name=VALUES(name), raw_json=VALUES(raw_json), updated_at=CURRENT_TIMESTAMP"
    )

    total = 0
    batch = 1000
    for i in range(0, len(rows), batch):
        cur.executemany(sql, rows[i : i + batch])
        total += len(rows[i : i + batch])
    return total


def mysql_conn():
    host = env("MYSQL_HOST") or env("DB_HOST") or "127.0.0.1"
    port_s = env("MYSQL_PORT") or env("DB_PORT") or "3306"
    user = env("MYSQL_USER") or env("DB_USER") or "root"
    password = env("MYSQL_PASSWORD") or env("DB_PASSWORD") or ""
    database = env("MYSQL_DB") or env("MYSQL_DATABASE") or env("DB_NAME") or "inforadar"

    try:
        port = int(float(str(port_s).strip()))
    except Exception:
        port = 3306

    src = "MYSQL_*" if env("MYSQL_PASSWORD") else ("DB_*" if env("DB_PASSWORD") else "defaults")
    print(f"[db] host={host} port={port} user={user} db={database} pass_len={len(password)} source={src}")

    if not password:
        raise RuntimeError("MySQL password empty. Set MYSQL_PASSWORD (or DB_PASSWORD) in .env")

    return pymysql.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        database=database,
        charset="utf8mb4",
        autocommit=True,
        cursorclass=pymysql.cursors.DictCursor,
    )



def _table_has_col(cur, table: str, col: str) -> bool:
    cur.execute(
        "SELECT COUNT(*) c FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s AND COLUMN_NAME=%s",
        (table, col),
    )
    r = cur.fetchone()
    return bool(r and int(r.get("c", 0)) > 0)


def upsert_events(cur, rows: List[Dict[str, Any]], has_category_id: bool) -> None:
    if not rows:
        return

    if has_category_id:
        sql = """
        INSERT INTO fonbet_events (event_id, sport_id, category_id, league_id, league_name, team1, team2, start_ts, state)
        VALUES (%(event_id)s, %(sport_id)s, %(category_id)s, %(league_id)s, %(league_name)s, %(team1)s, %(team2)s, %(start_ts)s, %(state)s)
        ON DUPLICATE KEY UPDATE
          sport_id=VALUES(sport_id),
          category_id=VALUES(category_id),
          league_id=VALUES(league_id),
          league_name=VALUES(league_name),
          team1=VALUES(team1),
          team2=VALUES(team2),
          start_ts=VALUES(start_ts),
          state=VALUES(state);
        """
    else:
        sql = """
        INSERT INTO fonbet_events (event_id, sport_id, league_id, league_name, team1, team2, start_ts, state)
        VALUES (%(event_id)s, %(sport_id)s, %(league_id)s, %(league_name)s, %(team1)s, %(team2)s, %(start_ts)s, %(state)s)
        ON DUPLICATE KEY UPDATE
          sport_id=VALUES(sport_id),
          league_id=VALUES(league_id),
          league_name=VALUES(league_name),
          team1=VALUES(team1),
          team2=VALUES(team2),
          start_ts=VALUES(start_ts),
          state=VALUES(state);
        """
    cur.executemany(sql, rows)


def load_existing_odds(cur, event_ids: List[int]) -> Dict[Tuple[int, int], float]:
    if not event_ids:
        return {}
    existing: Dict[Tuple[int, int], float] = {}
    chunk = 400
    for i in range(0, len(event_ids), chunk):
        part = event_ids[i:i + chunk]
        ph = ",".join(["%s"] * len(part))
        cur.execute(f"SELECT event_id, factor_id, odd FROM fonbet_odds WHERE event_id IN ({ph})", part)
        for r in cur.fetchall():
            if r["odd"] is not None:
                existing[(int(r["event_id"]), int(r["factor_id"]))] = float(r["odd"])
    return existing


def upsert_odds_and_history(
    cur,
    odds_rows: List[Tuple[int, int, Optional[float], Optional[float], Optional[str]]],
    existing: Dict[Tuple[int, int], float],
    has_hist_param: bool = False,
    has_hist_label: bool = False,
) -> int:
    """Upsert latest odds into fonbet_odds and append changes into fonbet_odds_history.

    We only *require* (event_id, factor_id, odd). If DB has extra columns:
      - fonbet_odds_history.param  (DOUBLE)  -> save normalized line/handicap/total
      - fonbet_odds_history.label  (VARCHAR) -> save factor label if present
    """
    if not odds_rows:
        return 0

    cur.executemany(
        "INSERT INTO fonbet_odds (event_id, factor_id, odd) VALUES (%s,%s,%s) "
        "ON DUPLICATE KEY UPDATE odd=VALUES(odd)",
        [(e, f, o) for (e, f, o, _p, _lbl) in odds_rows],
    )

    hist_rows = []
    for (e, f, o, p, lbl) in odds_rows:
        if o is None:
            continue
        prev = existing.get((e, f))
        if prev is None or abs(prev - o) > 1e-9:
            if has_hist_param and has_hist_label:
                hist_rows.append((e, f, o, p, lbl))
            elif has_hist_param:
                hist_rows.append((e, f, o, p))
            elif has_hist_label:
                hist_rows.append((e, f, o, lbl))
            else:
                hist_rows.append((e, f, o))

    if hist_rows:
        if has_hist_param and has_hist_label:
            sql = "INSERT INTO fonbet_odds_history (event_id, factor_id, odd, param, label) VALUES (%s,%s,%s,%s,%s)"
        elif has_hist_param:
            sql = "INSERT INTO fonbet_odds_history (event_id, factor_id, odd, param) VALUES (%s,%s,%s,%s)"
        elif has_hist_label:
            sql = "INSERT INTO fonbet_odds_history (event_id, factor_id, odd, label) VALUES (%s,%s,%s,%s)"
        else:
            sql = "INSERT INTO fonbet_odds_history (event_id, factor_id, odd) VALUES (%s,%s,%s)"

        cur.executemany(sql, hist_rows)

    return len(hist_rows)


# ----------------------------
# Main
# ----------------------------
def main():
    repo_root = Path(__file__).resolve().parents[2]  # D:\Inforadar_Pro
    loaded = load_env(repo_root)
    if loaded:
        print("[env] loaded from:", " | ".join(loaded))

    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", default=env("FONBET_LANG", "ru"))
    ap.add_argument("--scope-market", type=int, default=int(env("FONBET_SCOPE_MARKET", "1700")))
    ap.add_argument("--interval", type=float, default=float(env("FONBET_INTERVAL_SEC", env("FONBET_INTERVAL", "10"))))
    ap.add_argument("--hours", type=float, default=float(env("FONBET_HOURS", "12")))
    ap.add_argument("--only-football", action="store_true", default=env("FONBET_ONLY_FOOTBALL", "0").lower() in ("1", "true", "yes"))
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--dump", action="store_true")

    ap.add_argument("--connect-timeout", type=float, default=float(env("FONBET_CONNECT_TIMEOUT", "5")))
    ap.add_argument("--read-timeout", type=float, default=float(env("FONBET_READ_TIMEOUT", "25")))
    ap.add_argument("--retries", type=int, default=int(env("FONBET_RETRIES", "2")))
    ap.add_argument("--backoff", type=float, default=float(env("FONBET_BACKOFF", "0.5")))
    ap.add_argument("--failover-cooldown", type=float, default=float(env("FONBET_FAILOVER_COOLDOWN", "1.0")))
    args = ap.parse_args()

    timeout = (float(args.connect_timeout), float(args.read_timeout))

    cfg = FonbetCfg(lang=args.lang, scope_market=args.scope_market)

    proxies = build_proxy_dict()
    s = build_session(cfg.lang, proxies, retries=int(args.retries), backoff=float(args.backoff))

    bases = list(cfg.line_hosts)
    base_idx = 0

    def current_base() -> str:
        return bases[base_idx]

    def rotate_base() -> str:
        nonlocal base_idx
        base_idx = (base_idx + 1) % len(bases)
        return bases[base_idx]

    base = pick_line_base(cfg, s, timeout=timeout)
    if base in bases:
        base_idx = bases.index(base)

    print(f"🏁 Fonbet PREMATCH | base={current_base()} | scopeMarket={cfg.scope_market} | interval={args.interval}s")

    conn = mysql_conn()
    try:
        with conn.cursor() as _cur:
            _cur.execute("SELECT @@hostname AS hostname, @@port AS port, DATABASE() AS db")
            _info = _cur.fetchone() or {}
        print(f"[db] connected: hostname={_info.get('hostname')} port={_info.get('port')} db={_info.get('db')}")
    except Exception as e:
        print(f"[db] connected: (cannot read server info: {type(e).__name__}: {e})")

    with conn:
        with conn.cursor() as cur:
            has_category_id = _table_has_col(cur, "fonbet_events", "category_id")
            has_hist_param = _table_has_col(cur, "fonbet_odds_history", "param")
            has_hist_label = _table_has_col(cur, "fonbet_odds_history", "label")
            if not has_category_id:
                print("⚠️ fonbet_events.category_id not found — будет старый режим без category_id")

            # listBase + catalog mapping
            try:
                lb = get_list_base(cfg, s, current_base(), timeout=timeout)
                version = get_packet_version(lb)
                print(f"ℹ️ listBase version={version}")
            except Exception as e:
                print(f"❌ listBase failed on {current_base()}: {e}")
                rotate_base()
                time.sleep(max(0.1, float(args.failover_cooldown)))
                lb = get_list_base(cfg, s, current_base(), timeout=timeout)
                version = get_packet_version(lb)
                print(f"ℹ️ listBase version={version}")

            catalog_nodes = extract_catalog_nodes(lb)

            # факторный справочник (factor_id -> name/raw_json). Нужен UI для 1X2/фора/тотал.
            factor_catalog_loaded = False
            try:
                fc = extract_factor_catalog_entries(lb)
                n_fc = upsert_factor_catalog(cur, fc)
                if n_fc:
                    factor_catalog_loaded = True
                    print(f"🗂️ factor_catalog upserted: {len(fc)}")
                else:
                    print("ℹ️ factor_catalog: not found in listBase (попробуем из /events/list)")
            except Exception as e:
                print(f"⚠️ factor_catalog extract/upsert failed: {type(e).__name__}: {e}")

            root_cache: Dict[int, Tuple[int, Optional[str]]] = {}

            def get_root(cat_id: Optional[int]) -> Tuple[Optional[int], Optional[str]]:
                if cat_id is None:
                    return (None, None)
                if cat_id in root_cache:
                    rid, rname = root_cache[cat_id]
                    return (rid, rname)
                rid, rname = resolve_root(cat_id, catalog_nodes) if catalog_nodes else (cat_id, None)
                root_cache[cat_id] = (rid, rname)
                return (rid, rname)

            football_candidates = find_root_ids_by_name(catalog_nodes, "футбол") or find_root_ids_by_name(catalog_nodes, "football")
            football_root_id: Optional[int] = None
            football_root_name: Optional[str] = None
            if football_candidates:
                football_root_id, football_root_name = resolve_root(football_candidates[0], catalog_nodes)
                print(f"⚽ detected football_root_id={football_root_id} name={football_root_name!r}")
                print("   👉 поставь в .env:  FONBET_FOOTBALL_SPORT_ID=<football_root_id>  (для UI по умолчанию)")
            else:
                print("⚠️ football root not detected in catalog (будет работать без авто-футбола)")

            try:
                while True:
                    first_cycle = True
                    try:
                        payload = (get_list_base(cfg, s, current_base(), timeout=timeout) if (first_cycle or args.once) else get_list(cfg, s, current_base(), version, timeout=timeout))
                        first_cycle = False
                    except (requests.exceptions.RequestException, ValueError) as e:
                        print(f"⚠️ request/json error on {current_base()}: {e}")
                        rotate_base()
                        time.sleep(max(0.1, float(args.failover_cooldown)))
                        try:
                            lb = get_list_base(cfg, s, current_base(), timeout=timeout)
                            version = get_packet_version(lb) or version
                            print(f"ℹ️ recovered version={version} on {current_base()}")
                        except Exception as e2:
                            print(f"❌ recovery listBase failed on {current_base()}: {e2}")
                        continue

                    pv = get_packet_version(payload) or version

                    # если listBase не дал факторный справочник — пробуем вытащить его из payload /events/list
                    if not factor_catalog_loaded:
                        try:
                            fc2 = extract_factor_catalog_entries(payload)
                            n2 = upsert_factor_catalog(cur, fc2)
                            if n2:
                                factor_catalog_loaded = True
                                print(f"🗂️ factor_catalog upserted from list: {len(fc2)}")
                        except Exception as e:
                            print(f"⚠️ factor_catalog extract/upsert (list) failed: {type(e).__name__}: {e}")

                    events = extract_events(payload)

                    now_ts = int(time.time())
                    max_ts = now_ts + int(args.hours * 3600)

                    ev_rows: List[Dict[str, Any]] = []
                    odds_rows: List[Tuple[int, int, Optional[float], Optional[float], Optional[str]]] = []
                    event_ids_set: set[int] = set()

                    for e in events:
                        if not isinstance(e, dict):
                            continue
                        eid = extract_event_id(e)
                        if not eid:
                            continue

                        st = to_epoch_sec(e.get("startTime") or e.get("start") or e.get("time"))
                        if st is not None and not (now_ts <= st <= max_ts):
                            continue

                        # LEAF category id from event (категория внутри спорта)
                        sport_cat_id = e.get("sportId") or e.get("sport_id") or e.get("sport")
                        if isinstance(sport_cat_id, str) and sport_cat_id.isdigit():
                            sport_cat_id = int(sport_cat_id)
                        if not isinstance(sport_cat_id, int):
                            sport_cat_id = None

                        # ROOT sport id (сам "вид спорта": футбол/теннис/…)
                        sport_root_id, _sport_root_name = get_root(sport_cat_id)
                        if sport_root_id is None:
                            sport_root_id = sport_cat_id

                        # optional filter: only football
                        if args.only_football and football_root_id is not None and sport_root_id != football_root_id:
                            continue

                        t1, t2 = extract_teams(e)

                        row = {
                            "event_id": eid,
                            "sport_id": sport_root_id,
                            "league_id": e.get("leagueId") if isinstance(e.get("leagueId"), int) else None,
                            "league_name": e.get("leagueName") if isinstance(e.get("leagueName"), str) else None,
                            "team1": t1,
                            "team2": t2,
                            "start_ts": st,
                            "state": e.get("state") if isinstance(e.get("state"), str) else None,
                        }
                        if has_category_id:
                            row["category_id"] = sport_cat_id
                        ev_rows.append(row)

                        event_ids_set.add(eid)

                        for fid, raw_val, raw_param, raw_label in extract_factors_from_event(e):
                            odd = norm_odd(raw_val, cfg.odds_divisor)
                            param = norm_param(raw_param)
                            label = norm_label(raw_label)
                            odds_rows.append((eid, fid, odd, param, label))

                    # добор котировок из payload (вне events)
                    seen = {(e, f) for (e, f, _o, _p, _lbl) in odds_rows}
                    for peid, pfid, pval, pparam, plabel in extract_payload_factor_triplets(payload):
                        if peid in event_ids_set and (peid, pfid) not in seen:
                            odd = norm_odd(pval, cfg.odds_divisor)
                            param = norm_param(pparam)
                            label = norm_label(plabel)
                            odds_rows.append((peid, pfid, odd, param, label))
                            seen.add((peid, pfid))

                    upsert_events(cur, ev_rows, has_category_id)
                    existing = load_existing_odds(cur, list(event_ids_set))
                    changed = upsert_odds_and_history(cur, odds_rows, existing, has_hist_param=has_hist_param, has_hist_label=has_hist_label)

                    print(f"✅ events={len(ev_rows)} odds={len(odds_rows)} history_added={changed} pv={pv} base={current_base()}")

                    if args.dump:
                        (repo_root / "fonbet_last_payload.json").write_text(
                            json.dumps(payload, ensure_ascii=False, indent=2),
                            encoding="utf-8",
                        )

                    version = pv

                    if args.once:
                        break

                    time.sleep(max(1.0, float(args.interval)))

            except KeyboardInterrupt:
                print("🛑 stopped by user (KeyboardInterrupt). Bye.")


if __name__ == "__main__":
    main()
