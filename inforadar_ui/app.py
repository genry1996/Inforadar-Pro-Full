# -*- coding: utf-8 -*-
"""
Inforadar Pro - Flask Backend PRODUCTION
D:\Inforadar_Pro\inforadar_ui\app.py
"""
from flask import Flask, render_template, jsonify, request
import pymysql
from datetime import datetime
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
os.makedirs(CONFIG_DIR, exist_ok=True)

# ====== PRODUCTION SETTINGS ======
PRODUCTION_SETTINGS = {
    # Sharp Drop - финальные критерии
    "drop_10_5_percent": 30,      # 10→5 минимум 30%
    "drop_5_2_percent": 20,       # 5→2.0 минимум 20%
    "drop_2_13_percent": 15,      # 2.0→1.3 минимум 15%
    "money_multiplier": 1.5,      # Превышение средней в 1.5x
    "late_game_minute": 75,       # Метка 75+ (визуал)
    "min_money_absolute": 1000,   # Минимум 1000€
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
            charset="utf8mb4",
        )
        print(f"✅ Connected to MySQL {DB_HOST}:{DB_PORT}/{DB_NAME}")
        return conn
    except Exception as e:
        print(f"❌ DB Connection Error: {e}")
        return None

# ====== JINJA FILTER ======
@app.template_filter("timeago")
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
    try:
        return render_template("betwatch.html")
    except Exception as e:
        print(f"❌ Error rendering betwatch.html: {e}")
        return (
            "Ошибка загрузки betwatch.html", 
            500,
        )

@app.route("/api/betwatch/signals")
def api_betwatch_signals():
    """API: Получить сигналы из MySQL (таблица betwatchsignals)"""
    try:
        signal_type = request.args.get("type", "all")
        hours = int(request.args.get("hours", 24))
        limit = int(request.args.get("limit", 100))
        status = request.args.get("status", "all")
        
        conn = get_connection()
        if not conn:
            return jsonify({"success": False, "error": "Database connection failed"}), 500
        
        try:
            with conn.cursor() as cursor:
                query = """
                SELECT 
                    id, signaltype AS signal_type, eventid AS event_id,
                    eventname AS event_name, league, markettype AS market_type,
                    betfairodd AS betfair_odd, moneyvolume AS money_volume,
                    totalmarketvolume AS total_market_volume,
                    oldodd AS old_odd, newodd AS new_odd,
                    odddroppercent AS odd_drop_percent,
                    islive AS is_live, matchtime AS match_time,
                    detectedat AS detected_at
                FROM betwatchsignals
                WHERE detectedat >= NOW() - INTERVAL %s HOUR
                """
                params = [hours]
                
                if signal_type != "all":
                    query += " AND signaltype LIKE %s"
                    params.append(f"%{signal_type}%")
                
                # фильтр статуса
                if status == "live":
                    query += " AND islive = 1"
                elif status == "prematch":
                    query += " AND islive = 0"
                elif status == "break":
                    query += " AND islive = 2"
                
                query += " ORDER BY detectedat DESC LIMIT %s"
                params.append(limit)
                
                cursor.execute(query, params)
                signals = cursor.fetchall()
                
                for signal in signals:
                    if signal.get("detected_at"):
                        signal["detected_at"] = signal["detected_at"].strftime("%Y-%m-%d %H:%M:%S")
                
                return jsonify({
                    "success": True,
                    "count": len(signals),
                    "signals": signals,
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
    """API: Статистика сигналов"""
    try:
        hours = int(request.args.get("hours", 24))
        conn = get_connection()
        if not conn:
            return jsonify({"success": False, "error": "Database connection failed"}), 500
        
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT COUNT(*) AS total
                    FROM betwatchsignals
                    WHERE detectedat >= NOW() - INTERVAL %s HOUR
                    """,
                    (hours,),
                )
                total = cursor.fetchone()["total"]
                
                cursor.execute(
                    """
                    SELECT signaltype AS signal_type, COUNT(*) AS count
                    FROM betwatchsignals
                    WHERE detectedat >= NOW() - INTERVAL %s HOUR
                    GROUP BY signaltype
                    """,
                    (hours,),
                )
                by_type = cursor.fetchall()
                
                # Считаем только sharpdrop
                sharp_count = sum(row["count"] for row in by_type if "sharp" in row["signal_type"].lower())
                
                return jsonify({
                    "success": True,
                    "total": total,
                    "by_type": by_type,
                    "sharp_drop_count": sharp_count,
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
            with open(THRESHOLDS_FILE, "r", encoding="utf-8") as f:
                settings = json.load(f)
        else:
            settings = PRODUCTION_SETTINGS
        return jsonify({"success": True, "settings": settings})
    except Exception as e:
        print(f"❌ Error loading settings: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/betwatch/save-settings", methods=["POST"])
def api_betwatch_save_settings():
    """API: Сохранить настройки детектора"""
    try:
        settings = request.json
        validated_settings = {
            "drop_10_5_percent": float(settings.get("drop_10_5_percent", 30)),
            "drop_5_2_percent": float(settings.get("drop_5_2_percent", 20)),
            "drop_2_13_percent": float(settings.get("drop_2_13_percent", 15)),
            "money_multiplier": float(settings.get("money_multiplier", 1.5)),
            "late_game_minute": int(settings.get("late_game_minute", 75)),
            "min_money_absolute": float(settings.get("min_money_absolute", 1000)),
        }
        
        with open(THRESHOLDS_FILE, "w", encoding="utf-8") as f:
            json.dump(validated_settings, f, indent=4, ensure_ascii=False)
        
        print(f"✅ Settings saved to {THRESHOLDS_FILE}")
        return jsonify({
            "success": True,
            "message": "✅ Настройки сохранены! Перезапусти betwatch_advanced.py"
        })
    except Exception as e:
        print(f"❌ Error saving settings: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

# =========================================================== 
# OTHER ROUTES
# =========================================================== 

@app.route("/")
def index():
    return "<h1>Betwatch Production</h1><p><a href='/betwatch'>Go to Dashboard</a></p>"

@app.route("/metrics")
def metrics_stub():
    return "ok", 200, {"Content-Type": "text/plain; charset=utf-8"}

# =========================================================== 
# MAIN
# =========================================================== 

if __name__ == "__main__":
    if not os.path.exists(THRESHOLDS_FILE):
        with open(THRESHOLDS_FILE, "w", encoding="utf-8") as f:
            json.dump(PRODUCTION_SETTINGS, f, indent=4, ensure_ascii=False)
        print(f"✅ Created {THRESHOLDS_FILE}")
    
    print("=" * 70)
    print("🎯 Inforadar Pro - Flask Backend PRODUCTION")
    print("=" * 70)
    print(f"📁 Config: {THRESHOLDS_FILE}")
    print(f"🗄️ MySQL: {DB_HOST}:{DB_PORT}/{DB_NAME}")
    print("")
    print("🌐 Main: http://localhost:5000")
    print("📊 Betwatch: http://localhost:5000/betwatch")
    print("=" * 70)
    
    test_conn = get_connection()
    if test_conn:
        test_conn.close()
        print("✅ MySQL OK!")
    else:
        print("⚠️ MySQL не подключен! Проверь настройки!")
    
    app.run(host="0.0.0.0", port=5000, debug=True)
