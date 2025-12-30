import asyncio
import os
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any

from dotenv import load_dotenv
from playwright.async_api import async_playwright


# Project root: ...\inforadar_parser\parsers\fonbet\probe\fonbet_probe.py -> parents[4] == D:\Inforadar_Pro
ROOT = Path(__file__).resolve().parents[4]
ENV_PATH = ROOT / ".env"
if ENV_PATH.exists():
    load_dotenv(str(ENV_PATH))
else:
    load_dotenv()

TARGET_URL = os.getenv("FONBET_TARGET_URL", "https://fonbet.com.cy/sports/football?mode=1&dateInterval=5")

OUT_DIR = ROOT / "data" / "fonbet_probe"
OUT_DIR.mkdir(parents=True, exist_ok=True)

PROFILE_DIR = ROOT / "data" / "fonbet_profile"
PROFILE_DIR.mkdir(parents=True, exist_ok=True)

# If you don't have Google Chrome found by Playwright, set FONBET_CHROME_CHANNEL=0
USE_CHROME_CHANNEL = (os.getenv("FONBET_CHROME_CHANNEL", "1") or "1").strip() in ("1", "true", "True")


def ts() -> str:
    return datetime.utcnow().strftime("%Y%m%d_%H%M%S")


def proxy_from_env() -> Optional[Dict[str, Any]]:
    server = (os.getenv("FONBET_PROXY_SERVER") or "").strip()
    user = (os.getenv("FONBET_PROXY_USERNAME") or "").strip()
    pwd = (os.getenv("FONBET_PROXY_PASSWORD") or "").strip()
    if not server:
        return None
    cfg: Dict[str, Any] = {"server": server}
    if user:
        cfg["username"] = user
    if pwd:
        cfg["password"] = pwd
    return cfg


async def main():
    proxy_cfg = proxy_from_env()

    stamp = ts()
    har_path = OUT_DIR / f"fonbet_{stamp}.har"
    ws_log_path = OUT_DIR / f"fonbet_{stamp}_ws.log"

    print("\n[FONBET PROBE v3]")
    print(f"root     : {ROOT}")
    print(f"env      : {ENV_PATH} (exists={ENV_PATH.exists()})")
    print(f"target   : {TARGET_URL}")
    print(f"proxy    : {('ON ' + proxy_cfg['server']) if proxy_cfg else 'OFF'}")
    print(f"profile  : {PROFILE_DIR}")
    print(f"har_out  : {har_path}")
    print(f"ws_log   : {ws_log_path}")
    print("----------------------------------------------------------------")

    async with async_playwright() as p:
        launch_kwargs = dict(
            user_data_dir=str(PROFILE_DIR),
            headless=False,
            proxy=proxy_cfg,
            viewport={"width": 1400, "height": 900},
            record_har_path=str(har_path),
            record_har_content="embed",
        )
        if USE_CHROME_CHANNEL:
            launch_kwargs["channel"] = "chrome"

        ctx = await p.chromium.launch_persistent_context(**launch_kwargs)

        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        # Log XHR/Fetch
        page.on("request", lambda r: print(f"[REQ] {r.method} {r.url}") if r.resource_type in ("xhr", "fetch") else None)

        # WebSocket logging (optional)
        def on_websocket(ws):
            print(f"[WS] open {ws.url}")

            def _append(label: str, frame):
                with open(ws_log_path, "a", encoding="utf-8") as f:
                    f.write(f"\n--- {label} {ws.url} ---\n{frame}\n")

            ws.on("framereceived", lambda frame: _append("RECEIVED", frame))
            ws.on("framesent", lambda frame: _append("SENT", frame))

        page.on("websocket", on_websocket)

        # 1) Show the *actual* exit IP as seen by the browser
        await page.goto("https://api.ipify.org/?format=json", wait_until="domcontentloaded")
        ipify = (await page.text_content("body")) or ""
        print(f"\n[IPIFY] {ipify.strip()}\n")

        # 2) Open Fonbet page (you may see Cloudflare checkbox)
        print(f"Opening: {TARGET_URL}")
        await page.goto(TARGET_URL, wait_until="domcontentloaded")

        print("\n=== Если видишь Cloudflare чекбокс/капчу ===")
        print("Пройди её руками в окне браузера.")
        print("Когда увидишь страницу с матчами/линией — вернись сюда и нажми ENTER.\n")
        input()

        # Trigger extra network calls
        await page.mouse.wheel(0, 4000)
        await page.wait_for_timeout(8000)

        await ctx.close()

    print(f"Saved HAR: {har_path}")
    print(f"Saved WS log: {ws_log_path}")


if __name__ == "__main__":
    asyncio.run(main())
