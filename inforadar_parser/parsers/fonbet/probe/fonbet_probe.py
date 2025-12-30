import asyncio
import os
from datetime import datetime
from urllib.parse import urlparse, unquote

from playwright.async_api import async_playwright
from inforadar_parser.utils.proxy import build_proxy_url

TARGET_URL = os.getenv("FONBET_TARGET_URL", "https://fonbet.com.cy/sports/football?mode=1&dateInterval=5")
OUT_DIR = os.path.join("data", "fonbet_probe")
os.makedirs(OUT_DIR, exist_ok=True)

def _ts() -> str:
    return datetime.utcnow().strftime("%Y%m%d_%H%M%S")

def _proxy_for_playwright(proxy_url: str):
    if not proxy_url:
        return None
    p = urlparse(proxy_url)
    if not p.scheme or not p.hostname or not p.port:
        raise ValueError("Bad proxy URL format. Expected: http://user:pass@host:port")
    proxy = {"server": f"{p.scheme}://{p.hostname}:{p.port}"}
    if p.username:
        proxy["username"] = unquote(p.username)
    if p.password:
        proxy["password"] = unquote(p.password)
    return proxy

async def main():
    proxy_url = build_proxy_url("FONBET") or ""
    proxy_cfg = _proxy_for_playwright(proxy_url) if proxy_url else None

    stamp = _ts()
    har_path = os.path.join(OUT_DIR, f"fonbet_{stamp}.har")
    ws_log_path = os.path.join(OUT_DIR, f"fonbet_{stamp}_ws.log")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, proxy=proxy_cfg)
        context = await browser.new_context(
            viewport={"width": 1400, "height": 900},
            record_har_path=har_path,
            record_har_content="embed",
        )

        page = await context.new_page()

        def on_request(req):
            if req.resource_type in ("xhr", "fetch"):
                print(f"[REQ] {req.method} {req.url}")
        page.on("request", on_request)

        def on_websocket(ws):
            print(f"[WS] open {ws.url}")
            def _append(label: str, frame):
                with open(ws_log_path, "a", encoding="utf-8") as f:
                    f.write(f"\n--- {label} {ws.url} ---\n{frame}\n")
            ws.on("framereceived", lambda frame: _append("RECEIVED", frame))
            ws.on("framesent", lambda frame: _append("SENT", frame))
        page.on("websocket", on_websocket)

        print(f"Opening: {TARGET_URL}")
        await page.goto(TARGET_URL, wait_until="domcontentloaded")
        await page.wait_for_timeout(9000)
        await page.mouse.wheel(0, 2500)
        await page.wait_for_timeout(5000)

        await context.close()
        await browser.close()

    print(f"Saved HAR: {har_path}")
    print(f"Saved WS log: {ws_log_path}")

if __name__ == "__main__":
    asyncio.run(main())
