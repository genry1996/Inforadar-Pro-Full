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

            # strip quotes
            if len(v) >= 2 and ((v[0] == v[-1] == '"') or (v[0] == v[-1] == "'")):
                v = v[1:-1]

            # не перетираем env, если уже задано (например через $env:...)
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
def pick_line_base(
    cfg: FonbetCfg,
    s: requests.Session,
    timeout: Tuple[float, float],
) -> str:
    # getApiState (у тебя он приходил GET)
    for base in cfg.line_hosts:
        try:
            r = s.get(f"{base}/getApiState", timeout=timeout)
            if r.status_code == 200:
                return base
        except Exception:
            continue
    return cfg.line_hosts[0]


def get_list_base(
    cfg: FonbetCfg,
    s: requests.Session,
    base: str,
    timeout: Tuple[float, float],
) -> Dict[str, Any]:
    r = s.get(
        f"{base}/events/listBase",
        params={"lang": cfg.lang, "scopeMarket": str(cfg.scope_market)},
        timeout=timeout,
    )
    r.raise_for_status()
    return r.json()


def get_list(
    cfg: FonbetCfg,
    s: requests.Session,
    base: str,
    version: int,
    timeout: Tuple[float, float],
) -> Dict[str, Any]:
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
        # 2000 -> 2.0
        if divisor and val >= divisor:
            return val / float(divisor)
        return float(val)
    if isinstance(val, str):
        try:
            return float(val.replace(",", "."))
        except Exception:
            return None
    return None


def extract_event_id(e: Dict[str, Any]) -> Optional[int]:
    for k in ("id", "eventId", "event_id"):
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


def extract_factors_from_event(e: Dict[str, Any]) -> List[Tuple[int, Any]]:
    factors = e.get("factors")
    out: List[Tuple[int, Any]] = []
    if not isinstance(factors, list):
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


def extract_payload_factor_triplets(payload: Dict[str, Any]) -> List[Tuple[int, int, Any]]:
    """
    Частый формат у Fonbet:
      { "e": <event_id>, "factors": [ {"f": <factor_id>, "v": <odd>}, ... ] }
    Возвращает (event_id, factor_id, raw_value)
    """
    out: List[Tuple[int, int, Any]] = []

    def consume_list(lst: Any) -> None:
        if not isinstance(lst, list) or not lst:
            return
        if not isinstance(lst[0], dict):
            return
        sample = lst[0]
        if "factors" not in sample:
            return
        if not ("e" in sample or "eventId" in sample or "event" in sample):
            return

        for item in lst:
            if not isinstance(item, dict):
                continue
            eid = item.get("e") or item.get("eventId") or item.get("event")
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
                val = f.get("v") or f.get("value") or f.get("p")
                if isinstance(fid, str) and fid.isdigit():
                    fid = int(fid)
                if isinstance(fid, int):
                    out.append((eid, fid, val))

    # 1) если ключи явные
    for key in ("customFactors", "eventFactors", "eventFactorList", "factors", "eventFactor"):
        if key in payload:
            consume_list(payload.get(key))

    # 2) любые top-level списки
    for v in payload.values():
        consume_list(v)

    # 3) data
    data = payload.get("data")
    if isinstance(data, dict):
        for v in data.values():
            consume_list(v)

    return out


# ----------------------------
# MySQL
# ----------------------------
def mysql_conn():
    host = env("MYSQL_HOST") or env("DB_HOST") or "127.0.0.1"
    user = env("MYSQL_USER") or env("DB_USER") or "root"
    password = env("MYSQL_PASSWORD") or env("DB_PASSWORD") or ""
    database = env("MYSQL_DB") or env("MYSQL_DATABASE") or env("DB_NAME") or "inforadar"

    src = "MYSQL_*" if env("MYSQL_PASSWORD") else ("DB_*" if env("DB_PASSWORD") else "defaults")
    print(f"[db] host={host} user={user} db={database} pass_len={len(password)} source={src}")

    if not password:
        raise RuntimeError("MySQL password empty. Set MYSQL_PASSWORD (or DB_PASSWORD) in .env")

    return pymysql.connect(
        host=host,
        user=user,
        password=password,
        database=database,
        charset="utf8mb4",
        autocommit=True,
        cursorclass=pymysql.cursors.DictCursor,
    )


