import asyncio
from playwright.async_api import async_playwright

PROXY = {
    "server": "http://195.158.195.70:8000",
    "username": "koWQgu",
    "password": "N023zZ"
}

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(proxy=PROXY, headless=True)
        context = await browser.new_context()
        page = await context.new_page()
        try:
            await page.goto("https://api.ipify.org/?format=json", timeout=15000)
            print(await page.content())
        except Exception as e:
            print("ERROR:", e)
        await browser.close()

asyncio.run(main())
