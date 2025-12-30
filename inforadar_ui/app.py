from flask import Flask, render_template, jsonify, request, redirect, url_for
import pymysql
from datetime import datetime, timedelta
import os

from dotenv import load_dotenv
from pathlib import Path
# Load .env (current dir and project root)
load_dotenv(Path(__file__).resolve().parent / '.env')
load_dotenv(Path(__file__).resolve().parents[1] / '.env')

import logging
import json
import hashlib
from urllib.parse import unquote, quote  # decode/encode URL segments

# ============================================================
# LOGGING CONFIGURATION
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

logger = logging.getLogger(__name__)

# ============================================================
# FLASK APP INITIALIZATION
# ============================================================
app = Flask(__name__)

# ============================================================
# DATABASE CONFIGURATION
# ============================================================
def _env(name: str, default: str = "") -> str:
    v = os.getenv(name, default)
    return v.strip() if isinstance(v, str) else v

DB_CONFIG = {
    "host": _env("MYSQL_HOST", "localhost"),
    "user": _env("MYSQL_USER", "root"),
    "password": _env("MYSQL_PASSWORD", ""),
    "database": _env("MYSQL_DATABASE", "inforadar"),
    "port": int(_env("MYSQL_PORT", "3306") or 3306),
    "charset": "utf8mb4",
}

# ============================================================
# DATABASE CONNECTION
# ============================================================
def get_connection():
    """Создать MySQL подключение"""
    try:
        # PyMySQL encodes the password as latin-1 internally; if MYSQL_PASSWORD contains
        # non-latin chars, it crashes with: "latin-1 codec can't encode characters...".
        # Workaround: pass password as bytes (utf-8) when needed.
        cfg = dict(DB_CONFIG)
        pwd = cfg.get("password")
        if isinstance(pwd, str):
            try:
                pwd.encode("latin-1")
            except UnicodeEncodeError:
                cfg["password"] = pwd.encode("utf-8")

        return pymysql.connect(**cfg, cursorclass=pymysql.cursors.DictCursor, autocommit=True, use_unicode=True)
    except Exception as e:
        logger.error(f"MySQL connection error: {e}")
        return None

# ============================================================
# UTILITY FUNCTIONS
# ============================================================
def str_to_bool(value):
    """Преобразовать строку в bool"""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ('true', '1', 'yes', 'on')
    return False

def format_datetime(dt):
    """Форматировать datetime"""
    if dt:
        return dt.strftime('%Y-%m-%d %H:%M:%S')
    return None

def calculate_severity(change_pct):
    """Вычислить severity аномалии"""
    abs_change = abs(change_pct)
    if abs_change >= 10:
        return 'critical'
    elif abs_change >= 5:
        return 'important'
    else:
        return 'moderate'

# ============================================================
# HTML PAGES ROUTES
# ============================================================
@app.route('/')
def index():
    """Главная страница - live odds"""
    return render_template('liveodds.html')

@app.route('/live')
def live_page():
    """Страница LIVE"""
    return render_template('liveodds.html')

@app.route('/prematch')
def prematch_page():
    """Страница PREMATCH"""
    return render_template('prematchodds.html')


# Backward compatible route (older UI links used /prematch_event/<id>)
@app.route('/prematch_event/<int:event_id>')
def prematch_event_page(event_id: int):
    """Redirect to match detail by event_id."""
    try:
        conn = get_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT event_name FROM odds_22bet WHERE event_id=%s ORDER BY updated_at DESC LIMIT 1",
                (event_id,),
            )
            row = cursor.fetchone()
        conn.close()
        if not row:
            return jsonify({"error": "Event not found"}), 404

        event_name = row.get("event_name") or ""
        return redirect(url_for('match_detail', eventname=quote(event_name, safe='')))
    except Exception as e:
        logging.exception("Error in prematch_event_page")
        return jsonify({"error": str(e)}), 500

