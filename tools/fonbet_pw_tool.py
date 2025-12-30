import os
import re
import json
import time
import argparse
import asyncio
from typing import Dict, List, Tuple, Optional

from playwright.async_api import async_playwright

LIST_URL_DEFAULT = "https://fonbet.com.cy/sports/football?mode=1&dateInterval=5"

EVENT_HREF_RE = re.compile(r"^/sports/football/country/[^/]+/\d+/(\d+)$")
ODD_RE = re.compile(r"^\d+(\.\d+)?$")


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name, default) or "").strip()


def _proxy_from_env() -> Optional[dict]:
    server = _env("FONBET_PROXY_SERVER")
    if not server:
        return None
    user = _env("FONBET_PROXY_USERNAME")
    pwd = _env("FONBET_PROXY_PASSWORD")
    proxy = {"server": server}
    if user and pwd:
        proxy["username"] = user
        proxy["password"] = pwd
    return proxy


def _clean_lines(text: str) -> List[str]:
    lines = []
    for raw in text.splitlines():
        s = raw.replace("\u00a0", " ").strip()
        if s:
            lines.append(s)
    return lines


def _find_teams(lines: List[str]) -> Tuple[Optional[str], Optional[str]]:
    # чаще всего на странице встречается "A - B" или "A — B"
    for ln in lines:
        if " — " in ln:
            a, b = ln.split(" — ", 1)
            if a.strip() and b.strip():
                return a.strip(), b.strip()
        if " - " in ln:
            a, b = ln.split(" - ", 1)
            if a.strip() and b.strip():
                return a.strip(), b.strip()
    # fallback: иногда рядом отдельные строки, как у тебя было
    for i in range(1, len(lines) - 1):
        if lines[i] == "-" and lines[i - 1] and lines[i + 1]:
            return lines[i - 1], lines[i + 1]
    return None, None


def _pick_odd(block: List[str], label: str) -> Optional[float]:
    for i in range(len(block) - 1):
        if block[i] == label and ODD_RE.match(block[i + 1]):
            try:
                return float(block[i + 1])
            except Exception:
                return None
    return None


async def _wait_links(page, timeout_ms: int = 60000):
    # ждём появления ссылок на матчи
    await page.wait_for_function(
        """() => Array.from(document.querySelectorAll('a[href]'))
            .some(a => (a.getAttribute('href') || '').includes('/sports/football/country/'))""",
        timeout=timeout_ms,
    )


async def cmd_matches(args) -> int:
    proxy = _proxy_from_env()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=args.headless, proxy=proxy)
        context = await browser.new_context(
            locale="ru-RU",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        )
        page = await context.new_page()

        await page.goto(args.url, wait_until="domcontentloaded", timeout=90000)

        # иногда контент появляется не сразу
        await _wait_links(page, timeout_ms=90000)

        # чуть проскроллим, чтобы подгрузило побольше
        for _ in range(3):
            await page.mouse.wheel(0, 1200)
            await page.wait_for_timeout(700)

        items = await page.eval_on_selector_all(
            "a[href]",
            """els => els.map(a => ({
                href: a.getAttribute('href'),
                text: (a.innerText || '').trim()
            }))""",
        )

        matches = []
        seen = set()
        for it in items:
            href = (it.get("href") or "").strip()
            if not href:
                continue
            m = EVENT_HREF_RE.match(href)
            if not m:
                continue
            eid = m.group(1)
            if eid in seen:
                continue
            seen.add(eid)
            name = " ".join((it.get("text") or "").split()) or f"event {eid}"
            matches.append((int(eid), name, "https://fonbet.com.cy" + href))

        matches = matches[: args.limit]

        print(f"URL: {args.url}")
        print(f"Found matches: {len(matches)}")
        print("-" * 120)
        for eid, name, url in matches:
            print(f"{eid} | {name} | {url}")

        if args.save_json:
            with open(args.save_json, "w", encoding="utf-8") as f:
                json.dump(
                    [{"id": eid, "name": name, "url": url} for eid, name, url in matches],
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
            print(f"Saved: {args.save_json}")

        await context.close()
        await browser.close()

    return 0


async def cmd_odds(args) -> int:
    proxy = _proxy_from_env()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=args.headless, proxy=proxy)
        context = await browser.new_context(
            locale="ru-RU",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        )
        page = await context.new_page()

        await page.goto(args.url, wait_until="domcontentloaded", timeout=90000)
        await page.wait_for_timeout(2500)

        text = await page.inner_text("body")
        lines = _clean_lines(text)

        home, away = _find_teams(lines)

        data: Dict = {"teams": {"home": home, "away": away}, "markets": {}}

        # 1X2
        if "Full time result" in lines:
            idx = lines.index("Full time result")
            block = lines[idx + 1: idx + 120]
            if home and away:
                data["markets"]["1X2"] = {
                    "1": _pick_odd(block, home),
                    "X": _pick_odd(block, "Draw"),
                    "2": _pick_odd(block, away),
                }

        # Totals (грубо)
        totals = []
        if "Total goals" in lines:
            idx = lines.index("Total goals")
            block = lines[idx + 1: idx + 400]
            for i in range(len(block) - 3):
                if block[i].startswith("Total "):
                    try:
                        line_val = float(block[i].split(" ", 1)[1].strip())
                    except Exception:
                        continue
                    if ODD_RE.match(block[i + 1]) and ODD_RE.match(block[i + 2]):
                        totals.append(
                            {"line": line_val, "over": float(block[i + 1]), "under": float(block[i + 2])}
                        )
            if totals:
                data["markets"]["Totals"] = totals[:40]

        print(json.dumps(data, ensure_ascii=False, indent=2 if args.pretty else None))

        await context.close()
        await browser.close()

    return 0


def build_parser():
    ap = argparse.ArgumentParser("fonbet_pw_tool.py")
    ap.add_argument("--headless", action="store_true", help="по умолчанию запускается с окном")
    sub = ap.add_subparsers(dest="cmd", required=True)

    m = sub.add_parser("matches")
    m.add_argument("--url", default=LIST_URL_DEFAULT)
    m.add_argument("--limit", type=int, default=30)
    m.add_argument("--save-json", default="")
    m.set_defaults(func=cmd_matches)

    o = sub.add_parser("odds")
    o.add_argument("--url", required=True)
    o.add_argument("--pretty", action="store_true")
    o.set_defaults(func=cmd_odds)

    return ap


def main():
    args = build_parser().parse_args()
    return asyncio.run(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
