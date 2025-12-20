# -*- coding: utf-8 -*-
"""
Inforadar Pro - Flask Backend
D:\Inforadar_Pro\inforadar_ui\app.py
"""

from flask import Flask, render_template, jsonify, request, render_template_string
import pymysql
from datetime import datetime, timedelta
from collections import defaultdict
import json
import os

app = Flask(__name__)

# ====== DB SETTINGS ======
DB_HOST = "localhost"
DB_PORT = 3306
DB_USER = "root"
DB_PASSWORD = "ryban8991!"
DB_NAME = "inforadar"

# ====== CONFIG PATHS ======
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

def get_connection():
    """MySQL connection with pymysql"""
    try:
        conn = pymysql.connect(
            host=DB_HOST,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME,
            port=DB_PORT,
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=True,
            charset='utf8mb4'
        )
        print(f"✅ Connected to MySQL {DB_HOST}:{DB_PORT}/{DB_NAME}")
        return conn
    except Exception as e:
        print(f"❌ DB Connection Error: {e}")
        return None

# ====== JINJA FILTER ======
@app.template_filter('timeago')
def timeago(value):
    if not value:
        return ""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except Exception:
            return value
    now = datetime.utcnow()
    diff = now - value
    seconds = diff.total_seconds()
    if seconds < 60:
        return f"{int(seconds)}s"
    if seconds < 3600:
        return f"{int(seconds/60)}m"
    if seconds < 86400:
        return f"{int(seconds/3600)}h"
    if seconds < 604800:
        return f"{int(seconds/86400)}d"
    return value.strftime("%Y-%m-%d %H:%M")

# ===========================================================
# BETWATCH ROUTES
# ===========================================================

@app.route("/betwatch")
def betwatch_dashboard():
    """Betwatch Dashboard"""
    try:
        return render_template("betwatch.html")
    except Exception as e:
        print(f"❌ Error rendering betwatch.html: {e}")
        return f"<h1>Ошибка: {e}</h1><p>Проверьте что файл betwatch.html находится в D:\\Inforadar_Pro\\inforadar_ui\\templates\\</p>", 500

