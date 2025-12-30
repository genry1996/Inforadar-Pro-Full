$code = @'
import os
import re
import json
import argparse
import asyncio
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple

from playwright.async_api import async_playwright, TimeoutError as PWTimeout

LIST_URL = "https://fonbet.com.cy/sports/football?mode=1&dateInterval=5"

EVENT_HREF_RE = re.compile(r"^/sports/football/country/[^/]+/\d+/(\d+)$")

MARKET_1X2_KEYS = [
    "Full time result",
    "Match result",
    "Исход матча",
    "Результат матча",
]
DRAW_KEYS = ["Draw", "Ничья"]

ODD_RE = re.compile(r"^\d{1,3}(\.\d{2,3})?$")


def env(name: str, default: str = "") -> str:
    return (os.getenv(name, default) or "").strip()


def proxy_from_env() -> Optional[dict]:
    server = env("FONBET_PROXY_SERVER")
    if not server:
        return None
    user = env("FONBET_PROXY_USERNAME")
    pwd = env("FONBET_PROXY_PASSWORD")
    pr = {"server": server}
    if user and pwd:
        pr["username"] = user
        pr["password"] = pwd
    return pr


def clean_lines(text: str) -> List[str]:
    out = []
    for raw in text.splitlines():
        s = raw.replace("\u00a0", " ").strip()
        if s:
            out.append(s)
    return out


def find_first_match_links(items: List[dict], limit: int) -> List[Tuple[int, str, str]]:
    seen = set()
    res = []
    for it in items:
        href = (it.get("href") or "").strip()
        if not href:
            continue
        m = EVENT_HREF_RE.match(href)
        if not m:
            continue
        eid = int(m.group(1))
        if eid in seen:
            continue
        seen.add(eid)
        title = " ".join((it.get("text") or "").split()) or f"event {eid}"
        res.append((eid, title, "https://fonbet.com.cy" + href))
        if len(res) >= limit:
            break
    return res


def detect_teams(lines: List[str]) -> Tuple[Optional[str], Optional[str]]:
    for ln in lines:
        if " — " in ln:
            a, b = ln.split(" — ", 1)
            if a.strip() and b.strip():
                return a.strip(), b.strip()
        if " - " in ln:
            a, b = ln.split(" - ", 1)
            if a.strip() and b.strip():
                return a.strip(), b.strip()
    for i in range(1, len(lines) - 1):
        if lines[i] == "-" and lines[i - 1] and lines[i + 1]:
            return lines[i - 1], lines[i + 1]
    return None, None


def pick_odd(block: List[str], label: str) -> Optional[float]:
    for i in range(len(block) - 1):
        if block[i] == label and ODD_RE.match(block[i + 1]):
            try:
                return float(block[i + 1])
            except Exception:
                return None
    return None


def parse_1x2(lines: List[str]) -> Dict[str, Any]:
    home, away = detect_teams(lines)
    data: Dict[str, Any] = {"teams": {"home": home, "away": away}, "markets": {}}

    idx = None
    for k in MARKET_1X2_KEYS:
        if k in lines:
            idx = lines.index(k)
            break
    if idx is None:
        return data

    block = lines[idx + 1 : idx + 160]
    if not home or not away:
        odds = [x for x in block if ODD_RE.match(x)]
        if len(odds) >= 3:
            data["markets"]["1X2"] = {"1": float(odds[0]), "X": float(odds[1]), "2": float(odds[2])}
        return data

    draw_label = None
    for d in DRAW_KEYS:
        if d in block:
            draw_label = d
            break
    if draw_label is None:
        draw_label = "Draw"

    data["markets"]["1X2"] = {
        "1": pick_odd(block, home),
        "X": pick_odd(block, draw_label),
        "2": pick_odd(block, away),
    }
    return data


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=LIST_URL)
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--index", type=int, default=0)
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--debug-dir", default="fonbet_debug")
    args = ap.parse_args()

    debug = Path(args.debug_dir)
    debug.mkdir(parents=True, exist_ok=True)

    proxy = proxy_from_env()

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=args.headless,
            proxy=proxy,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-default-browser-check",
                "--disable-features=IsolateOrigins,site-per-process",
            ],
        )
        context = await browser.new_context(
            locale="ru-RU",
            timezone_id="Europe/Stockholm",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1400, "height": 900},
        )
        await context.add_init_script(
            """() => { Object.defineProperty(navigator, 'webdriver', {get: () => undefined}); }"""
        )

        page = await context.new_page()

        print("OPEN:", args.url)
        try:
            await page.goto(args.url, wait_until="domcontentloaded", timeout=90000)
        except PWTimeout:
            print("WARN: goto timeout, continue...")

        await page.wait_for_timeout(2500)

        try:
            await page.wait_for_function(
                """() => Array.from(document.querySelectorAll('a[href]'))
                    .some(a => (a.getAttribute('href')||'').includes('/sports/football/country/'))""",
                timeout=60000,
            )
        except PWTimeout:
            await page.screenshot(path=str(debug / "list_timeout.png"), full_page=True)
            (debug / "list_timeout.html").write_text(await page.content(), encoding="utf-8")
            (debug / "list_timeout_body.txt").write_text(await page.inner_text("body"), encoding="utf-8")
            print("FAIL: match links not found. Saved debug/list_timeout.*")
            await context.close()
            await browser.close()
            return

        for _ in range(3):
            await page.mouse.wheel(0, 1400)
            await page.wait_for_timeout(600)

        await page.screenshot(path=str(debug / "list.png"), full_page=True)
        (debug / "list.html").write_text(await page.content(), encoding="utf-8")

        items = await page.eval_on_selector_all(
            "a[href]",
            """els => els.map(a => ({href: a.getAttribute('href'), text: (a.innerText||'').trim()}))""",
        )
        matches = find_first_match_links(items, args.limit)

        print(f"MATCH LINKS FOUND: {len(matches)}")
        for i, (eid, title, url) in enumerate(matches[: min(10, len(matches))]):
            print(f"{i:02d}) {eid} | {title} | {url}")

        if not matches:
            print("FAIL: 0 matches. See fonbet_debug/list.*")
            await context.close()
            await browser.close()
            return

        idx = max(0, min(args.index, len(matches) - 1))
        eid, title, event_url = matches[idx]

        print("\nOPEN EVENT:", eid, title)
        try:
            await page.goto(event_url, wait_until="domcontentloaded", timeout=90000)
        except PWTimeout:
            print("WARN: event goto timeout, continue...")

        await page.wait_for_timeout(2500)
        await page.screenshot(path=str(debug / f"event_{eid}.png"), full_page=True)
        (debug / f"event_{eid}.html").write_text(await page.content(), encoding="utf-8")

        body_text = await page.inner_text("body")
        (debug / f"event_{eid}_body.txt").write_text(body_text, encoding="utf-8")

        lines = clean_lines(body_text)
        data = parse_1x2(lines)
        data["event"] = {"id": eid, "title": title, "url": event_url}

        (debug / f"event_{eid}_parsed.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

        print("\nPARSED:")
        print(json.dumps(data, ensure_ascii=False, indent=2))

        await context.close()
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
'@

New-Item -ItemType Directory -Path .\tools -Force | Out-Null
Set-Content -Path .\tools\fonbet_one.py -Value $code -Encoding UTF8
