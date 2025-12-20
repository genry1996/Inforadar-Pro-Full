# settings_editor.py - ИСПРАВЛЕННАЯ ВЕРСИЯ
import asyncio
import json
import os
from playwright.async_api import async_playwright

SETTINGS_FILE = "D:/Inforadar_Pro/config/thresholds.json"

async def edit_settings():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()
        
        # Загрузить текущие настройки
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                current = json.load(f)
        else:
            current = {}
        
        # Значения по умолчанию
        defaults = {
            "sharp_drop_high": 25,
            "sharp_drop_mid": 15,
            "sharp_drop_low": 14,
            "money_min": 3000,
            "value_bet": 13,
            "unbalanced_flow": 70,
            "unbalanced_total_min": 5000,
            "value_bet_bookmakers": ["22bet"]
        }
        
        # Объединить с дефолтными значениями
        settings = {**defaults, **current}
        
        bookmakers_html = ""
        for bk in ["22bet", "pinnacle", "bet365", "marathonbet", "1xbet", "fonbet"]:
            checked = "checked" if bk in settings["value_bet_bookmakers"] else ""
            bookmakers_html += f'<input type="checkbox" class="bk-checkbox" value="{bk}" {checked}> {bk.title()} &nbsp;&nbsp;'
        
        # HTML форма
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
            <style>
                body {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 40px; }}
                .container {{ max-width: 900px; background: white; padding: 40px; border-radius: 20px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1 class="text-center mb-4">⚙️ Настройки Betwatch</h1>
                
                <div class="row">
                    <div class="col-md-4 mb-3">
                        <label>📉 Sharp Drop High (%)</label>
                        <input type="number" class="form-control" id="sharp_drop_high" value="{settings['sharp_drop_high']}">
                    </div>
                    <div class="col-md-4 mb-3">
                        <label>📉 Sharp Drop Mid (%)</label>
                        <input type="number" class="form-control" id="sharp_drop_mid" value="{settings['sharp_drop_mid']}">
                    </div>
                    <div class="col-md-4 mb-3">
                        <label>📉 Sharp Drop Low (%)</label>
                        <input type="number" class="form-control" id="sharp_drop_low" value="{settings['sharp_drop_low']}">
                    </div>
                </div>
                
                <div class="row">
                    <div class="col-md-4 mb-3">
                        <label>💰 Money Min (EUR)</label>
                        <input type="number" class="form-control" id="money_min" value="{settings['money_min']}">
                    </div>
                    <div class="col-md-4 mb-3">
                        <label>💎 Value Bet (%)</label>
                        <input type="number" class="form-control" id="value_bet" value="{settings['value_bet']}">
                    </div>
                    <div class="col-md-4 mb-3">
                        <label>⚖️ Unbalanced Flow (%)</label>
                        <input type="number" class="form-control" id="unbalanced_flow" value="{settings['unbalanced_flow']}">
                    </div>
                </div>
                
                <div class="mb-3">
                    <label class="form-label"><strong>📚 Букмекеры для Value Bet:</strong></label><br>
                    {bookmakers_html}
                </div>
                
                <button class="btn btn-success btn-lg w-100" id="saveBtn">💾 СОХРАНИТЬ</button>
                <div id="result" class="mt-3"></div>
            </div>
        </body>
        </html>
        """
        
        await page.set_content(html)
        
        print("🎯 Измените настройки и нажмите СОХРАНИТЬ...")
        
        await page.locator("#saveBtn").wait_for()
        await page.locator("#saveBtn").click()
        
        # Получить данные
        new_settings = {
            "sharp_drop_high": await page.evaluate("() => parseInt(document.getElementById('sharp_drop_high').value)"),
            "sharp_drop_mid": await page.evaluate("() => parseInt(document.getElementById('sharp_drop_mid').value)"),
            "sharp_drop_low": await page.evaluate("() => parseInt(document.getElementById('sharp_drop_low').value)"),
            "money_min": await page.evaluate("() => parseInt(document.getElementById('money_min').value)"),
            "value_bet": await page.evaluate("() => parseInt(document.getElementById('value_bet').value)"),
            "unbalanced_flow": await page.evaluate("() => parseInt(document.getElementById('unbalanced_flow').value)"),
            "unbalanced_total_min": 5000,
            "value_bet_bookmakers": await page.evaluate("""
                () => {
                    const bookmakers = [];
                    document.querySelectorAll('.bk-checkbox:checked').forEach(cb => {
                        bookmakers.push(cb.value);
                    });
                    return bookmakers;
                }
            """)
        }
        
        # Сохранить
        os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(new_settings, f, indent=4, ensure_ascii=False)
        
        await page.evaluate("""
            () => {
                document.getElementById('result').innerHTML = 
                    '<div class="alert alert-success">✅ Сохранено в thresholds.json!</div>';
            }
        """)
        
        print("✅ Настройки сохранены в:", SETTINGS_FILE)
        await asyncio.sleep(3)
        await browser.close()

if __name__ == "__main__":
    asyncio.run(edit_settings())
