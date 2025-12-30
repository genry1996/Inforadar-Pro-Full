# inforadar_parser/parsers/fonbet/fonbet_api.py
from __future__ import annotations

import re
import time
import random
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple, List

import requests


LINE_HOST_RE = re.compile(r"(https?:)?//(line\d+)\.bkfon-resources\.com", re.IGNORECASE)


@dataclass
class FonbetApiConfig:
    origin_url: str = "https://fon.bet/sports/football?mode=1"
    lang: str = "ru"
    scope_market: int = 1600
    timeout_s: int = 20
    proxy: Optional[str] = None  # like http://user:pass@host:port


def _mk_session(cfg: FonbetApiConfig) -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "Accept": "application/json, text/plain, */*",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": f"{cfg.lang},en;q=0.8",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    })
    if cfg.proxy:
        s.proxies.update({
            "http": cfg.proxy,
            "https": cfg.proxy,
        })
    return s


def discover_line_base(cfg: FonbetApiConfig) -> str:
    """
    1) пробуем вытащить lineXX.bkfon-resources.com из HTML origin_url
    2) если не нашли — быстрый fallback: перебор нескольких line-нод вокруг 50..70
    """
    s = _mk_session(cfg)

    # 1) HTML -> ищем lineXX
    try:
        r = s.get(cfg.origin_url, timeout=cfg.timeout_s)
        r.raise_for_status()
        m = LINE_HOST_RE.search(r.text)
        if m:
            host = m.group(2)  # lineNN
            return f"https://{host}.bkfon-resources.com"
    except Exception:
        pass

    # 2) fallback (не сотни запросов — аккуратно)
    candidates = list(range(45, 71))
    random.shuffle(candidates)

    for n in candidates[:20]:
        base = f"https://line{n}.bkfon-resources.com"
        try:
            _ = fetch_events_list(cfg, base=base, version=0)
            return base
        except Exception:
            continue

    raise RuntimeError("Could not discover Fonbet line base (lineXX.bkfon-resources.com)")


def fetch_events_list(cfg: FonbetApiConfig, base: str, version: int = 0) -> Dict[str, Any]:
    """
    GET /events/list?lang=..&version=..&scopeMarket=..
    В ответе обычно есть packetVersion и много данных по линии.
    """
    s = _mk_session(cfg)
    url = f"{base}/events/list"
    params = {
        "lang": cfg.lang,
        "version": str(int(version)),
        "scopeMarket": str(int(cfg.scope_market)),
        # иногда помогает от кеша
        "_": str(int(time.time() * 1000)),
    }
    r = s.get(url, params=params, timeout=cfg.timeout_s)
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, dict):
        raise ValueError("Unexpected response type (expected JSON object)")
    return data


def extract_packet_version(payload: Dict[str, Any]) -> int:
    for k in ("packetVersion", "version", "pv"):
        v = payload.get(k)
        if isinstance(v, int):
            return v
        if isinstance(v, str) and v.isdigit():
            return int(v)
    return 0


def _to_epoch_seconds(x: Any) -> Optional[int]:
    if x is None:
        return None
    if isinstance(x, (int, float)):
        v = int(x)
        # ms -> sec
        if v > 10_000_000_000:  # ~year 2286 in seconds; anything above is likely ms
            v = v // 1000
        return v
    return None


def extract_events(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Пытаемся достать события максимально безопасно:
    - events: [...]
    - либо другие структуры (оставляем как есть)
    """
    if isinstance(payload.get("events"), list):
        return payload["events"]
    # иногда события лежат глубже — оставим пусто, но payload всё равно можно дампнуть и посмотреть
    return []


def extract_event_factors(event: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Факторы/коэфы обычно лежат как список объектов (f,v) или (id,value).
    """
    factors = event.get("factors")
    if isinstance(factors, list):
        return [x for x in factors if isinstance(x, dict)]
    return []
