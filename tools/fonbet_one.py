import os
import re
import json
import argparse
import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional

from playwright.async_api import async_playwright, Error as PWError


DEFAULT_URL = "https://fonbet.com.cy/sports/football?mode=1&dateInterval=5"


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name, default) or "").strip()


def proxy_from_env() -> Optional[Dict[str, str]]:
    server = _env("FONBET_PROXY_SERVER")
    user = _env("FONBET_PROXY_USERNAME")
    pwd = _env("FONBET_PROXY_PASSWORD")

    if not server:
        return None

    # защита от заглушек
    bad = ("YOUR_HOST", "YOUR_USER", "YOUR_PASS", "<", ">")
    if any(x in server for x in bad):
        return None

    pr: Dict[str, str] = {"server": server}
    if user:
        pr["username"] = user
    if pwd:
        pr["password"] = pwd
    return pr


async def dump_page(page, out_dir: Path, tag: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        (out_dir / f"{tag}.url.txt").write_text(page.url, encoding="utf-8")
    except Exception:
        pass
    try:
        html = await page.content()
        (out_dir / f"{tag}.html").write_text(html, encoding="utf-8")
    except Exception:
        pass
    try:
        await page.screenshot(path=str(out_dir / f"{tag}.png"), full_page=True)
    except Exception:
        pass


def json_deep_iter(obj: Any):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from json_deep_iter(v)
    elif isinstance(obj, list):
        for x in obj:
            yield from json_deep_iter(x)


def extract_events(payload: Any, limit: int = 50) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen = set()

    for d in json_deep_iter(payload):
        if not isinstance(d, dict):
            continue
        _id = d.get("id")
        if not isinstance(_id, int) or _id in seen:
            continue

        name = d.get("name") or d.get("eventName") or d.get("title")
        if not isinstance(name, str) or not name.strip():
            a = d.get("team1") or d.get("home") or d.get("teamHome")
            b = d.get("team2") or d.get("away") or d.get("teamAway")
            if isinstance(a, str) and isinstance(b, str) and a.strip() and b.strip():
                name = f"{a.strip()} — {b.strip()}"
            else:
                continue

        seen.add(_id)
        out.append({"id": _id, "name": name.strip()})
        if len(out) >= limit:
            break

    return out


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--manual", action="store_true")
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--capture-seconds", type=int, default=int(_env("FONBET_CAPTURE_SECONDS", "120") or "120"))
    ap.add_argument("--profile-dir", default="fonbet_profile")
    ap.add_argument("--debug-dir", default="fonbet_debug")
    ap.add_argument("--capture-json", default="captured.json")
    args = ap.parse_args()

    debug = Path(args.debug_dir)
    profile_dir = Path(args.profile_dir)
    debug.mkdir(parents=True, exist_ok=True)
    profile_dir.mkdir(parents=True, exist_ok=True)

    proxy = proxy_from_env()
    print("Proxy:", proxy.get("server") if proxy else "(none)")
    print("OPEN:", args.url)

    captured: List[Dict[str, Any]] = []
    seen_urls = set()

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            channel="chrome",
            headless=not args.manual,
            proxy=proxy,
            viewport={"width": 1400, "height": 900},
            locale="ru-RU",
            timezone_id="Europe/Stockholm",
            args=["--no-default-browser-check"],
        )
        context.set_default_timeout(60000)
        page = context.pages[0] if context.pages else await context.new_page()

        async def on_response(resp):
            try:
                ct = (resp.headers or {}).get("content-type", "")
                if "json" not in (ct or "").lower():
                    return

                url = resp.url
                # ловим только важные штуки, чтобы не раздувать
                if "events/" not in url and "line" not in url and "market" not in url:
                    return

                # чтобы не писать одно и то же много раз
                key = (url, resp.status)
                if key in seen_urls:
                    return
                seen_urls.add(key)

                js = await resp.json()
                captured.append({"url": url, "status": resp.status, "json": js})
            except Exception:
                return

        context.on("response", on_response)

        try:
            await page.goto(args.url, wait_until="domcontentloaded", timeout=120000)
            await asyncio.sleep(2)
            await dump_page(page, debug, "after_goto")

            if args.manual:
                print("Если есть Cloudflare — реши в окне и просто НЕ закрывай браузер.")
                print("Скрипт только ждёт и ловит JSON (не обходит).")

            print(f"Capturing JSON for {args.capture_seconds}s ...")
            await asyncio.sleep(max(1, args.capture_seconds))

        except Exception as e:
            print("ERROR during run:", repr(e))
            try:
                await dump_page(page, debug, "error")
            except Exception:
                pass
        finally:
            # ВАЖНО: сохраняем даже если было исключение
            cap_path = debug / args.capture_json
            try:
                cap_path.write_text(json.dumps(captured, ensure_ascii=False, indent=2), encoding="utf-8")
                print("Captured JSON blocks:", len(captured))
                print("Saved:", str(cap_path.resolve()))
            except Exception as e:
                print("FAILED to save captured.json:", repr(e))

            try:
                await context.close()
            except Exception:
                pass

    # Анализ: находим последний events/listBase или events/list
    best = None
    for item in reversed(captured):
        u = item.get("url", "")
        if "events/listBase" in u or "events/list" in u:
            best = item
            break

    if not best:
        print("No events/listBase or events/list captured.")
        print("Open fonbet_debug/captured.json and check what URLs were captured.")
        return

    payload = best.get("json")
    events = extract_events(payload, limit=args.limit)
    print("BEST URL:", best.get("url"))
    print(f"Events extracted: {len(events)}")
    for e in events[: args.limit]:
        print(f"- {e['id']}: {e['name']}")


if __name__ == "__main__":
    asyncio.run(main())
