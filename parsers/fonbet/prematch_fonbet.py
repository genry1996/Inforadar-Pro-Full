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


# -------- .env loader (без зависимостей) --------
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

            # НЕ перетираем то, что уже задано в окружении
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


@dataclass
class FonbetCfg:
    lang: str = "ru"
    scope_market: int = 1700
    line_hosts: Tuple[str, ...] = (
        "https://line01.cy8cff-resources.com",
        "https://line02.cy8cff-resources.com",
    )
    timeout_s: int = 25
    odds_divisor: int = 1000


def pick_line_base(cfg: FonbetCfg, s: requests.Session) -> str:
    # В твоём capture getApiState — GET :contentReference[oaicite:3]{index=3}
    for base in cfg.line_hosts:
        try:
            r = s.get(f"{base}/getApiState", timeout=cfg.timeout_s)
            if r.status_code == 200:
                return base
        except Exception:
            continue
    return cfg.line_hosts[0]


def get_list_base(cfg: FonbetCfg, s: requests.Session, base: str) -> Dict[str, Any]:
    r = s.get(
        f"{base}/events/listBase",
        params={"lang": cfg.lang, "scopeMarket": str(cfg.scope_market)},
        timeout=cfg.timeout_s,
    )
    r.raise_for_status()
    return r.json()


def get_list(cfg: FonbetCfg, s: requests.Session, base: str, version: int) -> Dict[str, Any]:
    r = s.get(
        f"{base}/events/list",
        params={"lang": cfg.lang, "version": str(int(version)), "scopeMarket": str(cfg.scope_market)},
        timeout=cfg.timeout_s,
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


def to_epoch_sec(x: Any) -> Optional[int]:
    if x is None:
        return None
    if isinstance(x, (int, float)):
        v = int(x)
        if v > 10_000_000_000:
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


def extract_factors(e: Dict[str, Any]) -> List[Tuple[int, Any]]:
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


def mysql_conn():
    # ✅ ВАЖНО: сначала MYSQL_*, как у тебя в .env :contentReference[oaicite:4]{index=4}
    host = env("MYSQL_HOST") or env("DB_HOST") or "127.0.0.1"
    user = env("MYSQL_USER") or env("DB_USER") or "root"
    password = env("MYSQL_PASSWORD") or env("DB_PASSWORD") or ""
    database = env("MYSQL_DB") or env("MYSQL_DATABASE") or env("DB_NAME") or "inforadar"

    src = "MYSQL_*" if env("MYSQL_PASSWORD") else ("DB_*" if env("DB_PASSWORD") else "defaults")
    print(f"[db] host={host} user={user} db={database} pass_len={len(password)} source={src}")

    if not password:
        raise RuntimeError("MySQL password empty. Set MYSQL_PASSWORD in D:\\Inforadar_Pro\\.env")

    try:
        return pymysql.connect(
            host=host,
            user=user,
            password=password,
            database=database,
            charset="utf8mb4",
            autocommit=True,
            cursorclass=pymysql.cursors.DictCursor,
        )
    except RuntimeError as e:
        msg = str(e)
        if "cryptography" in msg and ("caching_sha2_password" in msg or "sha256_password" in msg):
            raise RuntimeError(
                "MySQL auth requires cryptography. Install:\n"
                "  .\\.venv_fonbet\\Scripts\\pip.exe install -U cryptography"
            ) from e
        raise


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
    args = ap.parse_args()

    cfg = FonbetCfg(lang=args.lang, scope_market=args.scope_market)

    s = requests.Session()
    s.headers.update({
        "Accept": "application/json, text/plain, */*",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
        "Accept-Language": f"{cfg.lang},en;q=0.8",
    })

    proxies = build_proxy_dict()
    if proxies:
        s.proxies.update(proxies)

    base = pick_line_base(cfg, s)
    print(f"🏁 Fonbet PREMATCH | base={base} | scopeMarket={cfg.scope_market} | interval={args.interval}s")

    conn = mysql_conn()
    with conn:
        with conn.cursor() as cur:
            lb = get_list_base(cfg, s, base)
            version = get_packet_version(lb)
            print(f"ℹ️ listBase version={version}")

            while True:
                payload = get_list(cfg, s, base, version) if version else get_list_base(cfg, s, base)
                pv = get_packet_version(payload) or version
                events = extract_events(payload)

                now_ts = int(time.time())
                max_ts = now_ts + int(args.hours * 3600)

                ev_rows: List[Dict[str, Any]] = []
                odds_rows: List[Tuple[int, int, Optional[float]]] = []
                event_ids: List[int] = []

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
                    event_ids.append(eid)

                    for fid, raw_val in extract_factors(e):
                        odd = norm_odd(raw_val, cfg.odds_divisor)
                        odds_rows.append((eid, fid, odd))

                upsert_events(cur, ev_rows)
                existing = load_existing_odds(cur, event_ids)
                changed = upsert_odds_and_history(cur, odds_rows, existing)

                print(f"✅ events={len(ev_rows)} odds={len(odds_rows)} history_added={changed} pv={pv}")

                if args.dump:
                    (repo_root / "fonbet_last_payload.json").write_text(
                        json.dumps(payload, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )

                version = pv
                if args.once:
                    break
                time.sleep(max(1.0, float(args.interval)))


if __name__ == "__main__":
    main()