def upsert_events(cur, rows: List[Dict[str, Any]]) -> None:
    if not rows:
        return
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
    odds_rows: List[Tuple[int, int, Optional[float]]],
    existing: Dict[Tuple[int, int], float],
) -> int:
    if not odds_rows:
        return 0

    cur.executemany(
        "INSERT INTO fonbet_odds (event_id, factor_id, odd) VALUES (%s,%s,%s) "
        "ON DUPLICATE KEY UPDATE odd=VALUES(odd)",
        [(e, f, o) for (e, f, o) in odds_rows],
    )

    hist_rows = []
    for (e, f, o) in odds_rows:
        if o is None:
            continue
        prev = existing.get((e, f))
        if prev is None or abs(prev - o) > 1e-9:
            hist_rows.append((e, f, o))

    if hist_rows:
        cur.executemany(
            "INSERT INTO fonbet_odds_history (event_id, factor_id, odd) VALUES (%s,%s,%s)",
            hist_rows,
        )
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
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--dump", action="store_true")

    # anti-hang settings
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

    # выбираем рабочую ноду
    base = pick_line_base(cfg, s, timeout=timeout)
    if base in bases:
        base_idx = bases.index(base)

    print(f"🏁 Fonbet PREMATCH | base={current_base()} | scopeMarket={cfg.scope_market} | interval={args.interval}s")

    conn = mysql_conn()
    with conn:
        with conn.cursor() as cur:
            try:
                lb = get_list_base(cfg, s, current_base(), timeout=timeout)
                version = get_packet_version(lb)
                print(f"ℹ️ listBase version={version}")
            except Exception as e:
                print(f"❌ listBase failed on {current_base()}: {e}")
                print("↪️ failover to next line host")
                rotate_base()
                time.sleep(max(0.1, float(args.failover_cooldown)))
                lb = get_list_base(cfg, s, current_base(), timeout=timeout)
                version = get_packet_version(lb)
                print(f"ℹ️ listBase version={version}")

            try:
                while True:
                    try:
                        payload = get_list(cfg, s, current_base(), version, timeout=timeout) if version else get_list_base(cfg, s, current_base(), timeout=timeout)
                    except (requests.exceptions.RequestException, ValueError) as e:
                        print(f"⚠️ request/json error on {current_base()}: {e}")
                        print("↪️ failover to next line host")
                        rotate_base()
                        time.sleep(max(0.1, float(args.failover_cooldown)))
                        # после переключения попробуем listBase, чтобы восстановить версию
                        try:
                            lb = get_list_base(cfg, s, current_base(), timeout=timeout)
                            version = get_packet_version(lb) or version
                            print(f"ℹ️ recovered version={version} on {current_base()}")
                        except Exception as e2:
                            print(f"❌ recovery listBase failed on {current_base()}: {e2}")
                        continue

                    pv = get_packet_version(payload) or version
                    events = extract_events(payload)

                    now_ts = int(time.time())
                    max_ts = now_ts + int(args.hours * 3600)

                    ev_rows: List[Dict[str, Any]] = []
                    odds_rows: List[Tuple[int, int, Optional[float]]] = []
                    event_ids_set: set[int] = set()

                    # 1) события + факторы внутри events
                    for e in events:
                        if not isinstance(e, dict):
                            continue
                        eid = extract_event_id(e)
                        if not eid:
                            continue

                        st = to_epoch_sec(e.get("startTime") or e.get("start") or e.get("time"))
                        if st is not None and not (now_ts <= st <= max_ts):
                            continue

                        t1, t2 = extract_teams(e)
                        ev_rows.append({
                            "event_id": eid,
                            "sport_id": e.get("sportId") if isinstance(e.get("sportId"), int) else None,
                            "league_id": e.get("leagueId") if isinstance(e.get("leagueId"), int) else None,
                            "league_name": e.get("leagueName") if isinstance(e.get("leagueName"), str) else None,
                            "team1": t1,
                            "team2": t2,
                            "start_ts": st,
                            "state": e.get("state") if isinstance(e.get("state"), str) else None,
                        })
                        event_ids_set.add(eid)

                        for fid, raw_val in extract_factors_from_event(e):
                            odd = norm_odd(raw_val, cfg.odds_divisor)
                            odds_rows.append((eid, fid, odd))

                    # 2) добор котировок из payload (вне events)
                    seen = {(e, f) for (e, f, _) in odds_rows}
                    for peid, pfid, pval in extract_payload_factor_triplets(payload):
                        if peid in event_ids_set and (peid, pfid) not in seen:
                            odd = norm_odd(pval, cfg.odds_divisor)
                            odds_rows.append((peid, pfid, odd))
                            seen.add((peid, pfid))

                    upsert_events(cur, ev_rows)
                    existing = load_existing_odds(cur, list(event_ids_set))
                    changed = upsert_odds_and_history(cur, odds_rows, existing)

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
