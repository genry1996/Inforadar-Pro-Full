# tools/fonbet_line_tool.py
import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlparse, urlunparse, quote

import requests


LINE_HOSTS_DEFAULT = [
    "https://line01.cy8cff-resources.com",
    "https://line02.cy8cff-resources.com",
]

DEFAULT_LANG = "ru"
DEFAULT_SCOPE = 1700


def build_proxies_from_env() -> Optional[Dict[str, str]]:
    """
    Env:
      FONBET_PROXY_SERVER=http://host:port
      FONBET_PROXY_USERNAME=user
      FONBET_PROXY_PASSWORD=pass
    """
    server = (os.getenv("FONBET_PROXY_SERVER") or "").strip()
    if not server:
        return None

    if "://" not in server:
        server = "http://" + server

    u = (os.getenv("FONBET_PROXY_USERNAME") or "").strip()
    p = (os.getenv("FONBET_PROXY_PASSWORD") or "").strip()

    parsed = urlparse(server)
    if not parsed.hostname or not parsed.port:
        raise ValueError(f"Bad FONBET_PROXY_SERVER (need host:port): {server}")

    if u and p:
        netloc = f"{quote(u)}:{quote(p)}@{parsed.hostname}:{parsed.port}"
    else:
        netloc = f"{parsed.hostname}:{parsed.port}"

    proxy_url = urlunparse((parsed.scheme, netloc, "", "", "", ""))
    return {"http": proxy_url, "https": proxy_url}


def req_json(session: requests.Session, url: str, params: Dict[str, Any], timeout: int = 30) -> Any:
    r = session.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    ct = (r.headers.get("content-type") or "").lower()
    if "json" not in ct:
        # иногда сервер шлёт json без правильного content-type
        try:
            return r.json()
        except Exception:
            raise RuntimeError(f"Non-JSON response from {r.url} CT={ct} len={len(r.text)}")
    return r.json()


def pick_line_host(session: requests.Session, hosts: List[str]) -> str:
    last_err = None
    for h in hosts:
        try:
            js = req_json(session, f"{h}/getApiState", params={}, timeout=20)
            if isinstance(js, dict):
                return h
        except Exception as e:
            last_err = e
    raise RuntimeError(f"No line host available. Last error: {last_err!r}")


def iter_lists(o: Any) -> Iterable[List[Any]]:
    if isinstance(o, list):
        yield o
        for x in o:
            yield from iter_lists(x)
    elif isinstance(o, dict):
        for v in o.values():
            yield from iter_lists(v)


def iter_dicts(o: Any) -> Iterable[Dict[str, Any]]:
    if isinstance(o, dict):
        yield o
        for v in o.values():
            yield from iter_dicts(v)
    elif isinstance(o, list):
        for x in o:
            yield from iter_dicts(x)


def parse_start_time(v: Any) -> Optional[datetime]:
    # пытаемся привести к datetime
    if v is None:
        return None
    if isinstance(v, (int, float)):
        n = int(v)
        # ms
        if n > 10_000_000_000:
            return datetime.fromtimestamp(n / 1000, tz=timezone.utc)
        # sec
        if n > 1_000_000_000:
            return datetime.fromtimestamp(n, tz=timezone.utc)
        return None
    if isinstance(v, str):
        s = v.strip()
        # ISO-ish
        for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
            try:
                dt = datetime.strptime(s, fmt)
                return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            except Exception:
                pass
    return None


def extract_events(payload: Any) -> Dict[int, Dict[str, Any]]:
    """
    Достаём "похожие на события" словари.
    """
    events: Dict[int, Dict[str, Any]] = {}
    for d in iter_dicts(payload):
        _id = d.get("id")
        if not isinstance(_id, int):
            continue

        # эвристики "это матч/событие"
        name = d.get("name") or d.get("eventName") or d.get("title")
        st = d.get("startTime") or d.get("start") or d.get("startTimeStamp") or d.get("startTs")
        has_time = parse_start_time(st) is not None

        teamish = any(k in d for k in ("team1", "team2", "team1Name", "team2Name", "home", "away"))
        if name and (has_time or teamish):
            events[_id] = d

    return events


