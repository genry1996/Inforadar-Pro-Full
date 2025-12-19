from flask import Flask, render_template, jsonify, request, render_template_string
import pymysql
from datetime import datetime, timedelta
from collections import defaultdict

app = Flask(__name__)

# ====== DB SETTINGS ======
DB_HOST = "mysql_inforadar"  # ✅ Docker имя сервиса
DB_PORT = 3306
DB_USER = "root"
DB_PASSWORD = "ryban8991!"
DB_NAME = "inforadar"

def get_connection():
    """Подключение к MySQL через pymysql"""
    try:
        conn = pymysql.connect(
            host=DB_HOST,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME,
            port=DB_PORT,
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=True,
        )
        print(f"✅ Connected to MySQL: {DB_HOST}:{DB_PORT}/{DB_NAME}")
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
        return "только что"
    if seconds < 3600:
        return f"{int(seconds // 60)} мин назад"
    if seconds < 86400:
        return f"{int(seconds // 3600)} ч назад"
    if seconds < 604800:
        return f"{int(seconds // 86400)} дн назад"
    return value.strftime("%Y-%m-%d %H:%M")

# ===========================================================
# 🆕 BETWATCH DASHBOARD
# ===========================================================

@app.route('/betwatch')
def betwatch_dashboard():
    """Betwatch Advanced Detector Dashboard"""
    return render_template('betwatch.html')

