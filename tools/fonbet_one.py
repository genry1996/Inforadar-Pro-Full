import os
import json
import argparse
import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse, unquote

from playwright.async_api import async_playwright


DEFAULT_URL = "https://fonbet.com.cy/sports/football?mode=1&dateInterval=5"


# ----------------------------
# .env loader (no deps)
# ----------------------------
def _load_env_file(path: Path, override: bool = False) -> bool:
    if not path.exists():
        return False

    try:
        raw = path.read_text(encoding="utf-8-sig")
    except Exception:
        raw = path.read_text(encoding="utf-8", errors="ignore")

    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip()

        # strip quotes
        if len(v) >= 2 and ((v[0] == v[-1] == '"') or (v[0] == v[-1] == "'")):
            v = v[1:-1]

        if not override and os.environ.get(k) is not None:
            continue
        os.environ[k] = v
    return True


def load_env_auto() -> List[str]:
    """
    Loads:
      1) <repo_root>/.env   (D:\Inforadar_Pro\.env)
      2) <cwd>/.env
    """
    loaded_from: List[str] = []

    # tools/fonbet_one.py -> repo_root is parent of tools
    repo_root = Path(__file__).resolve().parents[1]
    root_env = repo_root / ".env"
    cwd_env = Path.cwd() / ".env"

    if _load_env_file(root_env, override=False):
        loaded_from.append(str(root_env))
    if cwd_env != root_env and _load_env_file(cwd_env, override=False):
        loaded_from.append(str(cwd_env))

    return loaded_from


# ----------------------------
# proxy helpers
# ----------------------------
def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name, default) or "").strip()


def _parse_proxy_url(proxy_url: str) -> Optional[Dict[str, str]]:
    """
    Accepts:
      http://host:port
      http://user:pass@host:port
    Returns Playwright proxy dict.
    """
    if not proxy_url:
        return None
    p = urlparse(proxy_url)
    if not p.scheme or not p.hostname or not p.port:
        return None

    pr: Dict[str, str] = {"server": f"{p.scheme}://{p.hostname}:{p.port}"}
    if p.username:
        pr["username"] = unquote(p.username)
    if p.password:
        pr["password"] = unquote(p.password)
    return pr


def proxy_from_sources(args) -> Optional[Dict[str, str]]:
    # 1) CLI --proxy (full)
    if args.proxy:
        pr = _parse_proxy_url(args.proxy)
        if pr:
            return pr

    # 2) CLI split
    if args.proxy_server:
        pr: Dict[str, str] = {"server": args.proxy_server}
        if args.proxy_username:
            pr["username"] = args.proxy_username
        if args.proxy_password:
            pr["password"] = args.proxy_password
        return pr

    # 3) ENV
    server = _env("FONBET_PROXY_SERVER")
    user = _env("FONBET_PROXY_USERNAME")
    pwd = _env("FONBET_PROXY_PASSWORD")
    if not server:
        return None
    pr2: Dict[str, str] = {"server": server}
    if user:
        pr2["username"] = user
    if pwd:
        pr2["password"] = pwd
    return pr2


# ----------------------------
# capture helpers
# ----------------------------
def is_json_ct(ct: str) -> bool:
    ct = (ct or "").lower()
    return ("application/json" in ct) or ("text/json" in ct) or ("+json" in ct)


def short_headers(h: Dict[str, str]) -> Dict[str, str]:
    keep = {}
    for k in ("accept", "content-type", "referer", "origin", "x-requested-with"):
        if k in h:
            keep[k] = h[k]
    return keep


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


