import asyncio
from playwright.async_api import async_playwright

PROXY = {
    "server": "http://142.111.48.253:7030",
    "username": "lknhyffv",
    "password": "ts7sg1ki2xhs"
}

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, proxy=PROXY)
        context = await browser.new_context()
        page = await context.new_page()
        try:
            await page.goto("https://api.ipify.org/?format=json", timeout=20000)
            print("SUCCESS:", await page.content())
        except Exception as e:
            print("ERROR:", e)
        await browser.close()

asyncio.run(main())
