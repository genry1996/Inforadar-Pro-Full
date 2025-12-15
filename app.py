from flask import Flask, render_template_string, jsonify
import mysql.connector
import os

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
            "/api/odds_22bet"
        ]
    })

@app.route('/anomalies_22bet')
def anomalies_22bet():
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
    
    # Получаем аномалии
    cursor.execute("""
        SELECT event_name, sport, anomaly_type, before_value, after_value, 
               diff_pct, status, comment, detected_at
        FROM anomalies_22bet
        ORDER BY detected_at DESC
        LIMIT 50
    """)
    anomalies = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>22Bet Anomalies Monitor</title>
        <meta charset="UTF-8">
        <style>
            body { font-family: Arial; margin: 20px; background: #f5f5f5; }
            h1 { color: #333; }
            .stats { background: white; padding: 15px; border-radius: 5px; margin: 10px 0; }
            table { width: 100%; border-collapse: collapse; background: white; margin: 20px 0; }
            th { background: #2196F3; color: white; padding: 12px; text-align: left; }
            td { padding: 10px; border-bottom: 1px solid #ddd; }
            tr:hover { background: #f5f5f5; }
            .anomaly { background: #fff3cd; }
            .status-badge { padding: 3px 8px; border-radius: 3px; font-size: 12px; }
            .status-active { background: #28a745; color: white; }
            .status-confirmed { background: #dc3545; color: white; }
            .refresh { background: #2196F3; color: white; padding: 10px 20px; border: none; border-radius: 5px; cursor: pointer; }
        </style>
        <script>
            function autoRefresh() {
                setTimeout(() => location.reload(), 30000);
            }
            window.onload = autoRefresh;
        </script>
    </head>
    <body>
        <h1>🎯 22Bet Anomalies Monitor</h1>
        
        <div class="stats">
            <h3>📊 Статистика</h3>
            <p><strong>Коэффициентов:</strong> {{ odds|length }}</p>
            <p><strong>Аномалий:</strong> {{ anomalies|length }}</p>
        </div>
        
        <h2>🚨 Аномалии</h2>
        <table>
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
            {% for a in anomalies %}
            <tr class="anomaly">
                <td>{{ a.detected_at }}</td>
                <td>{{ a.event_name }}</td>
                <td>{{ a.sport }}</td>
                <td>{{ a.anomaly_type }}</td>
                <td>{{ a.before_value }} → {{ a.after_value }}</td>
                <td>{{ a.diff_pct }}%</td>
                <td><span class="status-badge status-{{ a.status }}">{{ a.status }}</span></td>
                <td>{{ a.comment }}</td>
            </tr>
            {% endfor %}
        </table>
        
        <h2>💰 Коэффициенты</h2>
        <table>
            <tr>
                <th>Обновлено</th>
                <th>Событие</th>
                <th>Спорт</th>
                <th>1</th>
                <th>X</th>
                <th>2</th>
            </tr>
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
        </table>
        
        <button class="refresh" onclick="location.reload()">🔄 Обновить</button>
        <p style="color: #666;">Автообновление каждые 30 секунд</p>
    </body>
    </html>
    """
    
    return render_template_string(html, odds=odds, anomalies=anomalies)

@app.route('/api/odds_22bet')
def api_odds():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM odds_22bet ORDER BY updated_at DESC LIMIT 50")
    data = cursor.fetchall()
    cursor.close()
    conn.close()
    return jsonify(data)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