@app.route("/api/betwatch/signals")
def api_betwatch_signals():
    """API: Получить сигналы из MySQL"""
    try:
        signal_type = request.args.get("type", "all")
        hours = int(request.args.get("hours", 24))
        limit = int(request.args.get("limit", 100))
        
        conn = get_connection()
        if not conn:
            return jsonify({"success": False, "error": "Database connection failed"}), 500
        
        try:
            with conn.cursor() as cursor:
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
                
                # Конвертируем datetime в строки
                for signal in signals:
                    if signal.get("detected_at"):
                        signal["detected_at"] = signal["detected_at"].strftime("%Y-%m-%d %H:%M:%S")
                
                return jsonify({
                    "success": True,
                    "count": len(signals),
                    "signals": signals
                })
        
        except Exception as e:
            print(f"❌ Error in api_betwatch_signals: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
        finally:
            conn.close()
            
    except Exception as e:
        print(f"❌ Outer error in api_betwatch_signals: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/betwatch/stats")
def api_betwatch_stats():
    """API: Статистика сигналов из MySQL"""
    try:
        hours = int(request.args.get("hours", 24))
        
        conn = get_connection()
        if not conn:
            return jsonify({"success": False, "error": "Database connection failed"}), 500
        
        try:
            with conn.cursor() as cursor:
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
                
                # Топ событий
                cursor.execute("""
                    SELECT event_name, COUNT(*) as count
                    FROM betwatch_signals
                    WHERE detected_at >= NOW() - INTERVAL %s HOUR
                    GROUP BY event_name
                    ORDER BY count DESC
                    LIMIT 10
                """, (hours,))
                top_events = cursor.fetchall()
                
                # Средний перекос
                cursor.execute("""
                    SELECT AVG(flow_percent) as avg_flow
                    FROM betwatch_signals
                    WHERE detected_at >= NOW() - INTERVAL %s HOUR
                    AND flow_percent IS NOT NULL
                """, (hours,))
                result = cursor.fetchone()
                avg_flow = result["avg_flow"] if result and result["avg_flow"] else 0
                
                return jsonify({
                    "success": True,
                    "total": total,
                    "by_type": by_type,
                    "top_events": top_events,
                    "avg_flow": round(float(avg_flow), 2) if avg_flow else 0
                })
        
        except Exception as e:
            print(f"❌ Error in api_betwatch_stats: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
        finally:
            conn.close()
            
    except Exception as e:
        print(f"❌ Outer error in api_betwatch_stats: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/betwatch/settings", methods=["GET"])
def api_betwatch_get_settings():
    """API: Получить текущие настройки"""
    try:
        if os.path.exists(THRESHOLDS_FILE):
            with open(THRESHOLDS_FILE, 'r', encoding='utf-8') as f:
                settings = json.load(f)
        else:
            settings = DEFAULT_SETTINGS
        
        return jsonify({
            "success": True,
            "settings": settings
        })
    
    except Exception as e:
        print(f"❌ Error loading settings: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/betwatch/save-settings", methods=["POST"])
def api_betwatch_save_settings():
    """API: Сохранить настройки детектора"""
    try:
        settings = request.json
        
        # Валидация данных
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
        
        # Сохраняем настройки
        with open(THRESHOLDS_FILE, 'w', encoding='utf-8') as f:
            json.dump(validated_settings, f, indent=4, ensure_ascii=False)
        
        print(f"✅ Settings saved to {THRESHOLDS_FILE}")
        
        return jsonify({
            "success": True,
            "message": f"✅ Настройки сохранены! Перезапустите betwatch_advanced.py",
            "file": THRESHOLDS_FILE
        })
    
    except Exception as e:
        print(f"❌ Error saving settings: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/betwatch/fork-lifetime", methods=["POST"])
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
        
        conn = get_connection()
        if not conn:
            return jsonify({
                'success': False,
                'message': 'Ошибка подключения к БД'
            }), 500
        
        try:
            with conn.cursor() as cursor:
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
        
        finally:
            conn.close()
    
    except Exception as e:
        print(f"❌ Error in fork_lifetime: {e}")
        return jsonify({
            'success': False,
            'message': f'Ошибка: {str(e)}'
        }), 500

# ===========================================================
# OTHER ROUTES
# ===========================================================

@app.route("/")
def index():
    try:
        return render_template("index.html")
    except:
        return "<h1>Inforadar Pro</h1><p><a href='/betwatch'>Betwatch Dashboard</a></p>"

@app.route("/advanced")
def advanced_monitor():
    try:
        return render_template("advanced_monitor.html")
    except:
        return "<h1>Advanced Monitor</h1>"

@app.route("/exchange")
def exchange_dashboard():
    try:
        return render_template("dashboard_filter.html")
    except:
        return "<h1>Exchange Dashboard</h1>"

@app.route("/anomalies_22bet")
def anomalies_22bet_page():
    conn = get_connection()
    if not conn:
        return render_template_string("<h1>❌ Ошибка подключения к MySQL</h1><p>Проверьте что Docker запущен</p>")
    
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT 
                    id, event_name, sport, league, anomaly_type, market_type,
                    before_value, after_value, diff_pct, status, detected_at, comment
                FROM anomalies_22bet
                ORDER BY detected_at DESC, id DESC
                LIMIT 200
            """)
            rows = cursor.fetchall()
    except Exception as e:
        print(f"❌ Error: {e}")
        return f"<h1>Ошибка:</h1><pre>{e}</pre>"
    finally:
        conn.close()
    
    try:
        return render_template("anomalies_22bet.html", anomalies=rows)
    except:
        return f"<h1>22bet Anomalies</h1><p>Найдено {len(rows)} записей</p>"

@app.route("/metrics")
def metrics_stub():
    return "ok\n", 200, {"Content-Type": "text/plain; charset=utf-8"}

# ===========================================================
# MAIN
# ===========================================================

if __name__ == "__main__":
    # Создаем дефолтный файл настроек
    if not os.path.exists(THRESHOLDS_FILE):
        with open(THRESHOLDS_FILE, 'w', encoding='utf-8') as f:
            json.dump(DEFAULT_SETTINGS, f, indent=4, ensure_ascii=False)
        print(f"✅ Создан файл настроек: {THRESHOLDS_FILE}")
    
    print("=" * 70)
    print("🚀 Inforadar Pro - Flask Backend")
    print("=" * 70)
    print(f"🔗 MySQL: {DB_HOST}:{DB_PORT}/{DB_NAME}")
    print(f"📁 Конфигурация: {THRESHOLDS_FILE}")
    print(f"🌐 Главная: http://localhost:5000")
    print(f"📊 Betwatch: http://localhost:5000/betwatch")
    print("=" * 70)
    
    # Проверяем подключение к MySQL
    test_conn = get_connection()
    if test_conn:
        test_conn.close()
        print("✅ MySQL доступен!")
    else:
        print("❌ ВНИМАНИЕ: MySQL недоступен! Запустите Docker!")
    
    app.run(host="0.0.0.0", port=5000, debug=True)