@app.route('/api/betwatch/signals')
def api_betwatch_signals():
    """API: Получить сигналы Betwatch с фильтрами"""
    
    # Параметры фильтрации
    signal_type = request.args.get('type', 'all')
    hours = int(request.args.get('hours', 24))
    limit = int(request.args.get('limit', 50))
    
    conn = get_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500
    
    try:
        with conn.cursor() as cursor:
            # Базовый запрос
            query = """
                SELECT 
                    id,
                    signal_type,
                    event_name,
                    league,
                    market_type,
                    betfair_odd,
                    bookmaker_odd,
                    bookmaker_name,
                    money_volume,
                    total_market_volume,
                    flow_percent,
                    old_odd,
                    new_odd,
                    odd_drop_percent,
                    is_live,
                    match_time,
                    detected_at
                FROM betwatch_signals
                WHERE detected_at >= NOW() - INTERVAL %s HOUR
            """
            params = [hours]
            
            # Фильтр по типу
            if signal_type != 'all':
                query += " AND signal_type = %s"
                params.append(signal_type)
            
            query += " ORDER BY detected_at DESC LIMIT %s"
            params.append(limit)
            
            cursor.execute(query, params)
            signals = cursor.fetchall()
            
            # Форматируем даты
            for signal in signals:
                if signal['detected_at']:
                    signal['detected_at'] = signal['detected_at'].strftime('%Y-%m-%d %H:%M:%S')
            
            return jsonify({
                "success": True,
                "count": len(signals),
                "signals": signals
            })
    
    except Exception as e:
        print(f"❌ Error in api_betwatch_signals: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@app.route('/api/betwatch/stats')
def api_betwatch_stats():
    """API: Статистика сигналов Betwatch"""
    
    hours = int(request.args.get('hours', 24))
    
    conn = get_connection()
    if not conn:
        return jsonify({"error": "Database connection failed"}), 500
    
    try:
        with conn.cursor() as cursor:
            # Общее количество сигналов
            cursor.execute("""
                SELECT COUNT(*) as total
                FROM betwatch_signals
                WHERE detected_at >= NOW() - INTERVAL %s HOUR
            """, (hours,))
            total = cursor.fetchone()['total']
            
            # По типам
            cursor.execute("""
                SELECT 
                    signal_type,
                    COUNT(*) as count
                FROM betwatch_signals
                WHERE detected_at >= NOW() - INTERVAL %s HOUR
                GROUP BY signal_type
            """, (hours,))
            by_type = cursor.fetchall()
            
            # Топ событий
            cursor.execute("""
                SELECT 
                    event_name,
                    COUNT(*) as count
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
            avg_flow = result['avg_flow'] if result else 0
            
            return jsonify({
                "success": True,
                "total": total,
                "by_type": by_type,
                "top_events": top_events,
                "avg_flow": round(avg_flow, 2) if avg_flow else 0
            })
    
    except Exception as e:
        print(f"❌ Error in api_betwatch_stats: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

# ===========================================================
# ✅ ADVANCED MONITOR - ГЛАВНЫЙ ИНТЕРФЕЙС
# ===========================================================
@app.route("/advanced")
def advanced_monitor():
    """Продвинутый мониторинг с вкладками"""
    return render_template("advanced_monitor.html")

# ===========================================================
# ✅ EXCHANGE DASHBOARD - ДЛЯ PLAYWRIGHT ПАРСЕРА
# ===========================================================
@app.route('/exchange')
def exchange_dashboard():
    """Exchange Dashboard для Playwright парсера"""
    return render_template('dashboard_filter.html')

@app.route('/api/exchange/anomalies')
def api_exchange_anomalies():
    """API для Exchange аномалий - возвращает JSON данные"""
    conn = get_connection()
    if not conn:
        return jsonify({'error': 'DB connection failed'}), 500
    
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT 
                    id, market_id, selection_id, event_name, sport,
                    anomaly_type, severity, volume_before, volume_current,
                    volume_change_pct, price_before, price_current,
                    price_change_pct, details, detected_at
                FROM exchange_anomalies
                ORDER BY detected_at DESC
                LIMIT 100
            """)
            rows = cursor.fetchall()
            print(f"✅ Loaded {len(rows)} exchange anomalies")
    except Exception as e:
        print(f"❌ Error in api_exchange_anomalies: {e}")
        return jsonify([])
    finally:
        conn.close()
    
    # Преобразуем в нужный формат
    anomalies = []
    for row in rows:
        anomalies.append({
            'id': row['id'],
            'market_id': row.get('market_id'),
            'selection_id': row.get('selection_id'),
            'event_name': row.get('event_name', 'Unknown Event'),
            'sport': row.get('sport', 'Unknown'),
            'anomaly_type': row.get('anomaly_type', 'UNKNOWN'),
            'severity': row.get('severity', 'medium'),
            'volume_before': float(row['volume_before']) if row.get('volume_before') else 0,
            'volume_current': float(row['volume_current']) if row.get('volume_current') else 0,
            'volume_change_pct': float(row['volume_change_pct']) if row.get('volume_change_pct') else 0,
            'price_before': float(row['price_before']) if row.get('price_before') else 0,
            'price_current': float(row['price_current']) if row.get('price_current') else 0,
            'price_change_pct': float(row['price_change_pct']) if row.get('price_change_pct') else 0,
            'details': row.get('details', ''),
            'timestamp': row['detected_at'].isoformat() if row.get('detected_at') else None
        })
    
    return jsonify(anomalies)

# ===========================================================
# 22BET ANOMALIES - ГЛАВНЫЙ ДАШБОРД
# ===========================================================
@app.route("/anomalies_22bet")
def anomalies_22bet_page():
    """Страница аномалий 22bet"""
    conn = get_connection()
    if not conn:
        return render_template_string("""
            <h1>❌ Ошибка подключения к MySQL</h1>
            <p>Проверьте что Docker контейнер mysql_inforadar запущен.</p>
            <code>docker ps | grep mysql_inforadar</code>
        """)
    
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT
                    id, event_name, sport, league, anomaly_type,
                    market_type, before_value, after_value, diff_pct,
                    status, detected_at, comment
                FROM anomalies_22bet
                ORDER BY detected_at DESC, id DESC
                LIMIT 200
            """)
            rows = cursor.fetchall()
            print(f"✅ Loaded {len(rows)} anomalies from anomalies_22bet")
    except Exception as e:
        print(f"❌ Error in anomalies_22bet: {e}")
        import traceback
        traceback.print_exc()
        return f"Ошибка при получении данных: {e}"
    finally:
        conn.close()
    
    def fmt_odd(val):
        if val is None:
            return None
        try:
            f = float(val)
        except (TypeError, ValueError):
            return str(val)
        s = f"{f:.3f}".rstrip("0").rstrip(".")
        return s
    
    anomalies = []
    for row in rows:
        row["old_odd"] = fmt_odd(row.get("before_value"))
        row["new_odd"] = fmt_odd(row.get("after_value"))
        row["change_percent"] = row.get("diff_pct")
        row["created_at"] = row.get("detected_at")
        anomalies.append(row)
    
    return render_template("anomalies_22bet.html", anomalies=anomalies)

# ===========================================================
# ОСТАЛЬНЫЕ МАРШРУТЫ
# ===========================================================

@app.route("/anomalies")
def anomalies_page():
    """Страница общих аномалий"""
    filter_type = request.args.get("type", "all")
    conn = get_connection()
    if not conn:
        return "Ошибка подключения к MySQL"
    
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT
                    a.id, a.match_id, a.anomaly_type, a.before_value,
                    a.after_value, a.diff_pct, a.created_at, a.comment,
                    m.sport, m.league, m.home_team, m.away_team
                FROM anomalies a
                LEFT JOIN matches m ON a.match_id = m.id
                ORDER BY a.created_at DESC, a.id DESC
                LIMIT 200
            """)
            rows = cursor.fetchall()
    finally:
        conn.close()
    
    def fmt_odd(val):
        if val is None:
            return None
        try:
            f = float(val)
        except (TypeError, ValueError):
            return str(val)
        s = f"{f:.3f}".rstrip("0").rstrip(".")
        return s
    
    anomalies = []
    for row in rows:
        row["before_value"] = fmt_odd(row.get("before_value"))
        row["after_value"] = fmt_odd(row.get("after_value"))
        diff_val = row.get("diff_pct")
        if diff_val is not None:
            try:
                row["diff_pct"] = float(diff_val)
            except (TypeError, ValueError):
                row["diff_pct"] = None
        anomalies.append(row)
    
    filtered = anomalies
    if filter_type == "spread":
        filtered = [a for a in anomalies if a.get("anomaly_type") == "ODDS_SPREAD"]
    elif filter_type == "live":
        filtered = [a for a in anomalies if "LIVE" in (a.get("anomaly_type") or "")]
    elif filter_type == "prematch":
        filtered = [a for a in anomalies if "LIVE" not in (a.get("anomaly_type") or "")]
    
    return render_template(
        "anomalies.html",
        anomalies=filtered,
        filter_type=filter_type,
        current_type=filter_type,
        total_pages=1,
        page=1,
    )

