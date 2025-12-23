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
            "/prematch",
            "/live",
            "/anomalies_22bet",
            "/api/betwatch/settings",
            "/api/betwatch/save-settings",
            "/api/betwatch/signals",
            "/api/betwatch/stats",
            "/api/betwatch/fork-lifetime"
        ]
    })

# ===========================================================
# 22BET ODDS DISPLAY ROUTES
# ===========================================================

@app.route('/prematch')
def prematch():
    """Отображение прематч коэффициентов 22bet"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Получаем все активные события из odds_22bet
        cursor.execute("""
            SELECT 
                event_name,
                sport,
                league,
                market_type,
                odd_1,
                odd_x,
                odd_2,
                updated_at
            FROM odds_22bet
            WHERE status = 'active'
            ORDER BY updated_at DESC
            LIMIT 100
        """)
        
        odds = cursor.fetchall()
        
        # Конвертируем datetime в строку
        for odd in odds:
            if odd.get('updated_at'):
                odd['updated_at'] = odd['updated_at'].strftime('%Y-%m-%d %H:%M:%S')
        
        cursor.close()
        conn.close()
        
        html = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>22BET - Prematch Odds</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
            background: #f5f7fa;
            padding: 20px;
        }
        .header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px;
            border-radius: 10px;
            margin-bottom: 30px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }
        .header h1 { font-size: 32px; margin-bottom: 10px; }
        .header .subtitle { opacity: 0.9; font-size: 16px; }
        .stats {
            display: flex;
            gap: 20px;
            margin-bottom: 30px;
            flex-wrap: wrap;
        }
        .stat-card {
            background: white;
            padding: 20px;
            border-radius: 10px;
            flex: 1;
            min-width: 200px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        .stat-card .label { color: #666; font-size: 14px; margin-bottom: 5px; }
        .stat-card .value { 
            font-size: 32px; 
            font-weight: bold;
            color: #667eea;
        }
        .filters {
            background: white;
            padding: 20px;
            border-radius: 10px;
            margin-bottom: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        .filters input, .filters select {
            padding: 10px;
            border: 2px solid #e1e8ed;
            border-radius: 5px;
            margin-right: 10px;
            font-size: 14px;
        }
        .filters button {
            padding: 10px 20px;
            background: #667eea;
            color: white;
            border: none;
            border-radius: 5px;
            cursor: pointer;
            font-size: 14px;
            font-weight: 500;
        }
        .filters button:hover { background: #5568d3; }
        .odds-container {
            background: white;
            border-radius: 10px;
            overflow: hidden;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        table { 
            width: 100%; 
            border-collapse: collapse;
        }
        th {
            background: #667eea;
            color: white;
            padding: 15px;
            text-align: left;
            font-weight: 500;
            font-size: 14px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        td { 
            padding: 15px;
            border-bottom: 1px solid #f0f0f0;
            font-size: 14px;
        }
        tr:hover { background: #f8f9fa; }
        .event-name { 
            font-weight: 600;
            color: #1a202c;
        }
        .sport-badge {
            display: inline-block;
            padding: 4px 12px;
            background: #e3f2fd;
            color: #1976d2;
            border-radius: 12px;
            font-size: 12px;
            font-weight: 500;
        }
        .odd-value {
            font-weight: 600;
            color: #667eea;
            font-size: 16px;
        }
        .timestamp {
            color: #666;
            font-size: 12px;
        }
        .no-data {
            padding: 60px;
            text-align: center;
            color: #666;
            font-size: 16px;
        }
        .refresh-btn {
            position: fixed;
            bottom: 30px;
            right: 30px;
            background: #667eea;
            color: white;
            border: none;
            padding: 15px 25px;
            border-radius: 50px;
            cursor: pointer;
            font-size: 14px;
            font-weight: 600;
            box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);
            transition: all 0.3s;
        }
        .refresh-btn:hover {
            background: #5568d3;
            transform: translateY(-2px);
            box-shadow: 0 6px 16px rgba(102, 126, 234, 0.5);
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>⚽ 22BET Prematch Odds</h1>
        <div class="subtitle">Real-time betting coefficients from 22bet.com</div>
    </div>

    <div class="stats">
        <div class="stat-card">
            <div class="label">Total Events</div>
            <div class="value">{{ odds|length }}</div>
        </div>
        <div class="stat-card">
            <div class="label">Sports</div>
            <div class="value">{{ odds|map(attribute='sport')|unique|list|length }}</div>
        </div>
        <div class="stat-card">
            <div class="label">Last Update</div>
            <div class="value" style="font-size: 18px;">
                {% if odds %}{{ odds[0].updated_at }}{% else %}—{% endif %}
            </div>
        </div>
    </div>

    <div class="odds-container">
        {% if odds %}
        <table>
            <thead>
                <tr>
                    <th>Event</th>
                    <th>Sport / League</th>
                    <th>Market</th>
                    <th style="text-align: center;">1</th>
                    <th style="text-align: center;">X</th>
                    <th style="text-align: center;">2</th>
                    <th>Updated</th>
                </tr>
            </thead>
            <tbody>
                {% for odd in odds %}
                <tr>
                    <td>
                        <div class="event-name">{{ odd.event_name }}</div>
                    </td>
                    <td>
                        <span class="sport-badge">{{ odd.sport or 'N/A' }}</span>
                        <div style="margin-top: 5px; font-size: 12px; color: #666;">
                            {{ odd.league or 'Unknown League' }}
                        </div>
                    </td>
                    <td>{{ odd.market_type or '1X2' }}</td>
                    <td style="text-align: center;">
                        <span class="odd-value">{{ "%.2f"|format(odd.odd_1) if odd.odd_1 else '—' }}</span>
                    </td>
                    <td style="text-align: center;">
                        <span class="odd-value">{{ "%.2f"|format(odd.odd_x) if odd.odd_x else '—' }}</span>
                    </td>
                    <td style="text-align: center;">
                        <span class="odd-value">{{ "%.2f"|format(odd.odd_2) if odd.odd_2 else '—' }}</span>
                    </td>
                    <td>
                        <span class="timestamp">{{ odd.updated_at }}</span>
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
        {% else %}
        <div class="no-data">
            😕 No prematch odds available<br>
            <small style="color: #999; margin-top: 10px; display: block;">
                Parser may not be running or no events found
            </small>
        </div>
        {% endif %}
    </div>

    <button class="refresh-btn" onclick="location.reload()">🔄 Refresh</button>

    <script>
        // Auto-refresh every 15 seconds
        setTimeout(() => location.reload(), 15000);
    </script>
</body>
</html>
        """
        
        return render_template_string(html, odds=odds)
        
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/live')
def live():
    """Отображение live коэффициентов 22bet"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # Для live можно добавить фильтр по времени (например, обновлённые за последние 5 минут)
        cursor.execute("""
            SELECT 
                event_name,
                sport,
                league,
                market_type,
                odd_1,
                odd_x,
                odd_2,
                updated_at
            FROM odds_22bet
            WHERE status = 'active'
              AND updated_at >= DATE_SUB(NOW(), INTERVAL 10 MINUTE)
            ORDER BY updated_at DESC
            LIMIT 100
        """)
        
        odds = cursor.fetchall()
        
        # Конвертируем datetime в строку
        for odd in odds:
            if odd.get('updated_at'):
                odd['updated_at'] = odd['updated_at'].strftime('%Y-%m-%d %H:%M:%S')
        
        cursor.close()
        conn.close()
        
        html = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>22BET - Live Odds</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
            background: #0f1419;
            color: white;
            padding: 20px;
        }
        .header {
            background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
            color: white;
            padding: 30px;
            border-radius: 10px;
            margin-bottom: 30px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.3);
        }
        .header h1 { 
            font-size: 32px; 
            margin-bottom: 10px;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .live-indicator {
            display: inline-block;
            width: 12px;
            height: 12px;
            background: #ff4444;
            border-radius: 50%;
            animation: pulse 1.5s infinite;
        }
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.3; }
        }
        .header .subtitle { opacity: 0.9; font-size: 16px; }
        .stats {
            display: flex;
            gap: 20px;
            margin-bottom: 30px;
            flex-wrap: wrap;
        }
        .stat-card {
            background: #1c2128;
            padding: 20px;
            border-radius: 10px;
            flex: 1;
            min-width: 200px;
            border: 1px solid #30363d;
        }
        .stat-card .label { color: #8b949e; font-size: 14px; margin-bottom: 5px; }
        .stat-card .value { 
            font-size: 32px; 
            font-weight: bold;
            color: #f5576c;
        }
        .odds-container {
            background: #1c2128;
            border-radius: 10px;
            overflow: hidden;
            border: 1px solid #30363d;
        }
        table { 
            width: 100%; 
            border-collapse: collapse;
        }
        th {
            background: #f5576c;
            color: white;
            padding: 15px;
            text-align: left;
            font-weight: 500;
            font-size: 14px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        td { 
            padding: 15px;
            border-bottom: 1px solid #30363d;
            font-size: 14px;
        }
        tr:hover { background: #22272e; }
        .event-name { 
            font-weight: 600;
            color: #e6edf3;
        }
        .sport-badge {
            display: inline-block;
            padding: 4px 12px;
            background: rgba(245, 87, 108, 0.2);
            color: #f5576c;
            border-radius: 12px;
            font-size: 12px;
            font-weight: 500;
            border: 1px solid rgba(245, 87, 108, 0.3);
        }
        .odd-value {
            font-weight: 600;
            color: #58a6ff;
            font-size: 16px;
        }
        .timestamp {
            color: #8b949e;
            font-size: 12px;
        }
        .no-data {
            padding: 60px;
            text-align: center;
            color: #8b949e;
            font-size: 16px;
        }
        .refresh-btn {
            position: fixed;
            bottom: 30px;
            right: 30px;
            background: #f5576c;
            color: white;
            border: none;
            padding: 15px 25px;
            border-radius: 50px;
            cursor: pointer;
            font-size: 14px;
            font-weight: 600;
            box-shadow: 0 4px 12px rgba(245, 87, 108, 0.4);
            transition: all 0.3s;
        }
        .refresh-btn:hover {
            background: #e94560;
            transform: translateY(-2px);
            box-shadow: 0 6px 16px rgba(245, 87, 108, 0.5);
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>
            <span class="live-indicator"></span>
            22BET Live Odds
        </h1>
        <div class="subtitle">Real-time in-play betting coefficients</div>
    </div>

    <div class="stats">
        <div class="stat-card">
            <div class="label">Live Events</div>
            <div class="value">{{ odds|length }}</div>
        </div>
        <div class="stat-card">
            <div class="label">Sports</div>
            <div class="value">{{ odds|map(attribute='sport')|unique|list|length }}</div>
        </div>
        <div class="stat-card">
            <div class="label">Last Update</div>
            <div class="value" style="font-size: 18px;">
                {% if odds %}{{ odds[0].updated_at }}{% else %}—{% endif %}
            </div>
        </div>
    </div>

    <div class="odds-container">
        {% if odds %}
        <table>
            <thead>
                <tr>
                    <th>Event</th>
                    <th>Sport / League</th>
                    <th>Market</th>
                    <th style="text-align: center;">1</th>
                    <th style="text-align: center;">X</th>
                    <th style="text-align: center;">2</th>
                    <th>Updated</th>
                </tr>
            </thead>
            <tbody>
                {% for odd in odds %}
                <tr>
                    <td>
                        <div class="event-name">{{ odd.event_name }}</div>
                    </td>
                    <td>
                        <span class="sport-badge">{{ odd.sport or 'N/A' }}</span>
                        <div style="margin-top: 5px; font-size: 12px; color: #8b949e;">
                            {{ odd.league or 'Unknown League' }}
                        </div>
                    </td>
                    <td>{{ odd.market_type or '1X2' }}</td>
                    <td style="text-align: center;">
                        <span class="odd-value">{{ "%.2f"|format(odd.odd_1) if odd.odd_1 else '—' }}</span>
                    </td>
                    <td style="text-align: center;">
                        <span class="odd-value">{{ "%.2f"|format(odd.odd_x) if odd.odd_x else '—' }}</span>
                    </td>
                    <td style="text-align: center;">
                        <span class="odd-value">{{ "%.2f"|format(odd.odd_2) if odd.odd_2 else '—' }}</span>
                    </td>
                    <td>
                        <span class="timestamp">{{ odd.updated_at }}</span>
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
        {% else %}
        <div class="no-data">
            😕 No live odds available<br>
            <small style="color: #666; margin-top: 10px; display: block;">
                No events updated in the last 10 minutes
            </small>
        </div>
        {% endif %}
    </div>

    <button class="refresh-btn" onclick="location.reload()">🔄 Refresh</button>

    <script>
        // Auto-refresh every 10 seconds for live data
        setTimeout(() => location.reload(), 10000);
    </script>
</body>
</html>
        """
        
        return render_template_string(html, odds=odds)
        
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

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
    print(f"⚽ Prematch: http://localhost:5000/prematch")
    print(f"🔴 Live: http://localhost:5000/live")
    print(f"📊 Betwatch Settings API: http://localhost:5000/api/betwatch/settings")
    print(f"📈 22bet Anomalies: http://localhost:5000/anomalies_22bet")
    print("=" * 70)
    
    app.run(host='0.0.0.0', port=5000, debug=True)
