from flask import Flask, render_template, jsonify, request
import pymysql
from datetime import datetime

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
    except:
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
        return f"{int(seconds//60)} мин назад"
    if seconds < 86400:
        return f"{int(seconds//3600)} ч назад"
    if seconds < 604800:
        return f"{int(seconds//86400)} дн назад"

    return value.strftime("%Y-%m-%d %H:%M")


# ===========================================================
#                   АНОМАЛИИ  (ОДИН ЕДИНСТВЕННЫЙ РОУТ!)
# ===========================================================
@app.route("/anomalies")
def anomalies_page():
    filter_type = request.args.get("type", "all")

    conn = get_connection()
    anomalies = []

    if conn:
        with conn.cursor() as cursor:

            query = """
                SELECT
                    a.id,
                    a.match_id,
                    a.anomaly_type,
                    a.before_odd,
                    a.after_odd,
                    a.before_limit,
                    a.after_limit,
                    a.diff_pct,
                    a.occurred_at,
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
        page=1
    )

# ====== MAIN PAGE ======
@app.route("/")
def index():
    return render_template("index.html")


# ====== RUN ======
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
