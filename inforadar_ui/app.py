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
import logging

app = Flask(__name__)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s'
)

logger = logging.getLogger(__name__)

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
    "drop_5_2_percent": 20,        # 5→2.0 минимум 20%
    "drop_2_13_percent": 15,       # 2.0→1.3 минимум 15%
    "money_multiplier": 1.5,       # Превышение средней в 1.5x
    "late_game_minute": 75,        # Метка 75+ (визуал)
    "min_money_absolute": 1000,    # Минимум 1000€
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
        logger.debug(f"✅ Connected to MySQL {DB_HOST}:{DB_PORT}/{DB_NAME}")
        return conn
    except Exception as e:
        logger.error(f"❌ DB Connection Error: {e}")
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
        logger.error(f"❌ Error rendering betwatch.html: {e}")
        return ("Ошибка загрузки betwatch.html", 500)


@app.route("/api/betwatch/signals")
def api_betwatch_signals():
    """API: Получить сигналы из MySQL (таблица betwatch_signals)"""
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
                    id,
                    signal_type AS signal_type,
                    event_id AS event_id,
                    event_name AS event_name,
                    league,
                    market_type AS market_type,
                    betfair_odd AS betfair_odd,
                    money_volume AS money_volume,
                    total_market_volume AS total_market_volume,
                    old_odd AS old_odd,
                    new_odd AS new_odd,
                    odd_drop_percent AS odd_drop_percent,
                    is_live AS is_live,
                    match_time AS match_time,
                    detected_at AS detected_at
                FROM betwatch_signals
                WHERE detected_at >= NOW() - INTERVAL %s HOUR
                """
                params = [hours]

                if signal_type != "all":
                    query += " AND signal_type LIKE %s"
                    params.append(f"%{signal_type}%")

                # фильтр статуса
                if status == "live":
                    query += " AND is_live = 1"
                elif status == "prematch":
                    query += " AND is_live = 0"
                elif status == "break":
                    query += " AND is_live = 2"

                query += " ORDER BY detected_at DESC LIMIT %s"
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
            logger.error(f"❌ Error in api_betwatch_signals: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
        finally:
            conn.close()

    except Exception as e:
        logger.error(f"❌ Outer error in api_betwatch_signals: {e}")
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
                    FROM betwatch_signals
                    WHERE detected_at >= NOW() - INTERVAL %s HOUR
                    """,
                    (hours,),
                )
                total = cursor.fetchone()["total"]

                cursor.execute(
                    """
                    SELECT signal_type AS signal_type, COUNT(*) AS count
                    FROM betwatch_signals
                    WHERE detected_at >= NOW() - INTERVAL %s HOUR
                    GROUP BY signal_type
                    """,
                    (hours,),
                )
                by_type = cursor.fetchall()

                # Считаем только sharp_drop
                sharp_count = sum(row["count"] for row in by_type if "sharp" in row["signal_type"].lower())

                return jsonify({
                    "success": True,
                    "total": total,
                    "by_type": by_type,
                    "sharp_drop_count": sharp_count,
                })

        except Exception as e:
            logger.error(f"❌ Error in api_betwatch_stats: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
        finally:
            conn.close()

    except Exception as e:
        logger.error(f"❌ Outer error in api_betwatch_stats: {e}")
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
        logger.error(f"❌ Error loading settings: {e}")
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

        logger.info(f"✅ Settings saved to {THRESHOLDS_FILE}")

        return jsonify({
            "success": True,
            "message": "✅ Настройки сохранены! Перезапусти betwatch_advanced.py"
        })

    except Exception as e:
        logger.error(f"❌ Error saving settings: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ===========================================================
# 22BET ANOMALIES ROUTES
# ===========================================================

@app.route("/api/anomalies_22bet")
def api_anomalies_22bet():
    """API endpoint for 22bet anomalies data"""
    try:
        min_pct = float(request.args.get('min_pct', 2.0))
        anomaly_type = request.args.get('type')
        hours = int(request.args.get('hours', 4))

        conn = get_connection()
        if not conn:
            return jsonify({"success": False, "error": "DB connection failed"}), 500

        cursor = conn.cursor()

        query = f"""
        SELECT
            id,
            event_name,
            sport,
            league,
            anomaly_type,
            before_value,
            after_value,
            diff_pct,
            status,
            comment,
            detected_at,
            CASE
                WHEN ABS(diff_pct) >= 10 THEN 'critical'
                WHEN ABS(diff_pct) >= 5 THEN 'important'
                WHEN ABS(diff_pct) >= 2 THEN 'moderate'
                ELSE 'low'
            END as severity
        FROM anomalies_22bet
        WHERE detected_at >= DATE_SUB(NOW(), INTERVAL {hours} HOUR)
        AND ABS(diff_pct) >= {min_pct}
        """

        if anomaly_type == 'drop':
            query += " AND anomaly_type = 'ODDS_DROP'"
        elif anomaly_type == 'rise':
            query += " AND anomaly_type = 'ODDS_RISE'"

        query += " ORDER BY detected_at DESC LIMIT 500"

        cursor.execute(query)
        results = cursor.fetchall()

        data = []
        for row in results:
            data.append({
                'id': row['id'],
                'event_name': row['event_name'],
                'sport': row['sport'],
                'league': row['league'],
                'type': row['anomaly_type'],
                'before': float(row['before_value']) if row['before_value'] else 0,
                'after': float(row['after_value']) if row['after_value'] else 0,
                'change_pct': float(row['diff_pct']),
                'severity': row['severity'],
                'status': row['status'],
                'comment': row['comment'],
                'time': row['detected_at'].strftime('%Y-%m-%d %H:%M:%S') if row['detected_at'] else '',
            })

        cursor.close()
        conn.close()

        return jsonify({
            'success': True,
            'count': len(data),
            'data': data,
        })

    except Exception as e:
        logger.error(f"❌ Error in api_anomalies_22bet: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route("/anomalies_22bet")
def anomalies_22bet_page():
    """Page with 22bet anomalies"""
    return render_template("anomalies_22bet.html")


# ===========================================================
# MATCH DETAIL PAGE & API (FIXED)
# ===========================================================

@app.route("/match/<path:event_name>")
def match_detail(event_name):
    """Детальная страница матча с историей коэффициентов"""
    try:
        from urllib.parse import unquote
        event_name = unquote(event_name)
        return render_template("match_detail.html", event_name=event_name)
    except Exception as e:
        logger.error(f"❌ Error rendering match_detail: {e}")
        return ("Ошибка загрузки страницы матча", 500)


@app.route("/api/match/<path:event_name>/history")
def api_match_history(event_name):
    """API: История изменений коэффициентов для конкретного матча"""
    try:
        from urllib.parse import unquote
        event_name = unquote(event_name)
        hours = int(request.args.get('hours', 48))  # 👈 Увеличил до 48 часов

        conn = get_connection()
        if not conn:
            return jsonify({"success": False, "error": "DB connection failed"}), 500

        cursor = conn.cursor()

        # 🔥 ИСПРАВЛЕНО: Ищем по LIKE (чтобы найти "Team1 vs Team2 | 1x2")
        query = """
        SELECT
            event_name,
            sport,
            market_type,
            market_key,
            odd_1,
            odd_x,
            odd_2,
            updated_at,
            created_at
        FROM odds_22bet
        WHERE event_name LIKE %s
        AND updated_at >= DATE_SUB(NOW(), INTERVAL %s HOUR)
        ORDER BY updated_at ASC
        LIMIT 500
        """

        # Ищем точное совпадение ИЛИ с суффиксом "| 1x2"
        search_pattern = f"%{event_name}%"
        cursor.execute(query, (search_pattern, hours))
        odds_history = cursor.fetchall()

        logger.info(f"📊 Found {len(odds_history)} records for '{event_name}'")

        # Получаем аномалии для этого события
        anomaly_query = """
        SELECT
            id,
            anomaly_type,
            before_value,
            after_value,
            diff_pct,
            comment,
            detected_at,
            CASE
                WHEN ABS(diff_pct) >= 10 THEN 'critical'
                WHEN ABS(diff_pct) >= 5 THEN 'important'
                WHEN ABS(diff_pct) >= 2 THEN 'moderate'
                ELSE 'low'
            END as severity
        FROM anomalies_22bet
        WHERE event_name LIKE %s
        AND detected_at >= DATE_SUB(NOW(), INTERVAL %s HOUR)
        ORDER BY detected_at DESC
        LIMIT 100
        """
        cursor.execute(anomaly_query, (search_pattern, hours))
        anomalies = cursor.fetchall()

        # Форматируем данные для графика
        timeline = []
        for row in odds_history:
            timeline.append({
                'time': row['updated_at'].strftime('%Y-%m-%d %H:%M:%S'),
                'odd_1': float(row['odd_1']) if row['odd_1'] else None,
                'odd_x': float(row['odd_x']) if row['odd_x'] else None,
                'odd_2': float(row['odd_2']) if row['odd_2'] else None,
                'market': row['market_type'],
            })

        anomaly_list = []
        for a in anomalies:
            anomaly_list.append({
                'id': a['id'],
                'type': a['anomaly_type'],
                'before': a['before_value'],
                'after': a['after_value'],
                'change_pct': float(a['diff_pct']),
                'severity': a['severity'],
                'comment': a['comment'],
                'time': a['detected_at'].strftime('%Y-%m-%d %H:%M:%S'),
            })

        cursor.close()
        conn.close()

        return jsonify({
            'success': True,
            'event_name': event_name,
            'timeline': timeline,
            'anomalies': anomaly_list,
            'total_anomalies': len(anomaly_list),
        })

    except Exception as e:
        logger.error(f"❌ Error in api_match_history: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route("/api/match/<path:event_name>/stats")
def api_match_stats(event_name):
    """API: Статистика матча (мин/макс коэффициенты, движение)"""
    try:
        from urllib.parse import unquote
        event_name = unquote(event_name)

        conn = get_connection()
        if not conn:
            return jsonify({"success": False, "error": "DB connection failed"}), 500

        cursor = conn.cursor()

        # 🔥 ИСПРАВЛЕНО: Ищем по LIKE
        stats_query = """
        SELECT
            MIN(odd_1) as min_odd_1,
            MAX(odd_1) as max_odd_1,
            MIN(odd_2) as min_odd_2,
            MAX(odd_2) as max_odd_2,
            MIN(odd_x) as min_odd_x,
            MAX(odd_x) as max_odd_x,
            COUNT(*) as updates_count,
            MIN(created_at) as first_seen,
            MAX(updated_at) as last_update
        FROM odds_22bet
        WHERE event_name LIKE %s
        """

        search_pattern = f"%{event_name}%"
        cursor.execute(stats_query, (search_pattern,))
        stats = cursor.fetchone()

        cursor.close()
        conn.close()

        if not stats or stats['updates_count'] == 0:
            return jsonify({
                'success': False,
                'error': f'No data found for match: {event_name}'
            }), 404

        return jsonify({
            'success': True,
            'stats': {
                'odd_1': {
                    'min': float(stats['min_odd_1']) if stats['min_odd_1'] else 0,
                    'max': float(stats['max_odd_1']) if stats['max_odd_1'] else 0,
                },
                'odd_x': {
                    'min': float(stats['min_odd_x']) if stats['min_odd_x'] else 0,
                    'max': float(stats['max_odd_x']) if stats['max_odd_x'] else 0,
                },
                'odd_2': {
                    'min': float(stats['min_odd_2']) if stats['min_odd_2'] else 0,
                    'max': float(stats['max_odd_2']) if stats['max_odd_2'] else 0,
                },
                'updates_count': stats['updates_count'],
                'first_seen': stats['first_seen'].strftime('%Y-%m-%d %H:%M:%S') if stats['first_seen'] else '',
                'last_update': stats['last_update'].strftime('%Y-%m-%d %H:%M:%S') if stats['last_update'] else '',
            }
        })

    except Exception as e:
        logger.error(f"❌ Error in api_match_stats: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return jsonify({'success': False, 'error': str(e)}), 500


# ===========================================================
# OTHER ROUTES
# ===========================================================

@app.route("/")
def index():
    return "Go to /betwatch or /anomalies_22bet"


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
        logger.info(f"✅ Created {THRESHOLDS_FILE}")

    print("=" * 70)
    print("🎯 Inforadar Pro - Flask Backend PRODUCTION")
    print("=" * 70)
    print(f"📁 Config: {THRESHOLDS_FILE}")
    print(f"🗄️  MySQL: {DB_HOST}:{DB_PORT}/{DB_NAME}")
    print("")
    print("🌐 Main: http://localhost:5000")
    print("📊 Betwatch: http://localhost:5000/betwatch")
    print("🎯 22BET: http://localhost:5000/anomalies_22bet")
    print("=" * 70)

    test_conn = get_connection()
    if test_conn:
        test_conn.close()
        print("✅ MySQL OK!")
    else:
        print("⚠️  MySQL не подключен! Проверь настройки!")

    app.run(host="0.0.0.0", port=5000, debug=True)
