import asyncio
import logging
import json
from pathlib import Path
from datetime import datetime
from playwright.async_api import async_playwright
import mysql.connector
import os
from dotenv import load_dotenv
from telegram_notifier import TelegramNotifier

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler("parser.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)

logger = logging.getLogger(__name__)

# ✅ ПАРАМЕТРЫ ДЕТЕКТОРА
DETECTION_THRESHOLD = float(os.getenv("DETECTION_THRESHOLD", "0.3"))
CONFIRMATION_DELAY = int(os.getenv("CONFIRMATION_DELAY", "5"))
UPDATE_INTERVAL = int(os.getenv("UPDATE_INTERVAL", "60"))

logger.info(
    f"⚙️ Параметры: THRESHOLD={DETECTION_THRESHOLD}%, "
    f"DELAY={CONFIRMATION_DELAY}s, UPDATE={UPDATE_INTERVAL}s"
)

# ✅ TELEGRAM НАСТРОЙКИ (для 22BET)
TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    "8403963559:AAFoF6QYeRr2CIH2NEeLBxh5BYRX6XTHNxo",
)
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "5377484616")
TELEGRAM_MIN_ALERT_THRESHOLD = float(
    os.getenv("TELEGRAM_MIN_ALERT_THRESHOLD", "2.0")
)