@app.route('/anomalies22bet')
def anomalies_22bet_page():
    """Страница аномалий 22BET"""
    return render_template('anomalies_22bet.html')

@app.route('/betwatch')
def betwatch_page():
    """Страница BetWatch"""
    return render_template('betwatch.html')

@app.route('/match/<path:eventname>')
def match_detail(eventname):
    """
    ИСПРАВЛЕНО: Страница деталей матча с графиками
    """
    # Декодируем название события из URL
    decoded_name = unquote(eventname)

    # Получаем информацию о лиге из базы
    league = "Unknown League"
    try:
        conn = get_connection()
        if conn:
            cursor = conn.cursor()
            query = """
                SELECT league, sport 
                FROM odds_22bet 
                WHERE event_name = %s 
                LIMIT 1
            """
            cursor.execute(query, (decoded_name,))
            result = cursor.fetchone()
            cursor.close()
            conn.close()

            if result:
                league = result.get('league', 'Unknown League')
    except Exception as e:
        logger.error(f"Error fetching league info: {e}")

    return render_template('match_detail.html', 
                         event_name=decoded_name, 
                         league=league)

# ============================================================
# 22BET ODDS API ROUTES
# ============================================================
@app.route('/api/odds/prematch')
def api_odds_prematch():
    """API: Получить prematch коэффициенты 22bet из таблицы odds_22bet"""
    try:
        limit = int(request.args.get('limit', 500))
        limit = max(1, min(limit, 5000))
        sport = request.args.get('sport', '').strip()

        conn = get_connection()
        if not conn:
            return jsonify({'success': False, 'error': 'Database connection failed'}), 500

        cursor = conn.cursor()

        # ИСПРАВЛЕНО: Используем правильные названия колонок с подчёркиваниями
        query = """
            SELECT event_name, sport, league, market_type, odd_1, odd_x, odd_2,
                   updated_at, match_time, liquidity_level, is_suspicious
            FROM odds_22bet
            WHERE status = 'active'
        """
        params = []

        if sport:
            query += " AND sport = %s"
            params.append(sport)

        query += " AND match_time IS NOT NULL"

        query += " ORDER BY match_time ASC, updated_at DESC LIMIT %s"
        params.append(limit)

        cursor.execute(query, params)
        odds = cursor.fetchall()

        result = []
        for row in odds:
            result.append({
                'eventname': row['event_name'],
                'sport': row.get('sport', 'N/A'),
                'league': row.get('league', 'Unknown League'),
                'markettype': row.get('market_type', '1X2'),
                'odd1': float(row['odd_1']) if row['odd_1'] else None,
                'oddx': float(row['odd_x']) if row['odd_x'] else None,
                'odd2': float(row['odd_2']) if row['odd_2'] else None,
                'updatedat': format_datetime(row.get('updated_at')),
                'matchtime': format_datetime(row.get('match_time')),
                'liquidity': row.get('liquidity_level', 'low'),
                'suspicious': bool(row.get('is_suspicious', 0))
            })

        cursor.close()
        conn.close()

        logger.info(f"Returned {len(result)} prematch odds")
        return jsonify({
            'success': True,
            'count': len(result),
            'data': result
        })

    except Exception as e:
        logger.error(f"Error in api_odds_prematch: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/odds/live')
def api_odds_live():
    """API: Получить live коэффициенты 22bet"""
    try:
        limit = int(request.args.get('limit', 100))
        sport = request.args.get('sport', '').strip()

        conn = get_connection()
        if not conn:
            return jsonify({'success': False, 'error': 'Database connection failed'}), 500

        cursor = conn.cursor()

        query = """
            SELECT DISTINCT
                lm.eventname, lm.sport, lm.league,
                oh.homeodd AS odd1, oh.drawodd AS oddx, oh.awayodd AS odd2,
                lm.updatedat
            FROM livematches lm
            LEFT JOIN (
                SELECT matchid, homeodd, drawodd, awayodd, timestamp,
                       ROW_NUMBER() OVER (PARTITION BY matchid ORDER BY timestamp DESC) as rn
                FROM oddsfullhistory
                WHERE islive = 1
            ) oh ON lm.eventid = oh.matchid AND oh.rn = 1
            WHERE lm.status = 'live' AND lm.bookmaker = '22bet'
        """
        params = []

        if sport:
            query += " AND lm.sport = %s"
            params.append(sport)

        query += " ORDER BY lm.updatedat DESC LIMIT %s"
        params.append(limit)

        cursor.execute(query, params)
        odds = cursor.fetchall()

        result = []
        for row in odds:
            result.append({
                'eventname': row['eventname'],
                'sport': row.get('sport', 'Football'),
                'league': row.get('league', 'Unknown League'),
                'markettype': '1X2',
                'odd1': float(row['odd1']) if row['odd1'] else None,
                'oddx': float(row['oddx']) if row['oddx'] else None,
                'odd2': float(row['odd2']) if row['odd2'] else None,
                'updatedat': format_datetime(row.get('updatedat'))
            })

        cursor.close()
        conn.close()

        logger.info(f"Returned {len(result)} live odds")
        return jsonify({
            'success': True,
            'count': len(result),
            'data': result
        })

    except Exception as e:
        logger.error(f"Error in api_odds_live: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/odds/sports')
def api_odds_sports():
    """API: Список видов спорта из odds_22bet"""
    try:
        conn = get_connection()
        if not conn:
            return jsonify({'success': False, 'error': 'Database connection failed'}), 500

        cursor = conn.cursor()
        cursor.execute("""
            SELECT DISTINCT sport, COUNT(*) as count
            FROM odds_22bet
            WHERE status = 'active' AND sport IS NOT NULL
            GROUP BY sport
            ORDER BY count DESC
        """)
        sports = cursor.fetchall()

        result = []
        for row in sports:
            result.append({
                'name': row['sport'],
                'count': row['count']
            })

        cursor.close()
        conn.close()

        return jsonify({
            'success': True,
            'count': len(result),
            'data': result
        })

    except Exception as e:
        logger.error(f"Error in api_odds_sports: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# ============================================================
# ANOMALIES API ROUTES
# ============================================================

# ============================================================
# MATCH DETAILS API ROUTES
# ============================================================
@app.route('/api/match/<path:eventname>/full')
def api_match_full(eventname):
    """
    ДОБАВЛЕНО: API для полной информации о матче с историей коэффициентов
    Возвращает данные для графиков 1X2, тоталов и фор
    """
    try:
        decoded_name = unquote(eventname)
        conn = get_connection()

        if not conn:
            return jsonify({
                'success': False,
                'error': 'Database connection failed'
            }), 500

        cursor = conn.cursor()

        # Получаем историю коэффициентов для этого матча
        query = """
            SELECT 
                event_name,
                league,
                sport,
                market_type,
                odd_1,
                odd_x,
                odd_2,
                updated_at,
                is_suspicious
            FROM odds_22bet 
            WHERE event_name = %s 
            ORDER BY updated_at ASC
            LIMIT 1000
        """
        cursor.execute(query, (decoded_name,))
        odds_history = cursor.fetchall()
        cursor.close()
        conn.close()

        if not odds_history:
            return jsonify({
                'success': False,
                'error': 'Match not found',
                'message': f'No data found for event: {decoded_name}'
            }), 404

        # Форматируем данные для графиков
        response_data = {
            'success': True,
            'event': decoded_name,
            'league': odds_history[0].get('league', 'Unknown'),
            'sport': odds_history[0].get('sport', 'Football'),
            'odds': []
        }

        # Добавляем историю коэффициентов 1X2
        for record in odds_history:
            response_data['odds'].append({
                'time': record['updated_at'].isoformat() if record['updated_at'] else None,
                'updatedat': record['updated_at'].isoformat() if record['updated_at'] else None,
                'odd1': float(record['odd_1']) if record['odd_1'] else None,
                'oddx': float(record['odd_x']) if record['odd_x'] else None,
                'odd2': float(record['odd_2']) if record['odd_2'] else None,
                'suspicious': record.get('is_suspicious', False)
            })

        return jsonify(response_data)

    except Exception as e:
        logger.error(f"Error in api_match_full: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/match/<event_name>/full')
def match_full_data(event_name):
    """API: Полная история матча"""
    try:
        conn = get_connection()
        if not conn:
            return jsonify({'error': 'Database connection failed'}), 500

        cursor = conn.cursor()

        query = """
            SELECT timestamp, odds1x2home, odds1x2draw, odds1x2away,
                   oddstotalover, oddstotalunder, oddshandicaphome, oddshandicapaway,
                   minute, scorehome, scoreaway
            FROM livematches
            WHERE eventname = %s
            ORDER BY timestamp ASC
        """

        cursor.execute(query, (event_name,))
        history = cursor.fetchall()

        if not history:
            cursor.close()
            conn.close()
            return jsonify({'error': 'Match not found'}), 404

        result = {
            'eventname': event_name,
            'history': []
        }

        for row in history:
            result['history'].append({
                'timestamp': row['timestamp'].isoformat() if row['timestamp'] else None,
                'odds1x2': {
                    'home': float(row['odds1x2home']) if row['odds1x2home'] else None,
                    'draw': float(row['odds1x2draw']) if row['odds1x2draw'] else None,
                    'away': float(row['odds1x2away']) if row['odds1x2away'] else None
                },
                'oddstotal': {
                    'over': float(row['oddstotalover']) if row['oddstotalover'] else None,
                    'under': float(row['oddstotalunder']) if row['oddstotalunder'] else None
                },
                'oddshandicap': {
                    'home': float(row['oddshandicaphome']) if row['oddshandicaphome'] else None,
                    'away': float(row['oddshandicapaway']) if row['oddshandicapaway'] else None
                },
                'minute': row.get('minute'),
                'score': {
                    'home': row.get('scorehome'),
                    'away': row.get('scoreaway')
                }
            })

        cursor.close()
        conn.close()

        return jsonify(result)

    except Exception as e:
        logger.error(f"Error in match_full_data: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/match/<event_name>/anomalies')
def match_anomalies(event_name):
    """API: Аномалии конкретного матча"""
    try:
        conn = get_connection()
        if not conn:
            return jsonify([]), 500

        cursor = conn.cursor()

        query = """
            SELECT market, outcome, beforeodds, afterodds, changepct, severity, time
            FROM anomalies
            WHERE eventname = %s AND bookmaker = '22bet'
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
                'beforeodds': float(row['beforeodds']) if row['beforeodds'] else None,
                'afterodds': float(row['afterodds']) if row['afterodds'] else None,
                'changepct': float(row['changepct']),
                'severity': row['severity'],
                'time': format_datetime(row['time'])
            })

        cursor.close()
        conn.close()

        return jsonify(result)

    except Exception as e:
        logger.error(f"Error: {e}")
        return jsonify([]), 500

# ============================================================
# LIVE MATCHES API ROUTES
# ============================================================
@app.route('/api/livematches')
def api_livematches():
    """API: Список live матчей"""
    try:
        conn = get_connection()
        if not conn:
            return jsonify([]), 500

        cursor = conn.cursor()

        query = """
            SELECT DISTINCT eventname, league, minute, scorehome, scoreaway,
                   MAX(timestamp) as lastupdate
            FROM livematches
            WHERE timestamp >= NOW() - INTERVAL 1 HOUR
            GROUP BY eventname, league, minute, scorehome, scoreaway
            ORDER BY lastupdate DESC
        """

        cursor.execute(query)
        matches = cursor.fetchall()

        result = []
        for row in matches:
            result.append({
                'eventname': row['eventname'],
                'league': row.get('league', 'Unknown'),
                'minute': row.get('minute'),
                'score': f"{row.get('scorehome', 0)}:{row.get('scoreaway', 0)}",
                'lastupdate': format_datetime(row['lastupdate'])
            })

        cursor.close()
        conn.close()

        return jsonify(result)

    except Exception as e:
        logger.error(f"Error: {e}")
        return jsonify([]), 500

# ============================================================
# STATISTICS API ROUTES
# ============================================================
@app.route('/api/stats')
def api_stats():
    """API: Общая статистика"""
    try:
        conn = get_connection()
        if not conn:
            return jsonify({
                'totalanomalies': 0,
                'critical': 0,
                'important': 0,
                'moderate': 0,
                'houranomalies': 0,
                'livematches': 0
            }), 200

        cursor = conn.cursor()

        # Статистика за 24 часа
        cursor.execute("""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN severity = 'critical' THEN 1 ELSE 0 END) as critical,
                SUM(CASE WHEN severity = 'important' THEN 1 ELSE 0 END) as important,
                SUM(CASE WHEN severity = 'moderate' THEN 1 ELSE 0 END) as moderate
            FROM anomalies
            WHERE time >= NOW() - INTERVAL 24 HOUR AND bookmaker = '22bet'
        """)
        stats_24h = cursor.fetchone()

        # Статистика за 1 час
        cursor.execute("""
            SELECT COUNT(*) as count
            FROM anomalies
            WHERE time >= NOW() - INTERVAL 1 HOUR AND bookmaker = '22bet'
        """)
        stats_1h = cursor.fetchone()

        # Количество live матчей
        cursor.execute("""
            SELECT COUNT(DISTINCT eventname) as count
            FROM livematches
            WHERE timestamp >= NOW() - INTERVAL 10 MINUTE
        """)
        live_count = cursor.fetchone()

        cursor.close()
        conn.close()

        return jsonify({
            'totalanomalies': stats_24h['total'] or 0,
            'critical': stats_24h['critical'] or 0,
            'important': stats_24h['important'] or 0,
            'moderate': stats_24h['moderate'] or 0,
            'houranomalies': stats_1h['count'] or 0,
            'livematches': live_count['count'] or 0
        })

    except Exception as e:
        logger.error(f"Error in api_stats: {e}")
        return jsonify({
            'totalanomalies': 0,
            'critical': 0,
            'important': 0,
            'moderate': 0,
            'houranomalies': 0,
            'livematches': 0
        }), 200

# ============================================================
# BETWATCH API ROUTES
# ============================================================
@app.route('/api/betwatch/signals')
def betwatch_signals():
    """API: BetWatch сигналы"""
    try:
        conn = get_connection()
        if not conn:
            return jsonify([]), 500

        cursor = conn.cursor()

        query = """
            SELECT eventname, league, market, outcome, beforeodds, afterodds, 
                   changepct, severity, time, islive, matchminute
            FROM anomalies
            WHERE time >= NOW() - INTERVAL 1 HOUR
              AND ABS(changepct) >= 5
              AND bookmaker = '22bet'
            ORDER BY ABS(changepct) DESC
            LIMIT 50
        """

        cursor.execute(query)
        signals = cursor.fetchall()

        result = []
        for row in signals:
            result.append({
                'eventname': row['eventname'],
                'league': row.get('league', 'Unknown'),
                'market': row['market'],
                'outcome': row['outcome'],
                'beforeodds': float(row['beforeodds']) if row['beforeodds'] else None,
                'afterodds': float(row['afterodds']) if row['afterodds'] else None,
                'changepct': float(row['changepct']),
                'severity': row['severity'],
                'time': format_datetime(row['time']),
                'islive': bool(row.get('islive', False)),
                'matchminute': row.get('matchminute')
            })

        cursor.close()
        conn.close()

        return jsonify(result)

    except Exception as e:
        logger.error(f"Error: {e}")
        return jsonify([]), 500

# ============================================================
# LEAGUES API ROUTES
# ============================================================
@app.route('/api/leagues')
def api_leagues():
    """API: Список лиг"""
    try:
        conn = get_connection()
        if not conn:
            return jsonify([]), 500

        cursor = conn.cursor()

        query = """
            SELECT DISTINCT league, COUNT(*) as matchcount
            FROM anomalies
            WHERE time >= NOW() - INTERVAL 24 HOUR
              AND league IS NOT NULL
              AND bookmaker = '22bet'
            GROUP BY league
            ORDER BY matchcount DESC
            LIMIT 50
        """

        cursor.execute(query)
        leagues = cursor.fetchall()

        result = []
        for row in leagues:
            result.append({
                'name': row['league'],
                'matchcount': row['matchcount']
            })

        cursor.close()
        conn.close()

        return jsonify(result)

    except Exception as e:
        logger.error(f"Error: {e}")
        return jsonify([]), 500

# ============================================================
# SEARCH API ROUTES
# ============================================================
@app.route('/api/search')
def api_search():
    """API: Поиск матчей"""
    try:
        query_text = request.args.get('q', '').strip()

        if not query_text or len(query_text) < 3:
            return jsonify([]), 200

        conn = get_connection()
        if not conn:
            return jsonify([]), 500

        cursor = conn.cursor()

        query = """
            SELECT DISTINCT eventname, league
            FROM anomalies
            WHERE bookmaker = '22bet'
              AND (eventname LIKE %s OR league LIKE %s)
            LIMIT 20
        """

        search_pattern = f"%{query_text}%"
        cursor.execute(query, (search_pattern, search_pattern))
        results = cursor.fetchall()

        formatted_results = []
        for row in results:
            formatted_results.append({
                'eventname': row['eventname'],
                'league': row.get('league', 'Unknown')
            })

        cursor.close()
        conn.close()

        return jsonify(formatted_results)

    except Exception as e:
        logger.error(f"Error: {e}")
        return jsonify([]), 500

# ============================================================
# HEALTH CHECK
# ============================================================
@app.route('/api/health')
def health_check():
    """API: Health check"""
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

# ============================================================
# ERROR HANDLERS
# ============================================================
@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Endpoint not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"Internal error: {error}")
    return jsonify({'error': 'Internal server error'}), 500

# ============================================================
# MAIN ENTRY POINT
# ============================================================
if __name__ == '__main__':
    print("=" * 70)
    print("Inforadar Pro - Starting Flask Server")
    print("=" * 70)
    print(f"→ Main: http://localhost:5000")
    print(f"→ Live: http://localhost:5000/live")
    print(f"→ Prematch: http://localhost:5000/prematch")
    print(f"→ All anomalies: http://localhost:5000/anomalies22bet")
    print(f"→ BetWatch: http://localhost:5000/betwatch")
    print("=" * 70)
    print("API Endpoints:")
    print(f"→ GET /api/odds/prematch - 22bet prematch odds")
    print(f"→ GET /api/odds/live - 22bet live odds")
    print(f"→ GET /api/odds/sports - Available sports list")
    print(f"→ GET /api/anomalies/filtered?realonly=false&status=live")
    print(f"→ GET /api/anomalies/22bet")
    print(f"→ GET /api/match/<event_name>/full")
    print(f"→ GET /api/match/<event_name>/anomalies")
    print(f"→ GET /api/livematches")
    print(f"→ GET /api/stats")
    print(f"→ GET /api/betwatch/signals")
    print(f"→ GET /api/leagues")
    print(f"→ GET /api/search?q=")
    print(f"→ GET /api/health")
    print("=" * 70)

    # Проверка подключения к БД
    test_conn = get_connection()
    if test_conn:
        test_conn.close()
        print("✅ MySQL OK!")
    else:
        print("❌ MySQL connection failed!")
    print("=" * 70)

    app.run(host='0.0.0.0', port=5000, debug=True)