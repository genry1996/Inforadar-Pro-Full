import os
from flask import Flask
import pymysql

app = Flask(__name__)

DB_HOST = os.getenv("DB_HOST", "mysql_inforadar")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_NAME = os.getenv("DB_NAME", "inforadar")
DB_USER = os.getenv("DB_USER", "radar")
DB_PASSWORD = os.getenv("DB_PASSWORD", "ryban8991!")

@app.route("/")
def index():
    try:
        conn = pymysql.connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME,
            cursorclass=pymysql.cursors.DictCursor,
            connect_timeout=5,
        )
        with conn.cursor() as cur:
            cur.execute("SELECT NOW() AS now;")
            row = cur.fetchone()
        conn.close()
        return f"✅ UI работает. Подключение к MySQL успешно. NOW(): {row['now']}"
    except Exception as e:
        return f"<b>Ошибка подключения к MySQL:</b> {e}", 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