telegram_notifier = None
if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
    telegram_notifier = TelegramNotifier(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
    logger.info(
        f"📱 Telegram уведомления активированы "
        f"(@Oddly1xbet_bot, чат {TELEGRAM_CHAT_ID}, порог ≥{TELEGRAM_MIN_ALERT_THRESHOLD}%)"
    )
else:
    logger.warning("⚠️ Telegram не настроен (проверьте токен/чат id)")

# ✅ СОСТОЯНИЕ ДЕТЕКТОРА
STATE_FILE = Path("detector_state.json")
logger.info(f"📂 Файл состояния: {STATE_FILE.absolute()}")


def load_detector_state():
    """Загружаем состояние с диска"""
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                state = json.load(f)
            logger.info(
                f"✅ СОСТОЯНИЕ ЗАГРУЖЕНО: {len(state)} событий из {STATE_FILE}"
            )
            return state
        except Exception as e:
            logger.warning(f"⚠️ Ошибка загрузки состояния: {e}")
            return {}

    logger.info(f"📝 Файл состояния НЕ найден: {STATE_FILE} (первый запуск)")
    return {}


def save_detector_state(state):
    """Сохраняем состояние на диск"""
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        logger.info(
            f"💾 СОСТОЯНИЕ СОХРАНЕНО: {len(state)} событий в {STATE_FILE}"
        )
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения состояния: {e}")


def get_db_connection():
    return mysql.connector.connect(
        host=os.getenv("MYSQL_HOST", "localhost"),
        user=os.getenv("MYSQL_USER", "root"),
        password=os.getenv("MYSQL_PASSWORD", "ryban8991!"),
        database=os.getenv("MYSQL_DB", "inforadar"),
        autocommit=True,
    )


PROXY_CONFIG = {
    "server": "http://213.137.91.35:12323",
    "username": "14ab48c9d85c1",
    "password": "5d234f6517",
}

# ✅ ЗАГРУЖАЕМ СОСТОЯНИЕ ПРИ СТАРТЕ
global_detector_state = load_detector_state()


def detect_anomalies(current_events):
    """Детектор с сохранением состояния"""
    global global_detector_state
    anomalies = []

    logger.info(f"🔎 detect_anomalies() вызван с {len(current_events)} событиями")

    if not global_detector_state:
        logger.info(
            f"📝 ПЕРВЫЙ ЗАПУСК: инициализирую детектор с {len(current_events)} "
            f"событиями"
        )
        global_detector_state = {
            name: data.copy() for name, data in current_events.items()
        }
        save_detector_state(global_detector_state)
        logger.info("✅ Детектор готов к следующему запуску")
        return anomalies

    logger.info(
        f"🔍 СРАВНИВАЮ: {len(global_detector_state)} сохранённые vs "
        f"{len(current_events)} новые"
    )

    change_count = 0
    anomaly_count = 0

    for event_name, current_data in current_events.items():
        prev_data = global_detector_state.get(event_name)

        if not prev_data:
            logger.debug(f"🆕 Новое событие: {event_name}")
            continue

        for outcome in ["1", "X", "2"]:
            prev_odd = prev_data.get("odds", {}).get(outcome)
            curr_odd = current_data.get("odds", {}).get(outcome)

            if (
                prev_odd is None
                or curr_odd is None
                or prev_odd <= 0
                or curr_odd <= 0
            ):
                continue

            change_pct = (curr_odd - prev_odd) / prev_odd * 100

            if abs(change_pct) > 0.5:
                change_count += 1
                logger.info(
                    f"🔄 ИЗМЕНЕНИЕ: {event_name} ({outcome}): "
                    f"{prev_odd:.3f} → {curr_odd:.3f} ({change_pct:+.2f}%)"
                )

            sport_name = current_data.get("sport", prev_data.get("sport", "Unknown"))

            if abs(change_pct) >= abs(DETECTION_THRESHOLD):
                anomaly_count += 1
                logger.warning(
                    f"⏳ АНОМАЛИЯ ОБНАРУЖЕНА: {event_name} ({outcome}) "
                    f"{change_pct:+.2f}% (порог: >{DETECTION_THRESHOLD}%)"
                )

                anomaly = {
                    "event_name": event_name,
                    "sport": sport_name,
                    "anomaly_type": "ODDS_DROP"
                    if change_pct < 0
                    else "ODDS_RISE",
                    "before_value": f"{prev_odd:.3f}",
                    "after_value": f"{curr_odd:.3f}",
                    "diff_pct": round(change_pct, 2),
                    "status": "detected",
                    "comment": f"{outcome}: {prev_odd:.3f} → {curr_odd:.3f} ({change_pct:+.2f}%)",
                    "detected_at": datetime.now().isoformat(timespec="seconds"),
                }
                anomalies.append(anomaly)

    logger.info(
        f"📊 ИТОГО: {change_count} изменений (>0.5%), "
        f"{anomaly_count} аномалий (>{DETECTION_THRESHOLD}%)"
    )

    # Обновляем состояние
    for event_name, current_data in current_events.items():
        global_detector_state[event_name] = current_data.copy()

    save_detector_state(global_detector_state)

    if anomalies:
        logger.warning(f"\n🚨 *** ОБНАРУЖЕНО {len(anomalies)} АНОМАЛИЙ! ***")
        for i, anom in enumerate(anomalies, 1):
            logger.warning(
                f"  {i}. {anom['event_name']} - {anom['anomaly_type']} "
                f"({anom['diff_pct']}%)\n"
            )
    else:
        logger.info("✅ Аномалий не обнаружено")

    return anomalies


async def parse_22bet():
    async with async_playwright() as p:
        logger.info("🚀 Парсер 22BET запущен")

        browser = await p.chromium.launch(
            headless=True,
            proxy=PROXY_CONFIG,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )

        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0 Safari/537.36"
            ),
        )

        page = await context.new_page()

        MIRRORS = ["https://22betluck.com", "https://22bet.com"]
        working_mirror = None

        for mirror in MIRRORS:
            try:
                logger.info(f"🌐 Пробуем: {mirror}")
                response = await page.goto(
                    mirror, wait_until="domcontentloaded", timeout=15000
                )
                if response and response.status < 400:
                    logger.info(f"✅ Работает: {mirror}")
                    working_mirror = mirror
                    break
            except Exception:
                logger.warning(f"❌ Недоступно {mirror}")

        if not working_mirror:
            await browser.close()
            logger.error("❌ Все зеркала недоступны")
            return

        SPORTS = [{"name": "Football", "slug": "football"}]
        current_events = {}

        for sport in SPORTS:
            try:
                sport_url = f"{working_mirror}/line/{sport['slug']}/"
                logger.info(f"📌 Загружаем: {sport_url}")

                await page.goto(
                    sport_url, wait_until="domcontentloaded", timeout=60000
                )
                await asyncio.sleep(3)

                await page.wait_for_selector(
                    ".c-events__item_col", timeout=10000
                )

                all_events = await page.query_selector_all(
                    ".c-events__item.c-events__item_col"
                )

                logger.info(
                    f"📊 Найдено событий на странице: {len(all_events)}"
                )

                conn = get_db_connection()
                cursor = conn.cursor()
                success_count = 0

                for idx, event in enumerate(all_events[:20], 1):
                    try:
                        teams = await event.query_selector_all(".c-events__team")
                        logger.info(f"[{idx}] TEAMS COUNT: {len(teams)}")

                        if len(teams) < 2:
                            logger.warning(
                                f"[{idx}] SKIP: недостаточно команд ({len(teams)})"
                            )
                            continue

                        home = (await teams[0].inner_text()).strip()
                        away = (await teams[1].inner_text()).strip()
                        event_name = f"{home} vs {away}"

                        logger.info(f"[{idx}] EVENT: {event_name}")

                        if event_name in ("Home vs Away", "Team1 vs Team2"):
                            logger.warning(
                                f"[{idx}] SKIP: мусорное название"
                            )
                            continue

                        odds_elems = await event.query_selector_all(
                            ".c-bets__inner"
                        )

                        logger.info(
                            f"[{idx}] ODDS BLOCKS: {len(odds_elems)}"
                        )

                        odds_list = []
                        for o in odds_elems[:3]:
                            try:
                                txt = (await o.inner_text()).strip()
                                if txt:
                                    odds_list.append(float(txt))
                            except Exception:
                                pass

                        logger.info(
                            f"[{idx}] PARSED ODDS: {odds_list}"
                        )

                        if len(odds_list) < 2:
                            logger.warning(
                                f"[{idx}] SKIP: недостаточно коэффициентов "
                                f"({len(odds_list)})"
                            )
                            continue

                        while len(odds_list) < 3:
                            odds_list.append(1.0)

                        event_key = f"{event_name} | 1x2"
                        current_events[event_key] = {
                            "sport": sport["name"],
                            "status": "active",
                            "odds": {
                                "1": odds_list[0],
                                "X": odds_list[1],
                                "2": odds_list[2],
                            },
                        }

                        # 🔥 ИЗМЕНЕНО: INSERT вместо ON DUPLICATE KEY UPDATE
                        sql_1x2 = """
                        INSERT INTO odds_22bet (
                            event_name,
                            sport,
                            market_type,
                            market_key,
                            odd_1,
                            odd_x,
                            odd_2,
                            status
                        )
                        VALUES (%s, %s, '1x2', '1x2', %s, %s, %s, 'active')
                        """

                        cursor.execute(
                            sql_1x2,
                            (
                                event_name,
                                sport["name"],
                                float(odds_list[0]),
                                float(odds_list[1]),
                                float(odds_list[2]),
                            ),
                        )

                        success_count += 1
                        logger.info(
                            f"[{idx}] ✅ SAVED: {event_name} | "
                            f"{odds_list[0]:.2f} | {odds_list[1]:.2f} | {odds_list[2]:.2f}"
                        )

                    except Exception as e:
                        logger.error(f"[{idx}] ❌ ОШИБКА: {str(e)}")

                conn.commit()
                cursor.close()
                conn.close()

                logger.info(
                    f"✅ {sport['name']}: {success_count} событий сохранено\n"
                )

            except Exception as e:
                logger.error(f"❌ {sport['name']}: {e}")
                import traceback
                logger.error(traceback.format_exc())

        await browser.close()
        logger.info("🌐 Браузер закрыт")

        # 🔥 ДЕТЕКТОР
        logger.info(
            f"🔎 ВЫЗЫВАЮ ДЕТЕКТОР АНОМАЛИЙ с {len(current_events)} событиями..."
        )

        anomalies = detect_anomalies(current_events)

        logger.info(
            f"✅ Детектор завершил работу: {len(anomalies)} аномалий обнаружено"
        )

        if anomalies:
            logger.warning(f"💾 СОХРАНЯЮ {len(anomalies)} АНОМАЛИЙ В БД...")
            conn = get_db_connection()
            cursor = conn.cursor()

            for anom in anomalies:
                try:
                    sql = """
                    INSERT INTO anomalies_22bet (
                        event_name,
                        sport,
                        league,
                        anomaly_type,
                        before_value,
                        after_value,
                        diff_pct,
                        status,
                        comment
                    )
                    VALUES (%s, %s, 'Mixed', %s, %s, %s, %s, %s, %s)
                    """

                    cursor.execute(
                        sql,
                        (
                            anom["event_name"],
                            anom.get("sport", "Unknown"),
                            anom["anomaly_type"],
                            str(anom["before_value"])[:50],
                            str(anom["after_value"])[:50],
                            anom["diff_pct"],
                            anom["status"],
                            str(anom["comment"])[:255],
                        ),
                    )

                    logger.warning(
                        f"  ✅ {anom['event_name']} {anom['anomaly_type']} "
                        f"({anom['diff_pct']}%)"
                    )

                except Exception as e:
                    logger.error(f"  ❌ Ошибка записи: {e}")

            conn.commit()
            cursor.close()
            conn.close()

            # 📱 TELEGRAM УВЕДОМЛЕНИЯ
            if telegram_notifier and anomalies:
                critical_anomalies = [
                    a
                    for a in anomalies
                    if abs(a["diff_pct"]) >= TELEGRAM_MIN_ALERT_THRESHOLD
                ]

                if critical_anomalies:
                    logger.info(
                        f"📱 Отправляю {len(critical_anomalies)} критических аномалий "
                        f"в Telegram (@Oddly1xbet_bot)..."
                    )

                    if len(critical_anomalies) > 3:
                        success = telegram_notifier.send_batch_alert(
                            critical_anomalies
                        )
                        if success:
                            logger.info(
                                f"✅ Групповое уведомление отправлено "
                                f"({len(critical_anomalies)} аномалий)"
                            )
                        else:
                            logger.error(
                                "❌ Не удалось отправить групповое уведомление"
                            )
                    else:
                        sent_count = 0
                        for anom in critical_anomalies:
                            if telegram_notifier.send_anomaly_alert(anom):
                                sent_count += 1

                        logger.info(
                            f"✅ Отправлено {sent_count}/"
                            f"{len(critical_anomalies)} уведомлений"
                        )
                else:
                    logger.info(
                        f"ℹ️ Нет критических аномалий для Telegram "
                        f"(порог: ≥{TELEGRAM_MIN_ALERT_THRESHOLD}%)"
                    )


async def main():
    while True:
        try:
            await parse_22bet()
        except Exception as e:
            logger.error(f"💥 Критическая ошибка: {e}")
            import traceback
            logger.error(traceback.format_exc())

        logger.info(f"⏱️ Пауза {UPDATE_INTERVAL} сек...\n")
        await asyncio.sleep(UPDATE_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
