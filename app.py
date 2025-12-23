# -*- coding: utf-8 -*-
"""
Inforadar Pro - Main Flask Application
D:\Inforadar_Pro\app.py
"""

from flask import Flask, render_template_string, jsonify, request
import mysql.connector
import os
import json
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

# ====== CONFIGURATION ======
CONFIG_DIR = r"D:\Inforadar_Pro\config"
THRESHOLDS_FILE = os.path.join(CONFIG_DIR, "thresholds.json")

# Создаем директорию config если её нет
os.makedirs(CONFIG_DIR, exist_ok=True)

# ====== DEFAULT SETTINGS ======
DEFAULT_SETTINGS = {
    # Резкое падение - высокие кэфы (10-5)
    "enable_sharp_drop": True,
    "high_odd_from": 10.0,
    "high_odd_to": 5.0,
    "sharp_drop_high_min": 20,
    "sharp_drop_high_max": 35,
    
    # Резкое падение - средние кэфы (5-2)
    "mid_odd_from": 5.0,
    "mid_odd_to": 2.0,
    "sharp_drop_mid_min": 12,
    "sharp_drop_mid_max": 25,
    
    # Резкое падение - низкие кэфы (2-1.1)
    "low_odd_from": 2.0,
    "low_odd_to": 1.1,
    "sharp_drop_low_min": 10,
    "sharp_drop_low_max": 20,
    
    # Арбитраж
    "enable_value_bet": True,
    "value_bet_min": 3,
    "value_bet_max": 15,
    "arbitrage_corridor_percent": 5,
    "fork_lifetime_minutes": 5,
    "bookmakers": ["fonbet", "22bet"],
    
    # Большие заливы
    "enable_unbalanced": True,
    "money_min": 5000,
    "flow_bet": 70,
    
    # После 80
    "enable_after_80": True,
    "after_80_minute": 80
}

def get_db_connection():
    """MySQL connection"""
    return mysql.connector.connect(
        host=os.getenv("MYSQL_HOST", "localhost"),
        user=os.getenv("MYSQL_USER", "root"),
        password=os.getenv("MYSQL_PASSWORD", "ryban8991!"),
        database=os.getenv("MYSQL_DB", "inforadar")
    )

def load_settings():
    """Загрузка настроек из файла"""
    if os.path.exists(THRESHOLDS_FILE):
        try:
            with open(THRESHOLDS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"❌ Ошибка чтения настроек: {e}")
            return DEFAULT_SETTINGS
    return DEFAULT_SETTINGS

def save_settings(settings):
    """Сохранение настроек в файл"""
    try:
        with open(THRESHOLDS_FILE, 'w', encoding='utf-8') as f:
            json.dump(settings, f, indent=4, ensure_ascii=False)
        print(f"✅ Settings saved to {THRESHOLDS_FILE}")
        return True
    except Exception as e:
        print(f"❌ Ошибка сохранения настроек: {e}")
        return False

# ===========================================================
# MAIN ROUTES
# ===========================================================

@app.route('/')
def index():
    """Главная страница"""
    return jsonify({
        "status": "running",
        "version": "2.0",
        "endpoints": [
            "/anomalies_22bet",
            "/api/betwatch/settings",
            "/api/betwatch/save-settings",
            "/api/betwatch/signals",
            "/api/betwatch/stats",
            "/api/betwatch/fork-lifetime"
        ]
    })

# ===========================================================
# BETWATCH API ROUTES
# ===========================================================