@app.route("/anomaly")
def anomalies_single_alias():
    return anomalies_page()

@app.route('/api/anomalies/test', methods=['GET'])
def api_anomalies_test():
    """API endpoint для Playwright тестов"""
    test_data = [{
        'id': 1,
        'event_name': 'Test Match 1',
        'sport': 'Football',
        'league': 'Premier League',
        'market_type': '1X2',
        'old_odd': 2.5,
        'new_odd': 1.8,
        'change_percent': -28,
        'anomaly_type': 'ODDS_DROP',
        'severity': 'high',
        'status': 'active',
        'created_at': '2 mins ago',
        'comment': 'Significant drop detected'
    }]
    return jsonify(test_data)

@app.route("/oddsapi/epl")
def oddsapi_epl():
    """The Odds API - EPL данные"""
    conn = get_connection()
    if not conn:
        return "Ошибка подключения к MySQL"
    
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT
                    e.event_id, e.sport_key, e.sport_title,
                    e.commence_time, e.home_team, e.away_team, e.completed
                FROM oddsapi_events e
                WHERE e.sport_key = 'soccer_epl'
                ORDER BY e.commence_time ASC
            """)
            rows_events = cursor.fetchall()
            
            if not rows_events:
                return render_template("oddsapi_epl.html", events=[])
            
            event_ids = [row["event_id"] for row in rows_events]
            placeholders = ", ".join(["%s"] * len(event_ids))
            
            sql_odds = f"""
                SELECT
                    o.event_id, o.bookmaker_title, o.market_key,
                    o.outcome_name, o.outcome_price, o.last_update
                FROM oddsapi_odds o
                WHERE o.event_id IN ({placeholders})
                  AND o.market_key = 'h2h'
                ORDER BY o.event_id, o.bookmaker_title, o.outcome_name
            """
            cursor.execute(sql_odds, event_ids)
            rows_odds = cursor.fetchall()
    except Exception as e:
        print(f"❌ Error in /oddsapi/epl: {e}")
        return "Ошибка при получении данных The Odds API"
    finally:
        if conn:
            conn.close()
    
    odds_by_event = defaultdict(list)
    for row in rows_odds:
        odds_by_event[row["event_id"]].append(row)
    
    events = []
    for ev in rows_events:
        ev_id = ev["event_id"]
        commence = ev["commence_time"]
        if isinstance(commence, datetime):
            commence_str = commence.strftime("%Y-%m-%d %H:%M")
        else:
            commence_str = str(commence)
        
        events.append({
            "event_id": ev_id,
            "sport_key": ev["sport_key"],
            "sport_title": ev.get("sport_title"),
            "commence_time": commence_str,
            "home_team": ev["home_team"],
            "away_team": ev["away_team"],
            "completed": ev["completed"],
            "odds": odds_by_event.get(ev_id, []),
        })
    
    return render_template("oddsapi_epl.html", events=events)

@app.route("/")
def index():
    """Главная страница"""
    return render_template("index.html")

@app.route("/metrics")
def metrics_stub():
    """Health check endpoint"""
    return "ok\n", 200, {"Content-Type": "text/plain; charset=utf-8"}

if __name__ == "__main__":
    print("🚀 Starting Inforadar Pro Flask Server...")
    print(f"🔗 MySQL: {DB_HOST}:{DB_PORT}/{DB_NAME}")
    print(f"🎯 Betwatch Dashboard: http://localhost:5000/betwatch")
    print(f"📈 22bet Dashboard: http://localhost:5000/anomalies_22bet")
    print(f"📊 Advanced Monitor: http://localhost:5000/advanced")
    print(f"📊 Exchange Dashboard: http://localhost:5000/exchange")
    app.run(host="0.0.0.0", port=5000, debug=True)
