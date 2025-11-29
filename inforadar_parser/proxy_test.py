import asyncio
from playwright.async_api import async_playwright
import os

PROXY = os.getenv("PLAYWRIGHT_PROXY", "socks5://api6c4c28f3734e47c5:W5HMlkDB@176.103.231.20:50100")

async def main():
    print("Using proxy:", PROXY)

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                proxy={"server": PROXY}
            )
            page = await browser.new_page()
            await page.goto("https://www.22bet.com/")
            html = await page.content()
            print("Page loaded, length:", len(html))
            await browser.close()
    except Exception as e:
        print("ERROR:", e)

asyncio.run(main())
