import os
import re
import json
import argparse
import asyncio
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple

from playwright.async_api import async_playwright, TimeoutError as PWTimeout, Error as PWError

LIST_URL = "https://fonbet.com.cy/sports/football?mode=1&dateInterval=5"
EVENT_HREF_RE = re.compile(r"^/sports/football/country/[^/]+/\d+/(\d+)$")

MARKET_1X2_KEYS = ["Full time result", "Match result", "Исход матча", "Результат матча"]
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

    block = lines[idx + 1: idx + 200]

    if not home or not away:
        odds = [x for x in block if ODD_RE.match(x)]
        if len(odds) >= 3:
            data["markets"]["1X2"] = {"1": float(odds[0]), "X": float(odds[1]), "2": float(odds[2])}
        return data

    draw_label = next((d for d in DRAW_KEYS if d in block), "Draw")
    data["markets"]["1X2"] = {
        "1": pick_odd(block, home),
        "X": pick_odd(block, draw_label),
        "2": pick_odd(block, away),
    }
    return data


async def dump_page(page, debug: Path, prefix: str):
    try:
        await page.screenshot(path=str(debug / f"{prefix}.png"), full_page=True)
    except Exception:
        pass
    try:
        (debug / f"{prefix}.html").write_text(await page.content(), encoding="utf-8")
    except Exception:
        pass
    try:
        (debug / f"{prefix}_body.txt").write_text(await page.inner_text("body"), encoding="utf-8")
    except Exception:
        pass


async def wait_enter(prompt: str):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: input(prompt))


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=LIST_URL)
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--index", type=int, default=0)
    ap.add_argument("--debug-dir", default="fonbet_debug")
    ap.add_argument("--manual", action="store_true", help="открыть окно и дать подтвердить 'я человек' вручную")
    args = ap.parse_args()

    debug = Path(args.debug_dir)
    debug.mkdir(parents=True, exist_ok=True)

    proxy = proxy_from_env()

    async with async_playwright() as p:
        # ВАЖНО: persistent context сохраняет cookies/локалсторадж между запусками
        profile_dir = debug / "profile"
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            channel="chrome", 
            headless=not args.manual,        # manual => окно
            proxy=proxy,
            args=["--no-default-browser-check"],
            viewport={"width": 1400, "height": 900},
            locale="ru-RU",
            timezone_id="Europe/Stockholm",
        )

        page = context.pages[0] if context.pages else await context.new_page()
        await context.add_init_script("() => { Object.defineProperty(navigator, 'webdriver', {get: () => undefined}); }")

        print("OPEN:", args.url)
        try:
            await page.goto(args.url, wait_until="domcontentloaded", timeout=90000)
        except PWTimeout:
            print("WARN: goto timeout, continue...")
        except PWError as e:
            print("ERROR: goto failed:", e)
            await dump_page(page, debug, "goto_failed")
            await context.close()
            return

        await asyncio.sleep(2)
        await dump_page(page, debug, "list_after_goto")

        # Если включилась защита — НЕ обходим, а просим вручную подтвердить
        if args.manual:
            # простой признак челленджа
            txt = ""
            try:
                txt = (await page.inner_text("body")).lower()
            except Exception:
                pass

            if "cloudflare" in txt or "подтвердите, что вы человек" in txt:
                print("CLOUDFLARE CHALLENGE detected. Solve it in the opened browser window.")
                await wait_enter("Когда решишь капчу/проверку — нажми Enter здесь... ")
                await asyncio.sleep(2)
                await dump_page(page, debug, "list_after_manual")

        # дальше — ждём ссылки матчей
        try:
            await page.wait_for_function(
                """() => Array.from(document.querySelectorAll('a[href]'))
                    .some(a => (a.getAttribute('href')||'').includes('/sports/football/country/'))""",
                timeout=60000,
            )
        except (PWTimeout, PWError) as e:
            print("FAIL: match links not found / page error:", e)
            await dump_page(page, debug, "list_timeout_or_error")
            await context.close()
            return

        # скролл для подгрузки
        for _ in range(3):
            await page.mouse.wheel(0, 1400)
            await asyncio.sleep(0.6)

        await dump_page(page, debug, "list_ready")

        items = await page.eval_on_selector_all(
            "a[href]",
            "els => els.map(a => ({href: a.getAttribute('href'), text: (a.innerText||'').trim()}))",
        )
        matches = find_first_match_links(items, args.limit)

        print(f"MATCH LINKS FOUND: {len(matches)}")
        for i, (eid, title, url) in enumerate(matches[: min(10, len(matches))]):
            print(f"{i:02d}) {eid} | {title} | {url}")

        if not matches:
            print("FAIL: 0 matches. See fonbet_debug/list_ready.*")
            await context.close()
            return

        idx = max(0, min(args.index, len(matches) - 1))
        eid, title, event_url = matches[idx]

        print("\nOPEN EVENT:", eid, title)
        await page.goto(event_url, wait_until="domcontentloaded", timeout=90000)
        await asyncio.sleep(2)
        await dump_page(page, debug, f"event_{eid}")

        body_text = ""
        try:
            body_text = await page.inner_text("body")
        except Exception:
            pass

        data = parse_1x2(clean_lines(body_text))
        data["event"] = {"id": eid, "title": title, "url": event_url}

        (debug / f"event_{eid}_parsed.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        print("\nPARSED:")
        print(json.dumps(data, ensure_ascii=False, indent=2))

        await context.close()


if __name__ == "__main__":
    asyncio.run(main())
