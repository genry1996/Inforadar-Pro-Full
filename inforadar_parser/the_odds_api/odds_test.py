# -*- coding: utf-8 -*-
"""
odds_test.py — тест The Odds API (Starter план).
"""

print(">>> odds_test.py: файл загружен")

import os
import sys
import requests

# 🔑 Ключ берём только из переменной окружения
API_KEY = os.getenv("ODDS_API_KEY")
if not API_KEY:
    raise RuntimeError("ODDS_API_KEY is not set")

BASE_URL = "https://api.the-odds-api.com/v4"


def get_sports():
    """Список видов спорта (не тратит кредиты)."""
    print(">>> get_sports() called")
    url = f"{BASE_URL}/sports"
    params = {
        "apiKey": API_KEY,
        "all": "true",  # показать все, а не только in-season
    }
    print(">>> REQUEST (sports):", url, params)
    r = requests.get(url, params=params, timeout=15)
    print("Sports status:", r.status_code)
    print("x-requests-remaining:", r.headers.get("x-requests-remaining"))
    print("x-requests-used:", r.headers.get("x-requests-used"))
    r.raise_for_status()
    return r.json()


def get_odds(sport_key: str):
    """Коэффициенты по одному виду спорта (тратит кредиты)."""
    print(f">>> get_odds({sport_key}) called")
    url = f"{BASE_URL}/sports/{sport_key}/odds"
    params = {
        "apiKey": API_KEY,
        "regions": "eu",
        "markets": "h2h",
        "oddsFormat": "decimal",
        "dateFormat": "iso",
    }
    print(">>> REQUEST (odds):", url, params)
    r = requests.get(url, params=params, timeout=20)
    print("Odds status:", r.status_code)
    print("x-requests-remaining:", r.headers.get("x-requests-remaining"))
    print("x-requests-used:", r.headers.get("x-requests-used"))
    r.raise_for_status()
    return r.json()


def main():
    print(">>> main() entered")
    print(">>> cwd:", os.getcwd())
    print(">>> python exe:", sys.executable)

    # 1) забираем виды спорта
    sports = get_sports()
    print("\n=== ПЕРВЫЕ 5 ВИДОВ СПОРТА ===")
    for s in sports[:5]:
        print(f"- {s['key']} | {s['title']} | active={s['active']}")

    # пример – английская Премьер-лига
    sport_key = "soccer_epl"
    print(f"\n=== ПРИМЕР: {sport_key} ===")

    events = get_odds(sport_key)
    print("Событий получено:", len(events))

    for ev in events[:5]:
        print(f"\n{ev['commence_time']} | {ev['home_team']} vs {ev['away_team']}")
        if not ev.get("bookmakers"):
            continue
        bm = ev["bookmakers"][0]
        print("  БК:", bm["title"])
        for m in bm.get("markets", []):
            if m["key"] == "h2h":
                line = ", ".join(
                    f"{o['name']} -> {o['price']}" for o in m["outcomes"]
                )
                print("   H2H:", line)
                break


if __name__ == "__main__":
    print(">>> __main__ block started")
    try:
        main()
    except Exception as e:
        print(">>> ERROR:", repr(e), file=sys.stderr)