def extract_prices(payload: Any, event_ids: set) -> Dict[int, Dict[int, float]]:
    """
    Ищем коэффициенты в разных формах:
      - dict: {factorId: X, value/price/v/p: Y}
      - dict: {f: factorId, v/p: price}
      - list: [eventId, factorId, price] (или длинные плоские массивы кратные 3)
      - list: [factorId, price] (если лежит внутри event-структуры — это поймаем отдельно хуже,
        но на первом шаге важнее поймать eventId-флэт массивы)
    """
    out: Dict[int, Dict[int, float]] = {}

    def put(eid: int, fid: int, price: float):
        if eid not in out:
            out[eid] = {}
        out[eid][fid] = price

    # 1) dict-формы
    value_keys = ("value", "val", "price", "p", "v", "coef", "koef", "k")
    for d in iter_dicts(payload):
        # вариант A: factorId + valueKey
        if isinstance(d.get("factorId"), int):
            fid = int(d["factorId"])
            for kk in value_keys:
                vv = d.get(kk)
                if isinstance(vv, (int, float)) and 1.0 <= float(vv) <= 10000:
                    # пытаемся найти eventId рядом
                    eid = d.get("eventId") or d.get("idEvent") or d.get("e")
                    if isinstance(eid, int) and eid in event_ids:
                        put(eid, fid, float(vv))
                    break

        # вариант B: f + v/p
        if isinstance(d.get("f"), int):
            fid = int(d["f"])
            vv = d.get("v") if isinstance(d.get("v"), (int, float)) else d.get("p")
            if isinstance(vv, (int, float)) and 1.0 <= float(vv) <= 10000:
                eid = d.get("eventId") or d.get("e") or d.get("idEvent")
                if isinstance(eid, int) and eid in event_ids:
                    put(eid, fid, float(vv))

    # 2) list-формы: триплеты (eventId, factorId, price) и плоские массивы кратные 3
    for lst in iter_lists(payload):
        if not lst:
            continue

        # плоский массив кратный 3
        if len(lst) >= 6 and len(lst) % 3 == 0 and all(isinstance(x, (int, float)) for x in lst):
            for i in range(0, len(lst), 3):
                a, b, c = lst[i], lst[i + 1], lst[i + 2]
                eid = int(a)
                fid = int(b)
                price = float(c)
                if eid in event_ids and fid > 0 and 1.0 <= price <= 10000:
                    put(eid, fid, price)
            continue

        # вложенный триплет
        if len(lst) == 3 and all(isinstance(x, (int, float)) for x in lst):
            a, b, c = lst
            eid = int(a)
            fid = int(b)
            price = float(c)
            if eid in event_ids and fid > 0 and 1.0 <= price <= 10000:
                put(eid, fid, price)

    return out


def format_dt(dt: Optional[datetime]) -> str:
    if not dt:
        return ""
    # печатаем в локальном виде без tz (для читабельности)
    return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")