async def main() -> None:
    loaded = load_env_auto()

    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--manual", action="store_true")
    ap.add_argument("--capture-seconds", type=int, default=int(_env("FONBET_CAPTURE_SECONDS", "60") or "60"))
    ap.add_argument("--max-blocks", type=int, default=400)
    ap.add_argument("--profile-dir", default="fonbet_profile")
    ap.add_argument("--debug-dir", default="fonbet_debug")
    ap.add_argument("--capture-json", default="captured.json")
    ap.add_argument("--storage-state", default="storage_state.json")

    # proxy options
    ap.add_argument("--proxy", default=None, help="e.g. http://user:pass@host:port or http://host:port")
    ap.add_argument("--proxy-server", default=None, help="e.g. http://host:port")
    ap.add_argument("--proxy-username", default=None)
    ap.add_argument("--proxy-password", default=None)

    # extra logging (helps when content-type is not json)
    ap.add_argument("--log-requests", action="store_true", help="log xhr/fetch/websocket requests")
    args = ap.parse_args()

    debug = Path(args.debug_dir)
    profile_dir = Path(args.profile_dir)
    debug.mkdir(parents=True, exist_ok=True)
    profile_dir.mkdir(parents=True, exist_ok=True)

    proxy = proxy_from_sources(args)

    if loaded:
        print("[env] loaded from:", " | ".join(loaded))
    else:
        print("[env] not loaded (no .env found). If proxy is needed, set env vars or use --proxy.")

    print("Proxy:", proxy.get("server") if proxy else "(none)")
    print("OPEN:", args.url)

    captured: List[Dict[str, Any]] = []
    seen = set()

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            channel="chrome",
            headless=not args.manual,
            proxy=proxy,
            viewport={"width": 1500, "height": 900},
            locale="ru-RU",
            timezone_id="Europe/Paris",
            args=["--no-default-browser-check"],
        )
        context.set_default_timeout(60000)

        page = context.pages[0] if context.pages else await context.new_page()

        if args.log_requests:
            def on_request(req):
                if req.resource_type in ("xhr", "fetch", "websocket"):
                    print(f"[req:{req.resource_type}] {req.method} {req.url}")
            page.on("request", on_request)

        async def on_response(resp):
            try:
                ct = (resp.headers or {}).get("content-type", "")
                # оставим фильтр json, но только на СБОР в файл; запросы можно видеть через --log-requests
                if not is_json_ct(ct):
                    return

                url = resp.url
                key = (url, resp.status)
                if key in seen:
                    return
                seen.add(key)

                req = resp.request
                item = {
                    "url": url,
                    "status": resp.status,
                    "content_type": ct,
                    "method": req.method,
                    "resource_type": req.resource_type,
                    "req_headers": short_headers(req.headers),
                }

                js = await resp.json()
                item["json"] = js

                captured.append(item)
                if len(captured) <= 25:
                    print(f"[json] {resp.status} {url}")
            except Exception:
                return

        context.on("response", on_response)

        try:
            await page.goto(args.url, wait_until="domcontentloaded", timeout=120000)
            await asyncio.sleep(1)

            # закрыть модалки
            if args.manual:
                for _ in range(3):
                    try:
                        await page.keyboard.press("Escape")
                    except Exception:
                        pass
                    await asyncio.sleep(0.2)

            await dump_page(page, debug, "after_goto")

            if args.manual:
                print("Если есть модалка/баннер — закрой (X) или ESC. Скрипт НЕ обходит CF, только ловит JSON.")

            print(f"Capturing JSON for {args.capture_seconds}s ...")
            try:
                await page.mouse.wheel(0, 900)
                await asyncio.sleep(0.4)
                await page.mouse.wheel(0, -900)
            except Exception:
                pass

            await asyncio.sleep(max(1, args.capture_seconds))

        finally:
            cap_path = debug / args.capture_json
            cap_path.write_text(json.dumps(captured, ensure_ascii=False, indent=2), encoding="utf-8")
            print("Captured JSON blocks:", len(captured))
            print("Saved:", str(cap_path.resolve()))

            try:
                st_path = debug / args.storage_state
                await context.storage_state(path=str(st_path))
                print("Saved storage state:", str(st_path.resolve()))
            except Exception:
                pass

            try:
                await context.close()
            except Exception:
                pass

    # короткий вывод кандидатов
    pats = ("events", "line", "market", "coupon", "prematch", "sports", "factorscatalog")
    cands = [x["url"] for x in captured if any(p in x["url"].lower() for p in pats)]
    print("\nTop candidate URLs:")
    for u in cands[:25]:
        print("-", u)


if __name__ == "__main__":
    asyncio.run(main())
