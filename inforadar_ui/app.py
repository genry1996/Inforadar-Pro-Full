# ====================================================================
# Inforadar Pro - Flask Backend
# D:\Inforadar_Pro\inforadar_ui\app.py
# ====================================================================

from flask import Flask, render_template, jsonify, request
import pymysql
from datetime import datetime, timedelta
import os
import logging
import json
import hashlib

# ==================== НАСТРОЙКА ЛОГИРОВАНИЯ ====================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

logger = logging.getLogger(__name__)

# ==================== ИНИЦИАЛИЗАЦИЯ FLASK ====================
app = Flask(__name__)

# ==================== КОНФИГУРАЦИЯ БД ====================
DB_CONFIG = {
    'host': os.getenv('MYSQL_HOST', 'localhost'),
    'user': os.getenv('MYSQL_USER', 'root'),
    'password': os.getenv('MYSQL_PASSWORD', 'ryban8991!'),
    'database': os.getenv('MYSQL_DB', 'inforadar'),
    'charset': 'utf8mb4',
    'cursorclass': pymysql.cursors.DictCursor
}

# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================
def get_connection():
    """Создать подключение к MySQL"""
    try:
        return pymysql.connect(**DB_CONFIG)
    except Exception as e:
        logger.error(f"❌ MySQL connection error: {e}")
        return None

def str_to_bool(value):
    """Конвертация строки в bool для query параметров"""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ('true', '1', 'yes', 'on')
    return False

def format_datetime(dt):
    """Форматирование datetime в строку"""
    if dt:
        return dt.strftime('%Y-%m-%d %H:%M:%S')
    return None

def calculate_severity(change_pct):
    """Расчет критичности изменения"""
    abs_change = abs(change_pct)
    if abs_change >= 10:
        return 'critical'
    elif abs_change >= 5:
        return 'important'
    else:
        return 'moderate'

# ==================== HTML МАРШРУТЫ ====================
@app.route('/')
def index():
    """Главная страница - редирект на /live"""
    return render_template('anomalies_22bet.html')

@app.route('/live')
def live_page():
    """Страница LIVE матчей"""
    return render_template('anomalies_22bet.html')

@app.route('/prematch')
def prematch_page():
    """Страница PREMATCH матчей"""
    return render_template('anomalies_22bet.html')

@app.route('/anomalies_22bet')
def anomalies_22bet_page():
    """Страница всех аномалий 22BET"""
    return render_template('anomalies_22bet.html')

@app.route('/betwatch')
def betwatch_page():
    """Страница мониторинга BetWatch"""
    return render_template('betwatch.html')

@app.route('/match/<event_name>')
def match_detail_page(event_name):
    """Детальная страница матча"""
    return render_template('match_detail.html')

# ==================== API ЭНДПОИНТЫ ====================

