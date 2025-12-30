#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
22bet Prematch Football (next 12h) -> MySQL (table odds_22bet) for Inforadar UI.

What it does:
- Opens 22bet football prematch page via Playwright (with proxy if configured)
- Extracts: match time, teams, 1X2 odds
- Upserts into MySQL table odds_22bet with market_type='1X2', status='active'
- Loops every INTERVAL_SECONDS (default 60)

Config:
- Put credentials in .env (recommended) OR export env vars before run.
  Required for DB:
    MYSQL_HOST, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DATABASE, MYSQL_PORT
  Proxy (optional):
    PROXY (full URL) OR PROXY_SERVER + PROXY_USERNAME + PROXY_PASSWORD

Run:
  python prematch_football_12h_fixed.py --url "https://22betluck.com/ru/line/football" --tz Europe/Paris --interval 60 --hours 12
"""

import os
import re
import time
import hashlib
import argparse
from datetime import datetime, timedelta

import pymysql
from dotenv import load_dotenv

from playwright.sync_api import sync_playwright

# -------------------- env helpers --------------------
def _load_env():
    # Load .env from cwd and also from project root (two levels up), if exists
    load_dotenv(".env")
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        load_dotenv(os.path.join(here, ".env"))
        load_dotenv(os.path.join(here, "..", ".env"))
        load_dotenv(os.path.join(here, "..", "..", ".env"))
    except Exception:
        pass

def _env(name: str, default: str = "") -> str:
    v = os.getenv(name, default)
    return v.strip() if isinstance(v, str) else v

# -------------------- time parsing --------------------
def parse_match_time(raw: str, tz_name: str) -> datetime | None:
    """
    Accepts:
      - "28/12 19:00"
      - "28.12 19:00"
      - "19:00" (assumes today; if already passed -> tomorrow)
    Returns naive datetime in local tz (UI uses naive).
    """
    if not raw:
        return None

    s = raw.strip()
    now = datetime.now()

    # dd/mm HH:MM
    m = re.search(r"\b(\d{1,2})[\/\.](\d{1,2})\s+(\d{1,2}):(\d{2})\b", s)
    if m:
        day = int(m.group(1))
        month = int(m.group(2))
        hour = int(m.group(3))
        minute = int(m.group(4))
        year = now.year
        dt = datetime(year, month, day, hour, minute)
        # handle year wrap (late Dec / early Jan)
        if dt < now - timedelta(days=2):
            dt = datetime(year + 1, month, day, hour, minute)
        return dt

    # HH:MM only
    m = re.search(r"\b(\d{1,2}):(\d{2})\b", s)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2))
        dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if dt < now - timedelta(minutes=10):
            dt = dt + timedelta(days=1)
        return dt

    return None

def make_event_id(event_name: str, match_time: datetime | None) -> int:
    base = f"{event_name}|{match_time.isoformat() if match_time else ''}"
    h = hashlib.md5(base.encode("utf-8")).hexdigest()[:16]
    return int(h, 16)

def split_teams(event_name: str) -> tuple[str, str]:
    # Common separators
    for sep in [" vs ", " v ", " - ", " — ", " – "]:
        if sep in event_name:
            a, b = event_name.split(sep, 1)
            return a.strip(), b.strip()
    return event_name.strip(), ""

# -------------------- MySQL --------------------
def get_db():
    cfg = {
        "host": _env("MYSQL_HOST", "localhost"),
        "user": _env("MYSQL_USER", "root"),
        "password": _env("MYSQL_PASSWORD", ""),
        "database": _env("MYSQL_DATABASE", "inforadar"),
        "port": int(_env("MYSQL_PORT", "3306") or 3306),
        "charset": "utf8mb4",
        "cursorclass": pymysql.cursors.DictCursor,
        "autocommit": True,
    }
    return pymysql.connect(**cfg)

def ensure_schema(conn):
    sql = """
    CREATE TABLE IF NOT EXISTS odds_22bet (
      id INT AUTO_INCREMENT PRIMARY KEY,
      event_id BIGINT NOT NULL,
      event_name VARCHAR(255) NOT NULL,
      home_team VARCHAR(255),
      away_team VARCHAR(255),
      sport VARCHAR(50) NOT NULL,
      league VARCHAR(255),
      match_time DATETIME,
      market_type VARCHAR(50) NOT NULL DEFAULT '1X2',
      odd_1 DOUBLE,
      odd_x DOUBLE,
      odd_2 DOUBLE,
      liquidity_level VARCHAR(20) DEFAULT 'N/A',
      is_suspicious TINYINT(1) DEFAULT 0,
      status VARCHAR(20) DEFAULT 'active',
      bookmaker VARCHAR(50) DEFAULT '22bet',
      updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
      UNIQUE KEY uniq_event_market (event_id, market_type, bookmaker),
      INDEX idx_sport_time (sport, match_time),
      INDEX idx_league (league)
    ) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
    """
    with conn.cursor() as cur:
        cur.execute(sql)

def upsert_1x2(conn, row: dict):
    sql = """
    INSERT INTO odds_22bet
      (event_id, event_name, home_team, away_team, sport, league, match_time, market_type,
       odd_1, odd_x, odd_2, liquidity_level, is_suspicious, status, bookmaker)
    VALUES
      (%(event_id)s, %(event_name)s, %(home_team)s, %(away_team)s, %(sport)s, %(league)s, %(match_time)s, %(market_type)s,
       %(odd_1)s, %(odd_x)s, %(odd_2)s, %(liquidity_level)s, %(is_suspicious)s, %(status)s, %(bookmaker)s)
    ON DUPLICATE KEY UPDATE
      event_name=VALUES(event_name),
      home_team=VALUES(home_team),
      away_team=VALUES(away_team),
      league=VALUES(league),
      match_time=VALUES(match_time),
      odd_1=VALUES(odd_1),
      odd_x=VALUES(odd_x),
      odd_2=VALUES(odd_2),
      liquidity_level=VALUES(liquidity_level),
      is_suspicious=VALUES(is_suspicious),
      status=VALUES(status),
      updated_at=CURRENT_TIMESTAMP;
    """
    with conn.cursor() as cur:
        cur.execute(sql, row)

# -------------------- scraping --------------------
ODDS_RE = re.compile(r"\b(\d+\.\d+)\b")

def extract_odds(text: str) -> tuple[float | None, float | None, float | None]:
    # naive: take first 3 decimal numbers as 1, X, 2
    nums = [float(x) for x in ODDS_RE.findall(text)]
    if len(nums) >= 3:
        return nums[0], nums[1], nums[2]
    return None, None, None

def extract_time_str(text: str) -> str | None:
    m = re.search(r"\b\d{1,2}[\/\.]\d{1,2}\s+\d{1,2}:\d{2}\b", text)
    if m:
        return m.group(0)
    m = re.search(r"\b\d{1,2}:\d{2}\b", text)
    if m:
        return m.group(0)
    return None

def scrape_once(url: str, tz: str, proxy_cfg: dict | None) -> list[dict]:
    rows: list[dict] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, proxy=proxy_cfg)
        page = browser.new_page()
        page.goto(url, timeout=90_000, wait_until="domcontentloaded")
        page.wait_for_timeout(2000)

        # try to scroll a bit to load more events
        for _ in range(10):
            page.mouse.wheel(0, 2000)
            page.wait_for_timeout(500)

        events = page.query_selector_all(".c-events__item")
        for ev in events:
            text = (ev.inner_text() or "").strip()
            if not text:
                continue

            # event name is usually in a specific selector
            name_el = ev.query_selector(".c-events__name")
            event_name = (name_el.inner_text().strip() if name_el else "")
            if not event_name:
                # fallback: find line that contains "vs"
                for line in text.splitlines():
                    if "vs" in line.lower() or " v " in line.lower():
                        event_name = line.strip()
                        break
            if not event_name:
                continue

            time_str = extract_time_str(text)
            match_time = parse_match_time(time_str or "", tz)

            odd1, oddx, odd2 = extract_odds(text)
            if odd1 is None and oddx is None and odd2 is None:
                continue

            home, away = split_teams(event_name)
            event_id = make_event_id(event_name, match_time)

            rows.append({
                "event_id": event_id,
                "event_name": event_name,
                "home_team": home,
                "away_team": away,
                "sport": "Football",
                "league": None,
                "match_time": match_time,
                "market_type": "1X2",
                "odd_1": odd1,
                "odd_x": oddx,
                "odd_2": odd2,
                "liquidity_level": "N/A",
                "is_suspicious": 0,
                "status": "active",
                "bookmaker": "22bet",
            })

        browser.close()
    return rows

def build_proxy_cfg() -> dict | None:
    """
    Playwright expects proxy config:
      {"server":"http://host:port","username":"u","password":"p"}
    """
    proxy_full = _env("PROXY", "")
    if proxy_full:
        # If user provides full URL with creds, parse it
        m = re.match(r"^(https?://)([^:@]+):([^@]+)@(.+)$", proxy_full)
        if m:
            scheme = m.group(1)
            user = m.group(2)
            pwd = m.group(3)
            server = scheme + m.group(4)
            return {"server": server, "username": user, "password": pwd}
        # Otherwise just pass as server
        return {"server": proxy_full}

    server = _env("PROXY_SERVER", "")
    if not server:
        return None
    return {
        "server": server,
        "username": _env("PROXY_USERNAME", ""),
        "password": _env("PROXY_PASSWORD", ""),
    }

def main():
    _load_env()

    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=_env("PREMATCH_URL", "https://22betluck.com/ru/line/football"))
    ap.add_argument("--tz", default=_env("TZ", "Europe/Paris"))
    ap.add_argument("--interval", type=int, default=int(_env("PREMATCH_INTERVAL", "60") or 60))
    ap.add_argument("--hours", type=int, default=int(_env("PREMATCH_HOURS", "12") or 12))
    args = ap.parse_args()

    proxy_cfg = build_proxy_cfg()
    print(f"⚽ 22bet PREMATCH Football | interval={args.interval}s | window={args.hours}h | tz={args.tz}")
    if proxy_cfg:
        print(f"🌍 Proxy: {proxy_cfg.get('server')} (user: {'yes' if proxy_cfg.get('username') else 'no'})")
    else:
        print("🌍 Proxy: none")

    while True:
        t0 = time.time()
        try:
            conn = get_db()
            ensure_schema(conn)

            rows = scrape_once(args.url, args.tz, proxy_cfg)
            now = datetime.now()
            horizon = now + timedelta(hours=args.hours)

            saved = 0
            for r in rows:
                mt = r.get("match_time")
                if mt and (mt < now or mt > horizon):
                    continue
                upsert_1x2(conn, r)
                saved += 1

            print(f"✅ upserted: {saved} matches (raw scraped={len(rows)})")
            conn.close()
        except Exception as e:
            print(f"❌ error: {e}")

        dt = time.time() - t0
        sleep_for = max(1, args.interval - int(dt))
        time.sleep(sleep_for)

if __name__ == "__main__":
    main()