@app.route('/api/betwatch/settings', methods=['GET'])
def api_betwatch_get_settings():
    """API: Получить текущие настройки Betwatch"""
    try:
        settings = load_settings()
        return jsonify({
            "success": True,
            "settings": settings
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/api/betwatch/save-settings', methods=['POST'])
def api_betwatch_save_settings():
    """API: Сохранить настройки Betwatch"""
    try:
        settings = request.json
        
        # Валидация
        validated_settings = {
            # Резкое падение - высокие кэфы
            "enable_sharp_drop": settings.get('enable_sharp_drop', True),
            "high_odd_from": float(settings.get('high_odd_from', 10.0)),
            "high_odd_to": float(settings.get('high_odd_to', 5.0)),
            "sharp_drop_high_min": float(settings.get('sharp_drop_high_min', 20)),
            "sharp_drop_high_max": float(settings.get('sharp_drop_high_max', 35)),
            
            # Резкое падение - средние кэфы
            "mid_odd_from": float(settings.get('mid_odd_from', 5.0)),
            "mid_odd_to": float(settings.get('mid_odd_to', 2.0)),
            "sharp_drop_mid_min": float(settings.get('sharp_drop_mid_min', 12)),
            "sharp_drop_mid_max": float(settings.get('sharp_drop_mid_max', 25)),
            
            # Резкое падение - низкие кэфы
            "low_odd_from": float(settings.get('low_odd_from', 2.0)),
            "low_odd_to": float(settings.get('low_odd_to', 1.1)),
            "sharp_drop_low_min": float(settings.get('sharp_drop_low_min', 10)),
            "sharp_drop_low_max": float(settings.get('sharp_drop_low_max', 20)),
            
            # Арбитраж
            "enable_value_bet": settings.get('enable_value_bet', True),
            "value_bet_min": float(settings.get('value_bet_min', 3)),
            "value_bet_max": float(settings.get('value_bet_max', 15)),
            "arbitrage_corridor_percent": float(settings.get('arbitrage_corridor_percent', 5)),
            "fork_lifetime_minutes": int(settings.get('fork_lifetime_minutes', 5)),
            "bookmakers": settings.get('bookmakers', ["fonbet", "22bet"]),
            
            # Большие заливы
            "enable_unbalanced": settings.get('enable_unbalanced', True),
            "money_min": float(settings.get('money_min', 5000)),
            "flow_bet": float(settings.get('flow_bet', 70)),
            
            # После 80
            "enable_after_80": settings.get('enable_after_80', True),
            "after_80_minute": int(settings.get('after_80_minute', 80))
        }
        
        if save_settings(validated_settings):
            return jsonify({
                "success": True,
                "message": "✅ Настройки сохранены! Перезапустите betwatch_advanced.py",
                "file": THRESHOLDS_FILE
            })
        else:
            return jsonify({
                "success": False,
                "message": "Ошибка сохранения настроек"
            }), 500
    
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/api/betwatch/signals', methods=['GET'])
def api_betwatch_signals():
    """API: Получить сигналы Betwatch из БД"""
    try:
        signal_type = request.args.get("type", "all")
        hours = int(request.args.get("hours", 24))
        limit = int(request.args.get("limit", 100))
        
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        query = """
            SELECT 
                id, signal_type, event_id, event_name, league, sport,
                market_type, betfair_odd, bookmaker_odd, bookmaker_name,
                money_volume, total_market_volume, flow_percent,
                old_odd, new_odd, odd_drop_percent,
                is_live, match_time, detected_at
            FROM betwatch_signals
            WHERE detected_at >= NOW() - INTERVAL %s HOUR
        """
        params = [hours]
        
        if signal_type != "all":
            query += " AND signal_type = %s"
            params.append(signal_type)
        
        query += " ORDER BY detected_at DESC LIMIT %s"
        params.append(limit)
        
        cursor.execute(query, params)
        signals = cursor.fetchall()
        
        # Конвертируем datetime
        for signal in signals:
            if signal.get("detected_at"):
                signal["detected_at"] = signal["detected_at"].strftime("%Y-%m-%d %H:%M:%S")
        
        cursor.close()
        conn.close()
        
        return jsonify({
            "success": True,
            "count": len(signals),
            "signals": signals
        })
    
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/api/betwatch/stats', methods=['GET'])
def api_betwatch_stats():
    """API: Статистика сигналов Betwatch"""
    try:
        hours = int(request.args.get("hours", 24))
        
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Общее количество
        cursor.execute("""
            SELECT COUNT(*) as total
            FROM betwatch_signals
            WHERE detected_at >= NOW() - INTERVAL %s HOUR
        """, (hours,))
        total = cursor.fetchone()["total"]
        
        # По типам
        cursor.execute("""
            SELECT signal_type, COUNT(*) as count
            FROM betwatch_signals
            WHERE detected_at >= NOW() - INTERVAL %s HOUR
            GROUP BY signal_type
        """, (hours,))
        by_type = cursor.fetchall()
        
        cursor.close()
        conn.close()
        
        return jsonify({
            "success": True,
            "total": total,
            "by_type": by_type
        })
    
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/api/betwatch/fork-lifetime', methods=['POST'])
def api_betwatch_fork_lifetime():
    """API: Проверка времени жизни арбитражной вилки"""
    try:
        data = request.json
        event_id = data.get('event_id')
        market_type = data.get('market_type')
        
        if not event_id or not market_type:
            return jsonify({
                'success': False,
                'message': 'Не указаны event_id или market_type'
            }), 400
        
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        cursor.execute("""
            SELECT 
                detected_at, betfair_odd, bookmaker_odd, bookmaker_name,
                ABS((bookmaker_odd - betfair_odd) / betfair_odd * 100) as profit_percent
            FROM betwatch_signals
            WHERE event_id = %s 
              AND market_type = %s 
              AND signal_type LIKE '%value_bet%'
            ORDER BY detected_at ASC
        """, (event_id, market_type))
        
        fork_history = cursor.fetchall()
        
        cursor.close()
        conn.close()
        
        if not fork_history:
            return jsonify({
                'success': False,
                'message': 'Вилка не найдена'
            }), 404
        
        # Рассчитываем время жизни
        first_detection = fork_history[0]['detected_at']
        last_detection = fork_history[-1]['detected_at']
        lifetime_seconds = (last_detection - first_detection).total_seconds()
        lifetime_minutes = round(lifetime_seconds / 60, 2)
        
        # Конвертируем datetime
        for record in fork_history:
            if 'detected_at' in record and record['detected_at']:
                record['detected_at'] = record['detected_at'].strftime("%Y-%m-%d %H:%M:%S")
        
        return jsonify({
            'success': True,
            'event_id': event_id,
            'market_type': market_type,
            'lifetime_minutes': lifetime_minutes,
            'detections_count': len(fork_history),
            'first_detected': fork_history[0]['detected_at'],
            'last_detected': fork_history[-1]['detected_at'],
            'max_profit_percent': max([r['profit_percent'] for r in fork_history]),
            'min_profit_percent': min([r['profit_percent'] for r in fork_history]),
            'history': fork_history
        })
    
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

# ===========================================================
# 22BET ROUTES (LEGACY)
# ===========================================================

@app.route('/anomalies_22bet')
def anomalies_22bet():
    """22bet аномалии (старый функционал)"""
    min_change = request.args.get('min_change', 0.3, type=float)
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Получаем аномалии
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
<html>
<head>
    <meta charset="UTF-8">
    <title>22bet Anomalies</title>
    <style>
        body { font-family: Arial; padding: 20px; }
        table { width: 100%; border-collapse: collapse; }
        th, td { padding: 10px; text-align: left; border: 1px solid #ddd; }
        th { background: #667eea; color: white; }
        tr:hover { background: #f5f5f5; }
    </style>
</head>
<body>
    <h1>📊 22bet Anomalies Monitor</h1>
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
            <tr>
                <td>{{ a.detected_at }}</td>
                <td>{{ a.event_name }}</td>
                <td>{{ a.sport }}</td>
                <td>{{ a.anomaly_type }}</td>
                <td>{{ "%.2f"|format(a.before_value) }} → {{ "%.2f"|format(a.after_value) }}</td>
                <td>{{ "%.2f"|format(a.diff_pct) }}%</td>
                <td>{{ a.status }}</td>
                <td>{{ a.comment }}</td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
</body>
</html>
"""
    
    return render_template_string(html, anomalies=anomalies)

# ===========================================================
# MAIN
# ===========================================================

if __name__ == '__main__':
    # Создаем дефолтный файл настроек если его нет
    if not os.path.exists(THRESHOLDS_FILE):
        save_settings(DEFAULT_SETTINGS)
        print(f"✅ Создан файл настроек: {THRESHOLDS_FILE}")
    
    print("=" * 70)
    print("🚀 Inforadar Pro - Main Flask Application")
    print("=" * 70)
    print(f"📁 Конфигурация: {THRESHOLDS_FILE}")
    print(f"🌐 Главная: http://localhost:5000")
    print(f"📊 Betwatch Settings API: http://localhost:5000/api/betwatch/settings")
    print(f"📈 22bet Anomalies: http://localhost:5000/anomalies_22bet")
    print("=" * 70)
    
    app.run(host='0.0.0.0', port=5000, debug=True)