@app.route('/api/anomalies_filtered')
def anomalies_filtered():
    """
    Фильтрованные аномалии с поддержкой real_only

    Параметры:
    - real_only: true/false - только игры, которых НЕТ на БК
    - min_pct: минимальный % изменения (по умолчанию 2)
    - hours: период в часах (по умолчанию 4)
    - type: тип изменения (rise/drop/all)
    - market: тип рынка (1x2/total/handicap/all)
    - outcome: исход (1/X/2/over/under/all)
    - severity: критичность (critical/important/moderate/all)
    - status: live/prematch/all
    """
    try:
        # Парсинг параметров
        real_only = str_to_bool(request.args.get('real_only', 'false'))
        min_pct = float(request.args.get('min_pct', 2))
        hours = int(request.args.get('hours', 4))
        change_type = request.args.get('type', 'all').lower()
        market = request.args.get('market', 'all').lower()
        outcome = request.args.get('outcome', 'all').lower()
        severity = request.args.get('severity', 'all').lower()
        # ⭐ по умолчанию показываем live
        status = request.args.get('status', 'live').lower()

        logger.info(f"🔍 Filtering anomalies: real_only={real_only}, min_pct={min_pct}, hours={hours}, status={status}")

        conn = get_connection()
        if not conn:
            return jsonify({'success': False, 'error': 'Database connection failed'}), 500

        cursor = conn.cursor()

        # Базовый запрос
        query = """
            SELECT
                a.id,
                a.event_name,
                a.league,
                a.market,
                a.outcome,
                a.before_odds,
                a.after_odds,
                a.change_pct,
                a.severity,
                a.time,
                a.bookmaker,
                a.is_live,
                a.match_minute,
                a.score,
                a.match_time
            FROM anomalies a
            WHERE a.time >= NOW() - INTERVAL %s HOUR
            AND ABS(a.change_pct) >= %s
            AND a.bookmaker = '22bet'
        """
        params = [hours, min_pct]

        # ⭐ ФИЛЬТР REAL_ONLY - только "осиротевшие" игры (не отображаются на БК)
        if real_only:
            query += """
                AND a.event_name NOT IN (
                    SELECT DISTINCT event_name
                    FROM bookmaker_events
                    WHERE last_seen >= NOW() - INTERVAL 5 MINUTE
                    AND bookmaker = '22bet'
                )
            """
            logger.info("🎯 Real-only filter enabled: showing orphan games only")

        # Фильтр по статусу (live/prematch)
        if status == 'live':
            query += " AND (a.is_live = 1 OR a.match_minute > 0)"
        elif status == 'prematch':
            query += " AND (a.is_live = 0 AND (a.match_minute = 0 OR a.match_minute IS NULL))"

        # Фильтр по типу изменения
        if change_type == 'rise':
            query += " AND a.change_pct > 0"
        elif change_type == 'drop':
            query += " AND a.change_pct < 0"

        # Фильтр по рынку
        if market != 'all':
            query += " AND LOWER(a.market) = %s"
            params.append(market)

        # Фильтр по исходу
        if outcome != 'all':
            query += " AND LOWER(a.outcome) = %s"
            params.append(outcome)

        # Фильтр по критичности
        if severity != 'all':
            query += " AND LOWER(a.severity) = %s"
            params.append(severity)

        query += " ORDER BY a.time DESC LIMIT 200"

        cursor.execute(query, params)
        data = cursor.fetchall()

        # Форматирование результата
        result = []
        for row in data:
            result.append({
                'id': row['id'],
                'event_name': row['event_name'],
                'league': row.get('league', 'Unknown'),
                'market': row['market'],
                'outcome': row['outcome'],
                'before_odds': float(row['before_odds']) if row['before_odds'] else None,
                'after_odds': float(row['after_odds']) if row['after_odds'] else None,
                'change_pct': float(row['change_pct']),
                'severity': row['severity'],
                'time': format_datetime(row['time']),
                'bookmaker': row.get('bookmaker', '22bet'),
                'is_live': bool(row.get('is_live', False)),
                'match_minute': row.get('match_minute'),
                'score': row.get('score'),
                'match_time': format_datetime(row.get('match_time'))
            })

        cursor.close()
        conn.close()

        logger.info(f"✅ Returned {len(result)} anomalies (real_only: {real_only}, status: {status})")

        return jsonify({
            'success': True,
            'count': len(result),
            'real_only': real_only,
            'filters': {
                'min_pct': min_pct,
                'hours': hours,
                'type': change_type,
                'market': market,
                'outcome': outcome,
                'severity': severity,
                'status': status
            },
            'data': result
        })

    except Exception as e:
        logger.error(f"❌ Error in anomalies_filtered: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/anomalies_22bet')
def api_anomalies_22bet():
    """API для всех аномалий 22BET (legacy endpoint)"""
    try:
        hours = int(request.args.get('hours', 4))
        min_pct = float(request.args.get('min_pct', 2))

        conn = get_connection()
        if not conn:
            return jsonify([]), 500

        cursor = conn.cursor()

        query = """
            SELECT
                event_name,
                league,
                market,
                outcome,
                before_odds,
                after_odds,
                change_pct,
                severity,
                time,
                is_live,
                match_minute,
                score
            FROM anomalies
            WHERE time >= NOW() - INTERVAL %s HOUR
            AND ABS(change_pct) >= %s
            AND bookmaker = '22bet'
            ORDER BY time DESC
            LIMIT 100
        """

        cursor.execute(query, (hours, min_pct))
        data = cursor.fetchall()

        result = []
        for row in data:
            result.append({
                'event_name': row['event_name'],
                'league': row.get('league', 'Unknown'),
                'market': row['market'],
                'outcome': row['outcome'],
                'before_odds': float(row['before_odds']) if row['before_odds'] else None,
                'after_odds': float(row['after_odds']) if row['after_odds'] else None,
                'change_pct': float(row['change_pct']),
                'severity': row['severity'],
                'time': format_datetime(row['time']),
                'is_live': bool(row.get('is_live', False)),
                'match_minute': row.get('match_minute'),
                'score': row.get('score')
            })

        cursor.close()
        conn.close()

        return jsonify(result)

    except Exception as e:
        logger.error(f"❌ Error: {e}")
        return jsonify([]), 500


@app.route('/api/match/<event_name>/full')
def match_full_data(event_name):
    """Полные данные матча с историей коэффициентов"""
    try:
        conn = get_connection()
        if not conn:
            return jsonify({'error': 'Database connection failed'}), 500

        cursor = conn.cursor()

        # Получить историю коэффициентов
        query = """
            SELECT
                timestamp,
                odds_1x2_home,
                odds_1x2_draw,
                odds_1x2_away,
                odds_total_over,
                odds_total_under,
                odds_handicap_home,
                odds_handicap_away,
                minute,
                score_home,
                score_away
            FROM live_matches
            WHERE event_name = %s
            ORDER BY timestamp ASC
        """

        cursor.execute(query, (event_name,))
        history = cursor.fetchall()

        if not history:
            cursor.close()
            conn.close()
            return jsonify({'error': 'Match not found'}), 404

        # Форматирование данных
        result = {
            'event_name': event_name,
            'history': []
        }

        for row in history:
            result['history'].append({
                'timestamp': row['timestamp'].isoformat() if row['timestamp'] else None,
                'odds_1x2': {
                    'home': float(row['odds_1x2_home']) if row['odds_1x2_home'] else None,
                    'draw': float(row['odds_1x2_draw']) if row['odds_1x2_draw'] else None,
                    'away': float(row['odds_1x2_away']) if row['odds_1x2_away'] else None
                },
                'odds_total': {
                    'over': float(row['odds_total_over']) if row['odds_total_over'] else None,
                    'under': float(row['odds_total_under']) if row['odds_total_under'] else None
                },
                'odds_handicap': {
                    'home': float(row['odds_handicap_home']) if row['odds_handicap_home'] else None,
                    'away': float(row['odds_handicap_away']) if row['odds_handicap_away'] else None
                },
                'minute': row.get('minute'),
                'score': {
                    'home': row.get('score_home'),
                    'away': row.get('score_away')
                }
            })

        cursor.close()
        conn.close()

        return jsonify(result)

    except Exception as e:
        logger.error(f"❌ Error in match_full_data: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/match/<event_name>/anomalies')
def match_anomalies(event_name):
    """Получить все аномалии для конкретного матча"""
    try:
        conn = get_connection()
        if not conn:
            return jsonify([]), 500

        cursor = conn.cursor()

        query = """
            SELECT
                market,
                outcome,
                before_odds,
                after_odds,
                change_pct,
                severity,
                time
            FROM anomalies
            WHERE event_name = %s
            AND bookmaker = '22bet'
            ORDER BY time DESC
            LIMIT 50
        """

        cursor.execute(query, (event_name,))
        anomalies = cursor.fetchall()

        result = []
        for row in anomalies:
            result.append({
                'market': row['market'],
                'outcome': row['outcome'],
                'before_odds': float(row['before_odds']) if row['before_odds'] else None,
                'after_odds': float(row['after_odds']) if row['after_odds'] else None,
                'change_pct': float(row['change_pct']),
                'severity': row['severity'],
                'time': format_datetime(row['time'])
            })

        cursor.close()
        conn.close()

        return jsonify(result)

    except Exception as e:
        logger.error(f"❌ Error: {e}")
        return jsonify([]), 500


@app.route('/api/live_matches')
def api_live_matches():
    """Получить список всех live матчей"""
    try:
        conn = get_connection()
        if not conn:
            return jsonify([]), 500

        cursor = conn.cursor()

        query = """
            SELECT DISTINCT
                event_name,
                league,
                minute,
                score_home,
                score_away,
                MAX(timestamp) as last_update
            FROM live_matches
            WHERE timestamp >= NOW() - INTERVAL 1 HOUR
            GROUP BY event_name, league, minute, score_home, score_away
            ORDER BY last_update DESC
        """

        cursor.execute(query)
        matches = cursor.fetchall()

        result = []
        for row in matches:
            result.append({
                'event_name': row['event_name'],
                'league': row.get('league', 'Unknown'),
                'minute': row.get('minute'),
                'score': f"{row.get('score_home', 0)}:{row.get('score_away', 0)}",
                'last_update': format_datetime(row['last_update'])
            })

        cursor.close()
        conn.close()

        return jsonify(result)

    except Exception as e:
        logger.error(f"❌ Error: {e}")
        return jsonify([]), 500


@app.route('/api/stats')
def api_stats():
    """Общая статистика"""
    try:
        conn = get_connection()
        if not conn:
            return jsonify({
                'total_anomalies': 0,
                'critical': 0,
                'important': 0,
                'moderate': 0,
                'hour_anomalies': 0,
                'live_matches': 0
            }), 200

        cursor = conn.cursor()

        # Общее количество аномалий за последние 24 часа
        cursor.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN severity = 'critical' THEN 1 ELSE 0 END) as critical,
                SUM(CASE WHEN severity = 'important' THEN 1 ELSE 0 END) as important,
                SUM(CASE WHEN severity = 'moderate' THEN 1 ELSE 0 END) as moderate
            FROM anomalies
            WHERE time >= NOW() - INTERVAL 24 HOUR
            AND bookmaker = '22bet'
        """)
        stats_24h = cursor.fetchone()

        # Аномалии за последний час
        cursor.execute("""
            SELECT COUNT(*) as count
            FROM anomalies
            WHERE time >= NOW() - INTERVAL 1 HOUR
            AND bookmaker = '22bet'
        """)
        stats_1h = cursor.fetchone()

        # Количество live матчей
        cursor.execute("""
            SELECT COUNT(DISTINCT event_name) as count
            FROM live_matches
            WHERE timestamp >= NOW() - INTERVAL 10 MINUTE
        """)
        live_count = cursor.fetchone()

        cursor.close()
        conn.close()

        return jsonify({
            'total_anomalies': stats_24h['total'] or 0,
            'critical': stats_24h['critical'] or 0,
            'important': stats_24h['important'] or 0,
            'moderate': stats_24h['moderate'] or 0,
            'hour_anomalies': stats_1h['count'] or 0,
            'live_matches': live_count['count'] or 0
        })

    except Exception as e:
        logger.error(f"❌ Error in api_stats: {e}")
        return jsonify({
            'total_anomalies': 0,
            'critical': 0,
            'important': 0,
            'moderate': 0,
            'hour_anomalies': 0,
            'live_matches': 0
        }), 200


@app.route('/api/betwatch/signals')
def betwatch_signals():
    """API для BetWatch сигналов"""
    try:
        conn = get_connection()
        if not conn:
            return jsonify([]), 500

        cursor = conn.cursor()

        query = """
            SELECT
                event_name,
                league,
                market,
                outcome,
                before_odds,
                after_odds,
                change_pct,
                severity,
                time,
                is_live,
                match_minute
            FROM anomalies
            WHERE time >= NOW() - INTERVAL 1 HOUR
            AND ABS(change_pct) >= 5
            AND bookmaker = '22bet'
            ORDER BY ABS(change_pct) DESC
            LIMIT 50
        """

        cursor.execute(query)
        signals = cursor.fetchall()

        result = []
        for row in signals:
            result.append({
                'event_name': row['event_name'],
                'league': row.get('league', 'Unknown'),
                'market': row['market'],
                'outcome': row['outcome'],
                'before_odds': float(row['before_odds']) if row['before_odds'] else None,
                'after_odds': float(row['after_odds']) if row['after_odds'] else None,
                'change_pct': float(row['change_pct']),
                'severity': row['severity'],
                'time': format_datetime(row['time']),
                'is_live': bool(row.get('is_live', False)),
                'match_minute': row.get('match_minute')
            })

        cursor.close()
        conn.close()

        return jsonify(result)

    except Exception as e:
        logger.error(f"❌ Error: {e}")
        return jsonify([]), 500


@app.route('/api/leagues')
def api_leagues():
    """Получить список всех лиг"""
    try:
        conn = get_connection()
        if not conn:
            return jsonify([]), 500

        cursor = conn.cursor()

        query = """
            SELECT DISTINCT league, COUNT(*) as match_count
            FROM anomalies
            WHERE time >= NOW() - INTERVAL 24 HOUR
            AND league IS NOT NULL
            AND bookmaker = '22bet'
            GROUP BY league
            ORDER BY match_count DESC
            LIMIT 50
        """

        cursor.execute(query)
        leagues = cursor.fetchall()

        result = []
        for row in leagues:
            result.append({
                'name': row['league'],
                'match_count': row['match_count']
            })

        cursor.close()
        conn.close()

        return jsonify(result)

    except Exception as e:
        logger.error(f"❌ Error: {e}")
        return jsonify([]), 500


@app.route('/api/search')
def api_search():
    """Поиск матчей по названию"""
    try:
        query_text = request.args.get('q', '').strip()
        if not query_text or len(query_text) < 3:
            return jsonify([]), 200

        conn = get_connection()
        if not conn:
            return jsonify([]), 500

        cursor = conn.cursor()

        query = """
            SELECT DISTINCT event_name, league
            FROM anomalies
            WHERE bookmaker = '22bet'
            AND (event_name LIKE %s OR league LIKE %s)
            LIMIT 20
        """

        search_pattern = f"%{query_text}%"
        cursor.execute(query, (search_pattern, search_pattern))
        results = cursor.fetchall()

        formatted_results = []
        for row in results:
            formatted_results.append({
                'event_name': row['event_name'],
                'league': row.get('league', 'Unknown')
            })

        cursor.close()
        conn.close()

        return jsonify(formatted_results)

    except Exception as e:
        logger.error(f"❌ Error: {e}")
        return jsonify([]), 500


@app.route('/api/health')
def health_check():
    """Проверка состояния сервиса"""
    try:
        conn = get_connection()
        if conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.close()
            conn.close()
            return jsonify({
                'status': 'ok',
                'database': 'connected',
                'timestamp': datetime.now().isoformat()
            }), 200
        else:
            return jsonify({
                'status': 'error',
                'database': 'disconnected',
                'timestamp': datetime.now().isoformat()
            }), 500
    except Exception as e:
        return jsonify({
            'status': 'error',
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500

# ==================== ERROR HANDLERS ====================
@app.errorhandler(404)
def not_found(error):
    """Обработка 404 ошибок"""
    return jsonify({'error': 'Endpoint not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    """Обработка 500 ошибок"""
    logger.error(f"Internal error: {error}")
    return jsonify({'error': 'Internal server error'}), 500

# ==================== ЗАПУСК СЕРВЕРА ====================
if __name__ == '__main__':
    print("=" * 70)
    print("🚀 Inforadar Pro - Starting Flask Server")
    print("=" * 70)
    print(f"🌐 Main: http://localhost:5000/")
    print(f"🔴 Live: http://localhost:5000/live")
    print(f"⏰ Prematch: http://localhost:5000/prematch")
    print(f"📊 All anomalies: http://localhost:5000/anomalies_22bet")
    print(f"🔍 BetWatch: http://localhost:5000/betwatch")
    print("=" * 70)
    print("📡 API Endpoints:")
    print(f"   GET /api/anomalies_filtered?real_only=false&status=live")
    print(f"   GET /api/anomalies_22bet")
    print(f"   GET /api/match/<event_name>/full")
    print(f"   GET /api/match/<event_name>/anomalies")
    print(f"   GET /api/live_matches")
    print(f"   GET /api/stats")
    print(f"   GET /api/betwatch/signals")
    print(f"   GET /api/leagues")
    print(f"   GET /api/search?q=")
    print(f"   GET /api/health")
    print("=" * 70)

    # Проверка подключения к БД
    test_conn = get_connection()
    if test_conn:
        test_conn.close()
        print("✅ MySQL OK!")
    else:
        print("⚠️ MySQL connection failed!")
    print("=" * 70)

    # Запуск сервера
    app.run(host='0.0.0.0', port=5000, debug=True)
