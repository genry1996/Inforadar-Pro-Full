# -*- coding: utf-8 -*-
"""
Лёгкий клиент для The Odds API.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Tuple

import requests


class OddsApiError(Exception):
    """Ошибки работы с The Odds API."""


class OddsApiClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = "https://api.the-odds-api.com/v4",
        timeout: int = 20,
    ) -> None:
        self.api_key = api_key or os.getenv("ODDS_API_KEY")
        if not self.api_key:
            raise OddsApiError("ODDS_API_KEY is not set")

        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _get(self, path: str, **params: Any) -> Tuple[Any, Dict[str, Any]]:
        url = f"{self.base_url}{path}"
        params["apiKey"] = self.api_key

        resp = requests.get(url, params=params, timeout=self.timeout)

        info = {
            "remaining": resp.headers.get("x-requests-remaining"),
            "used": resp.headers.get("x-requests-used"),
            "status": resp.status_code,
        }

        if resp.status_code != 200:
            raise OddsApiError(
                f"GET {url} -> {resp.status_code}: {resp.text}"
            )

        return resp.json(), info

    # === Публичные методы ===

    def get_sports(self, all_: bool = True):
        params: Dict[str, Any] = {}
        if all_:
            params["all"] = "true"
        return self._get("/sports", **params)

    def get_odds(
        self,
        sport_key: str,
        regions: str = "eu",
        markets: str = "h2h",
        odds_format: str = "decimal",
        date_format: str = "iso",
    ):
        return self._get(
            f"/sports/{sport_key}/odds",
            regions=regions,
            markets=markets,
            oddsFormat=odds_format,
            dateFormat=date_format,
        )


if __name__ == "__main__":
    # маленький самотест
    client = OddsApiClient()
    data, info = client.get_sports()
    print("Sports status:", info)
    print("Пример вида спорта:", data[0] if data else None)
