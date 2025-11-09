from flask import Flask, render_template, jsonify
import pymysql
import os

app = Flask(__name__)

# --- Настройки базы данных ---
DB_HOST = "mysql_inforadar"
DB_PORT = 3306
DB_USER = "radar"
DB_PASSWORD = "ryban8991!"
DB_NAME = "inforadar"

def get_connection():
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
        print(f"Ошибка подключения к MySQL: {e}")
        return None

# --- Маршруты ---

@app.route("/")
def index():
    """Главная страница (OddlyOdds Dashboard)"""
    return render_template("index.html")

@app.route("/api/matches")
def get_matches():
    """API для вывода всех матчей"""
    conn = get_connection()
    if conn is None:
        return jsonify({"error": "Ошибка подключения к базе"}), 500

    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT id, sport, league, home_team, away_team,
                       score_home, score_away, start_time, created_at
                FROM matches ORDER BY start_time DESC
            """)
            data = cursor.fetchall()
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
