from flask import Flask, render_template, jsonify, request
import pymysql
from datetime import datetime
from collections import defaultdict

app = Flask(__name__)

# ====== DB SETTINGS ======
DB_HOST = "mysql_inforadar"  # внутри Docker-сети
DB_PORT = 3306
DB_USER = "root"
DB_PASSWORD = "ryban8991!"
DB_NAME = "inforadar"


def get_connection():
    try:
        return pymysql.connect(
            host=DB_HOST,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME,
            port=DB_PORT,
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=True,
        )
    except Exception:
        return None


# ====== JINJA FILTER ======
@app.template_filter("timeago")
def timeago(value):
    if not value:
        return ""
    if isinstance(value, str):
        # на всякий случай — если строка
        try:
            value = datetime.fromisoformat(value)
        except Exception:
            return value

    now = datetime.utcnow()
    diff = now - value
    seconds = diff.total_seconds()

    if seconds < 60:
        return "только что"
    if seconds < 3600:
        return f"{int(seconds // 60)} мин назад"
    if seconds < 86400:
        return f"{int(seconds // 3600)} ч назад"
    if seconds < 604800:
        return f"{int(seconds // 86400)} дн назад"

    return value.strftime("%Y-%m-%d %H:%M")


# ===========================================================
#                   АНОМАЛИИ
# ===========================================================
@app.route("/anomalies")
def anomalies_page():
    """
    Страница аномалий:
    - тянем последние 200 записей из anomalies (+матч, если есть)
    - форматируем коэффициенты и проценты
    - фильтр по type: all / spread / live / prematch
    """
    filter_type = request.args.get("type", "all")

    conn = get_connection()
    if not conn:
        return "Ошибка подключения к MySQL"

    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    a.id,
                    a.match_id,
                    a.anomaly_type,
                    a.before_value,
                    a.after_value,
                    a.diff_pct,
                    a.created_at,
                    a.comment,
                    m.sport,
                    m.league,
                    m.home_team,
                    m.away_team
                FROM anomalies a
                LEFT JOIN matches m ON a.match_id = m.id
                ORDER BY a.created_at DESC, a.id DESC
                LIMIT 200
                """
            )
            rows = cursor.fetchall()
    finally:
        conn.close()

    def fmt_odd(val):
        """Приводим Decimal/float/строку к строке с 2–3 знаками без лишних нулей."""
        if val is None:
            return None
        try:
            f = float(val)
        except (TypeError, ValueError):
            return str(val)
        s = f"{f:.3f}".rstrip("0").rstrip(".")
        return s

    anomalies = []
    for row in rows:
        # коэффициенты
        row["before_value"] = fmt_odd(row.get("before_value"))
        row["after_value"] = fmt_odd(row.get("after_value"))

        # процент
        diff_val = row.get("diff_pct")
        if diff_val is not None:
            try:
                row["diff_pct"] = float(diff_val)
            except (TypeError, ValueError):
                row["diff_pct"] = None

        # created_at оставляем datetime — фильтр timeago сам форматирует
        anomalies.append(row)

    # ===== Фильтр по типу =====
    filtered = anomalies
    if filter_type == "spread":
        filtered = [a for a in anomalies if (a.get("anomaly_type") == "ODDS_SPREAD")]
    elif filter_type == "live":
        filtered = [
            a for a in anomalies if "LIVE" in (a.get("anomaly_type") or "")
        ]
    elif filter_type == "prematch":
        filtered = [
            a for a in anomalies if "LIVE" not in (a.get("anomaly_type") or "")
        ]

    return render_template(
        "anomalies.html",
        anomalies=filtered,
        filter_type=filter_type,   # для подсветки таба
        current_type=filter_type,  # если в шаблоне используется другое имя
        total_pages=1,
        page=1,
    )


# alias /anomaly -> /anomalies (на всякий случай, если где-то старый линк)
@app.route("/anomaly")
def anomalies_single_alias():
    return anomalies_page()


# ===========================================================
#          THE ODDS API — EPL (soccer_epl)
# ===========================================================
@app.route("/oddsapi/epl")
def oddsapi_epl():
    conn = get_connection()
    if not conn:
        return "Ошибка подключения к MySQL"

    try:
        with conn.cursor() as cursor:
            # 1) События EPL
            cursor.execute(
                """
                SELECT
                    e.event_id,
                    e.sport_key,
                    e.sport_title,
                    e.commence_time,
                    e.home_team,
                    e.away_team,
                    e.completed
                FROM oddsapi_events e
                WHERE e.sport_key = 'soccer_epl'
                ORDER BY e.commence_time ASC
                """
            )
            rows_events = cursor.fetchall()

            if not rows_events:
                return render_template("oddsapi_epl.html", events=[])

            event_ids = [row["event_id"] for row in rows_events]

            # 2) H2H-коэффы по этим событиям
            placeholders = ", ".join(["%s"] * len(event_ids))
            sql_odds = f"""
                SELECT
                    o.event_id,
                    o.bookmaker_title,
                    o.market_key,
                    o.outcome_name,
                    o.outcome_price,
                    o.last_update
                FROM oddsapi_odds o
                WHERE o.event_id IN ({placeholders})
                  AND o.market_key = 'h2h'
                ORDER BY o.event_id, o.bookmaker_title, o.outcome_name
            """
            cursor.execute(sql_odds, event_ids)
            rows_odds = cursor.fetchall()

    except Exception as e:
        print("❌ Ошибка в /oddsapi/epl:", e)
        return "Ошибка при получении данных The Odds API"
    finally:
        if conn:
            conn.close()

    # Собираем удобную структуру для шаблона
    odds_by_event = defaultdict(list)
    for row in rows_odds:
        odds_by_event[row["event_id"]].append(row)

    events = []
    for ev in rows_events:
        ev_id = ev["event_id"]
        commence = ev["commence_time"]
        if isinstance(commence, datetime):
            commence_str = commence.strftime("%Y-%m-%d %H:%M")
        else:
            commence_str = str(commence)

        events.append(
            {
                "event_id": ev_id,
                "sport_key": ev["sport_key"],
                "sport_title": ev.get("sport_title"),
                "commence_time": commence_str,
                "home_team": ev["home_team"],
                "away_team": ev["away_team"],
                "completed": ev["completed"],
                "odds": odds_by_event.get(ev_id, []),
            }
        )

    return render_template("oddsapi_epl.html", events=events)


# ====== MAIN PAGE ======
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/metrics")
def metrics_stub():
    # Заглушка для Prometheus, чтобы не было 404
    return "ok\n", 200, {"Content-Type": "text/plain; charset=utf-8"}


# ====== RUN LOCAL (в докере всё равно не используется) ======
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
