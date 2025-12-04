from playwright.sync_api import sync_playwright

PROXY = "http://213.137.91.35:12323"   # ← Твой рабочий прокси

print("Запуск дампа HTML...")

with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=True,
        proxy={"server": PROXY}
    )

    context = browser.new_context()
    page = context.new_page()

    url = "https://22betluck.com/line/football/"   # зеркало, которое открывается у тебя
    print(f"Открываем {url}")

    page.goto(url, timeout=60000)
    page.wait_for_timeout(8000)

    html = page.content()

    with open("/app/page.html", "w", encoding="utf-8") as f:
        f.write(html)

    print("HTML успешно сохранён → /app/page.html")

    browser.close()
