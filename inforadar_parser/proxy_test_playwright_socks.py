import asyncio
from playwright.async_api import async_playwright

PROXY = {
    "server": "socks5://45.145.161.146:62607",
    "username": "uwft8q1U",
    "password": "NNVPCRK4"
}

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(proxy=PROXY, headless=True)
        context = await browser.new_context()
        page = await context.new_page()
        try:
            await page.goto("https://api.ipify.org/?format=json", timeout=30000)
            print("SUCCESS:", await page.content())
        except Exception as e:
            print("ERROR:", e)
        await browser.close()

asyncio.run(main())
