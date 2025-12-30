from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional
import time
import httpx


@dataclass
class FonbetConfig:
    base_headers: Dict[str, str]
    cookies: Dict[str, str]
    timeout: float = 20.0
    retries: int = 2
    retry_sleep: float = 0.7


class FonbetClient:
    def __init__(self, cfg: FonbetConfig, proxy_url: Optional[str] = None):
        self.cfg = cfg
        self.client = httpx.Client(
            headers=cfg.base_headers,
            cookies=cfg.cookies,
            timeout=cfg.timeout,
            proxy=proxy_url or None,
            follow_redirects=True,
        )

    @staticmethod
    def default_headers() -> Dict[str, str]:
        return {
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "accept": "application/json, text/plain, */*",
            "accept-language": "en-US,en;q=0.9,ru;q=0.8",
            "cache-control": "no-cache",
            "pragma": "no-cache",
        }

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> "FonbetClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def get_json(self, url: str, params: Optional[Dict[str, Any]] = None) -> Any:
        last_err: Exception | None = None
        for attempt in range(self.cfg.retries + 1):
            try:
                r = self.client.get(url, params=params)
                r.raise_for_status()
                return r.json()
            except Exception as e:
                last_err = e
                if attempt < self.cfg.retries:
                    time.sleep(self.cfg.retry_sleep * (attempt + 1))
                    continue
                raise last_err
