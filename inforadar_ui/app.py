from flask import Flask, render_template, jsonify
import pymysql

app = Flask(__name__)

# === Настройки подключения к MySQL ===
DB_HOST = "mysql_inforadar"
DB_PORT = 3306
DB_USER = "radar"
DB_PASSWORD = "ryban8991!"
DB_NAME = "inforadar"


def get_connection():
    """Создаёт подключение к базе данных MySQL"""
    try:
        conn = pymysql.connect(
            host=DB_HOST,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME,
            port=DB_PORT,
            cursorclass=pymysql.cursors.DictCursor,
            connect_timeout=5
        )
        return conn
    except Exception as e:
        print(f"❌ Ошибка подключения к MySQL: {e}")
        return None


# === Главная страница ===
@app.route("/")
def index():
    """Показывает тестовую страницу Soccer"""
    conn = get_connection()
    if conn is None:
        return "<b>Ошибка подключения к MySQL</b>"
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM matches ORDER BY id DESC LIMIT 50;")
            matches = cursor.fetchall()
        conn.close()
        return render_template("index.html", matches=matches)
    except Exception as e:
        return f"<b>Ошибка при получении данных:</b> {e}"


# === API ===
@app.route("/api/matches")
def api_matches():
    """API для получения матчей"""
    conn = get_connection()
    if conn is None:
        return jsonify({"error": "Не удалось подключиться к MySQL"}), 500
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM matches ORDER BY start_time DESC;")
            matches = cursor.fetchall()
        conn.close()
        return jsonify(matches)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# === LIVE ===
@app.route("/live")
def live_page():
    """Страница с LIVE-матчами"""
    return render_template("live.html")


# === MATCHES (единая страница с вкладками) ===
@app.route("/matches")
def matches_page():
    """Главная страница со вкладками (Live, Prematch, Results)"""
    return render_template("matches_tabs.html")


# === ESPORTS ===
@app.route("/esports")
def esports_page():
    """Страница с матчами киберспорта"""
    return render_template("esports.html")


# === PREMATCH ===
@app.route("/prematch")
def prematch_page():
    """Страница предстоящих матчей"""
    conn = get_connection()
    if conn is None:
        return "<b>Ошибка подключения к MySQL</b>"

    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM matches WHERE start_time > NOW() ORDER BY start_time ASC;")
            matches = cursor.fetchall()
        conn.close()
        return render_template("prematch.html", matches=matches)
    except Exception as e:
        return f"<b>Ошибка при получении данных:</b> {e}"


# === Проверка API ===
@app.route("/api/test")
def api_test():
    return jsonify({"status": "ok", "message": "API OddlyOdds работает"})


# === Точка входа ===
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
