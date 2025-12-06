from flask import Flask, render_template, jsonify, request
import pymysql
from datetime import datetime
from collections import defaultdict

app = Flask(__name__)

# ====== DB SETTINGS ======
DB_HOST = "mysql_inforadar"
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
    filter_type = request.args.get("type", "all")

    conn = get_connection()
    anomalies = []

    if conn:
        with conn.cursor() as cursor:
            # Ничего не предполагаем про схему anomalies:
            # просто берём a.* и добавляем поля из matches
            query = """
                SELECT
                    a.*,
                    m.sport,
                    m.league,
                    m.home_team,
                    m.away_team
                FROM anomalies a
                LEFT JOIN matches m ON a.match_id = m.id
            """

            if filter_type == "live":
                query += " WHERE a.anomaly_type LIKE '%LIVE%'"
            elif filter_type == "prematch":
                query += " WHERE a.anomaly_type NOT LIKE '%LIVE%'"

            query += " ORDER BY a.occurred_at DESC LIMIT 200"

            cursor.execute(query)
            anomalies = cursor.fetchall()

    return render_template(
        "anomalies.html",
        anomalies=anomalies,
        filter_type=filter_type,
        total_pages=1,
        page=1,
    )


# алиас, чтобы /anomaly тоже открывал страницу аномалий
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


# ====== RUN ======
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
