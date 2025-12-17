from flask import Flask, render_template_string, jsonify, request
import mysql.connector
import os
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

def get_db_connection():
    return mysql.connector.connect(
        host=os.getenv("MYSQL_HOST", "localhost"),
        user=os.getenv("MYSQL_USER", "root"),
        password=os.getenv("MYSQL_PASSWORD", "ryban8991!"),
        database=os.getenv("MYSQL_DB", "inforadar")
    )

@app.route('/')
def index():
    return jsonify({
        "status": "running",
        "endpoints": [
            "/anomalies_22bet",
            "/api/odds_22bet",
            "/api/anomalies?min_change=2.0"  # Новый эндпоинт с фильтром
        ]
    })

@app.route('/anomalies_22bet')
def anomalies_22bet():
    # Получаем параметр фильтра из URL (по умолчанию 0.3%)
    min_change = request.args.get('min_change', 0.3, type=float)

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Получаем последние коэффициенты
    cursor.execute("""
        SELECT event_name, sport, odd_1, odd_x, odd_2, updated_at 
        FROM odds_22bet 
        ORDER BY updated_at DESC 
        LIMIT 50
    """)
    odds = cursor.fetchall()

    # Получаем аномалии с фильтром
    cursor.execute("""
        SELECT event_name, sport, anomaly_type, before_value, after_value, 
               diff_pct, status, comment, detected_at 
        FROM anomalies_22bet 
        WHERE ABS(diff_pct) >= %s
        ORDER BY detected_at DESC 
        LIMIT 50
    """, (min_change,))
    anomalies = cursor.fetchall()

    cursor.close()
    conn.close()

    html = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>22Bet Anomalies Monitor</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { 
            font-family: 'Segoe UI', Tahoma, sans-serif; 
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            padding: 20px;
        }
        .container { max-width: 1400px; margin: 0 auto; }
        h1 { 
            color: white; 
            text-align: center; 
            margin-bottom: 30px;
            font-size: 2.5em;
            text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
        }
        .stats { 
            display: grid; 
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        .stat-card {
            background: white;
            padding: 20px;
            border-radius: 15px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.2);
            text-align: center;
        }
        .stat-card h3 { color: #667eea; margin-bottom: 10px; }
        .stat-card .number { font-size: 2.5em; color: #764ba2; font-weight: bold; }

        .filter-panel {
            background: white;
            padding: 20px;
            border-radius: 15px;
            margin-bottom: 20px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.2);
        }
        .filter-panel label { font-weight: bold; margin-right: 10px; }
        .filter-panel select { 
            padding: 10px; 
            border-radius: 8px; 
            border: 2px solid #667eea;
            font-size: 16px;
        }

        .section {
            background: white;
            padding: 25px;
            border-radius: 15px;
            margin-bottom: 30px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.2);
        }
        .section h2 { 
            color: #667eea; 
            margin-bottom: 20px;
            font-size: 1.8em;
        }
        table { 
            width: 100%; 
            border-collapse: collapse;
            background: white;
        }
        th { 
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white; 
            padding: 15px;
            text-align: left;
            font-weight: 600;
        }
        td { 
            padding: 12px 15px; 
            border-bottom: 1px solid #eee;
        }
        tr:hover { background: #f8f9ff; }

        .odds-drop { color: #e74c3c; font-weight: bold; }
        .odds-rise { color: #27ae60; font-weight: bold; }
        .critical { background: #ffe6e6 !important; }
        .important { background: #fff4e6 !important; }

        .auto-update { 
            text-align: center; 
            color: white; 
            margin-top: 20px;
            font-size: 14px;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🎯 22Bet Anomalies Monitor</h1>

        <div class="stats">
            <div class="stat-card">
                <h3>📊 Коэффициентов</h3>
                <div class="number">{{ odds|length }}</div>
            </div>
            <div class="stat-card">
                <h3>🚨 Аномалий</h3>
                <div class="number">{{ anomalies|length }}</div>
            </div>
            <div class="stat-card">
                <h3>🔍 Порог</h3>
                <div class="number">{{ "%.1f"|format(min_change) }}%</div>
            </div>
        </div>

        <div class="filter-panel">
            <label for="filter">Фильтр по изменению:</label>
            <select id="filter" onchange="location.href='?min_change=' + this.value">
                <option value="0.3" {% if min_change == 0.3 %}selected{% endif %}>Все (≥0.3%)</option>
                <option value="1.0" {% if min_change == 1.0 %}selected{% endif %}>Значительные (≥1%)</option>
                <option value="2.0" {% if min_change == 2.0 %}selected{% endif %}>Важные (≥2%)</option>
                <option value="5.0" {% if min_change == 5.0 %}selected{% endif %}>Критические (≥5%)</option>
            </select>
        </div>

        <div class="section">
            <h2>🚨 Аномалии</h2>
            <table>
                <thead>
                    <tr>
                        <th>Время</th>
                        <th>Событие</th>
                        <th>Спорт</th>
                        <th>Тип</th>
                        <th>Было → Стало</th>
                        <th>Изменение</th>
                        <th>Статус</th>
                        <th>Комментарий</th>
                    </tr>
                </thead>
                <tbody>
                    {% for a in anomalies %}
                    <tr class="{% if a.diff_pct|abs >= 5 %}critical{% elif a.diff_pct|abs >= 2 %}important{% endif %}">
                        <td>{{ a.detected_at }}</td>
                        <td>{{ a.event_name }}</td>
                        <td>{{ a.sport }}</td>
                        <td class="{% if 'DROP' in a.anomaly_type %}odds-drop{% else %}odds-rise{% endif %}">
                            {{ a.anomaly_type }}
                        </td>
                        <td>{{ a.before_value }} → {{ a.after_value }}</td>
                        <td class="{% if a.diff_pct < 0 %}odds-drop{% else %}odds-rise{% endif %}">
                            {{ "%.2f"|format(a.diff_pct) }}%
                        </td>
                        <td>{{ a.status }}</td>
                        <td>{{ a.comment }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>

        <div class="section">
            <h2>💰 Коэффициенты</h2>
            <table>
                <thead>
                    <tr>
                        <th>Обновлено</th>
                        <th>Событие</th>
                        <th>Спорт</th>
                        <th>1</th>
                        <th>X</th>
                        <th>2</th>
                    </tr>
                </thead>
                <tbody>
                    {% for o in odds %}
                    <tr>
                        <td>{{ o.updated_at }}</td>
                        <td>{{ o.event_name }}</td>
                        <td>{{ o.sport }}</td>
                        <td>{{ "%.2f"|format(o.odd_1) }}</td>
                        <td>{{ "%.2f"|format(o.odd_x) }}</td>
                        <td>{{ "%.2f"|format(o.odd_2) }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>

        <div class="auto-update">
            ⏱️ Автообновление каждые 30 секунд
        </div>
    </div>

    <script>
        setTimeout(function() {
            location.reload();
        }, 30000);
    </script>
</body>
</html>
    """

    return render_template_string(html, odds=odds, anomalies=anomalies, min_change=min_change)

@app.route('/api/odds_22bet')
def api_odds():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM odds_22bet ORDER BY updated_at DESC LIMIT 50")
    data = cursor.fetchall()
    cursor.close()
    conn.close()
    return jsonify(data)

@app.route('/api/anomalies')
def api_anomalies():
    """API эндпоинт для получения аномалий с фильтром"""
    min_change = request.args.get('min_change', 0.3, type=float)

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT * FROM anomalies_22bet 
        WHERE ABS(diff_pct) >= %s
        ORDER BY detected_at DESC 
        LIMIT 100
    """, (min_change,))
    data = cursor.fetchall()
    cursor.close()
    conn.close()
    return jsonify(data)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
