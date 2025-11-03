from flask import Flask, render_template
import pymysql
import os

app = Flask(__name__)

def get_db_connection():
    return pymysql.connect(
        host='mysql_inforadar',
        user='root',
        password='ryban8991!',  # ✅ исправлен пароль
        database='inforadar',
        cursorclass=pymysql.cursors.DictCursor
    )

@app.route('/')
def matches():
    try:
        connection = get_db_connection()
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM matches")
            matches = cursor.fetchall()
        connection.close()
        return render_template('matches.html', matches=matches)
    except Exception as e:
        return f"<h3>Ошибка подключения к MySQL:<
