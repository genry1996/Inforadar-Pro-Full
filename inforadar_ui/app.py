from flask import Flask, render_template, jsonify
import pymysql
import os

app = Flask(__name__)

# Параметры подключения к MySQL (контейнер mysql_inforadar)
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


@app.route("/")
def index():
    """Главная страница: проверка соединения с базой"""
    conn = get_connection()
    if conn is None:
        return "<b>Ошибка подключения к MySQL:</b> не удалось установить соединение."
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT NOW() as now;")
            result = cursor.fetchone()
        conn.close()
        return f"<h3>✅ Подключение к MySQL успешно!</h3><p>Текущее время: {result['now']}</p>"
    except Exception as e:
        return f"<b>Ошибка подключения к MySQL:</b> {e}"


@app.route("/api/test")
def api_test():
    """Тестовый эндпоинт для проверки API"""
    return jsonify({"status": "ok", "message": "API Inforadar работает"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
