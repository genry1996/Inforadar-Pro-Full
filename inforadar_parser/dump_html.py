from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# === ЖЁСТКО ПРОПИСЫВАЕМ РАБОЧИЙ ПРОКСИ (тот самый, что ты проверил через curl) ===
PROXY_URL = (
    "http://"
    "p5wCXOtxz2NYPe7k:"
    "ll0NYne2DSrm18Ot_country-de_session-R8xpzoY9_lifetime-30m"
    "@geo.iproyal.com:12321"
)

URL = "https://22betluck.com/line/football/"

def main():
    print("Запуск дампа HTML...")
    print(f"Открываем {URL}")
    print(f"Playwright proxy = {PROXY_URL}")

    proxy = {
        # ВАЖНО: прокси с логином/паролем в одной строке — как в curl -x
        "server": PROXY_URL
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,   # в контейнере только headless
            proxy=proxy,
        )
        page = browser.new_page()

        try:
            page.goto(URL, timeout=120_000, wait_until="load")
        except PlaywrightTimeoutError as e:
            print("❌ Timeout при переходе на страницу:", e)

        # даём странице ещё 3 секунды "подышать"
        page.wait_for_timeout(3000)

        html = page.content()
        out_path = "/app/page.html"
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(html)

        print(f"✅ HTML сохранён в {out_path}")
        browser.close()

if __name__ == "__main__":
    main()