def cmd_fetch_payload(session: requests.Session, line_host: str, scope: int, lang: str) -> Dict[str, Any]:
    # listBase даёт “снимок”; list — обновления (нужен version). Берём сначала listBase.
    base = req_json(session, f"{line_host}/events/listBase", params={"lang": lang, "scopeMarket": scope}, timeout=45)
    # Попробуем получить version из payload или из getApiState, чтобы дёрнуть list и словить odds если они там.
    version = None
    if isinstance(base, dict):
        for k in ("version", "v", "lineVersion", "dataVersion"):
            if isinstance(base.get(k), int):
                version = int(base[k])
                break

    if version is None:
        try:
            st = req_json(session, f"{line_host}/getApiState", params={}, timeout=20)
            if isinstance(st, dict):
                for k in ("version", "v", "lineVersion", "dataVersion"):
                    if isinstance(st.get(k), int):
                        version = int(st[k])
                        break
        except Exception:
            pass

    payload = {"listBase": base, "list": None, "meta": {"line_host": line_host, "scope": scope, "lang": lang, "version": version}}
    if version is not None:
        try:
            upd = req_json(session, f"{line_host}/events/list", params={"lang": lang, "scopeMarket": scope, "version": version}, timeout=45)
            payload["list"] = upd
        except Exception:
            # не критично, listBase нам важнее
            payload["list"] = None

    return payload


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    ap.add_argument("--lang", default=DEFAULT_LANG)
    ap.add_argument("--scope", type=int, default=DEFAULT_SCOPE)
    ap.add_argument("--line-host", default=os.getenv("FONBET_LINE_HOST") or "")
    ap.add_argument("--no-proxy", action="store_true")

    sp_m = sub.add_parser("matches", help="Print matches")
    sp_m.add_argument("--limit", type=int, default=30)

    sp_o = sub.add_parser("odds", help="Print odds (factors) for match id")
    sp_o.add_argument("--id", type=int, required=True)
    sp_o.add_argument("--max", type=int, default=50)

    sp_d = sub.add_parser("dump", help="Dump raw payload to file")
    sp_d.add_argument("--out", default="fonbet_line_dump.json")

    args = ap.parse_args()

    proxies = None
    if not args.no_proxy:
        proxies = build_proxies_from_env()

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36",
            "Accept": "application/json,text/plain,*/*",
        }
    )
    if proxies:
        session.proxies.update(proxies)

    # line host
    if args.line_host:
        line_host = args.line_host.rstrip("/")
    else:
        line_host = pick_line_host(session, LINE_HOSTS_DEFAULT)

    payload = cmd_fetch_payload(session, line_host, scope=args.scope, lang=args.lang)

    if args.cmd == "dump":
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        print(f"Saved: {args.out}")
        print(f"Line host: {line_host}")
        return

    # объединяем источники
    sources = []
    if payload.get("listBase") is not None:
        sources.append(payload["listBase"])
    if payload.get("list") is not None:
        sources.append(payload["list"])

    # собираем события
    events: Dict[int, Dict[str, Any]] = {}
    for src in sources:
        events.update(extract_events(src))

    event_ids = set(events.keys())

    # собираем коэффициенты
    prices: Dict[int, Dict[int, float]] = {}
    for src in sources:
        pmap = extract_prices(src, event_ids)
        for eid, f2p in pmap.items():
            prices.setdefault(eid, {}).update(f2p)

    if args.cmd == "matches":
        rows = []
        for eid, e in events.items():
            name = e.get("name") or e.get("eventName") or e.get("title") or ""
            st = e.get("startTime") or e.get("start") or e.get("startTimeStamp") or e.get("startTs")
            dt = parse_start_time(st)
            rows.append((dt or datetime.max.replace(tzinfo=timezone.utc), eid, str(name)))

        rows.sort(key=lambda x: x[0])

        print(f"Line host: {line_host}")
        print(f"Events found: {len(rows)} | With prices: {sum(1 for _, eid, _ in rows if eid in prices and prices[eid])}")
        print("-" * 120)
        for dt, eid, name in rows[: args.limit]:
            has = "prices" if (eid in prices and prices[eid]) else ""
            print(f"{format_dt(dt)} | {name[:70]:70} | id={eid} {has}")
        return

    if args.cmd == "odds":
        eid = args.id
        if eid not in events:
            print(f"Not found in events: id={eid}")
            print("Tip: run `matches --limit 50` and copy id from there.")
            return
        e = events[eid]
        name = e.get("name") or e.get("eventName") or e.get("title") or ""
        st = e.get("startTime") or e.get("start") or e.get("startTimeStamp") or e.get("startTs")
        dt = parse_start_time(st)

        print(f"Line host: {line_host}")
        print(f"{format_dt(dt)} | {name} | id={eid}")
        print("-" * 120)

        f2p = prices.get(eid) or {}
        if not f2p:
            print("No factor prices detected for this event in listBase/list.")
            print("Do: python tools/fonbet_line_tool.py dump --out fonbet_line_dump.json")
            return

        # печатаем top-N по factorId
        for fid in sorted(f2p.keys())[: args.max]:
            print(f"factorId={fid}  price={f2p[fid]}")
        return


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
