from flask import Flask, render_template, jsonify, request, render_template_string
import pymysql
from datetime import datetime
from collections import defaultdict

app = Flask(__name__)

# ====== DB SETTINGS ======
DB_HOST = "mysql_inforadar"  # ✅ Docker имя сервиса
DB_PORT = 3306  # ✅ Внутренний порт контейнера
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
# 22BET ANOMALIES - ГЛАВНЫЙ ДАШБОРД
# ===========================================================

@app.route("/anomalies_22bet")
def anomalies_22bet_page():
    """Страница аномалий 22bet"""
    conn = get_connection()
    
    if not conn:
        return render_template_string("""
            <!DOCTYPE html>
            <html>
            <head>
                <title>Ошибка подключения</title>
                <style>
                    body { font-family: Arial; padding: 40px; background: #f5f5f5; }
                    .error { background: white; padding: 30px; border-radius: 8px; 
                             border-left: 4px solid #dc2626; max-width: 600px; margin: 0 auto; }
                    h1 { color: #dc2626; margin-top: 0; }
                </style>
            </head>
            <body>
                <div class="error">
                    <h1>❌ Ошибка подключения к MySQL</h1>
                    <p>Проверьте что Docker контейнер mysql_inforadar запущен.</p>
                </div>
            </body>
            </html>
        """)
    
    try:
        with conn.cursor() as cursor:
            # Проверяем есть ли таблица
            cursor.execute("SHOW TABLES LIKE 'anomalies_22bet'")
            if not cursor.fetchone():
                return render_template_string("""
                    <!DOCTYPE html>
                    <html>
                    <head><title>Таблица не найдена</title></head>
                    <body style="font-family: Arial; padding: 40px;">
                        <h1>⚠️ Таблица anomalies_22bet не существует</h1>
                        <p>Используйте Playwright для добавления данных.</p>
                    </body>
                    </html>
                """)
            
            cursor.execute("""
                SELECT
                    id,
                    event_name,
                    sport,
                    league,
                    anomaly_type,
                    market_type,
                    before_value,
                    after_value,
                    diff_pct,
                    status,
                    detected_at,
                    comment
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
                    a.id,
                    a.match_id,
                    a.anomaly_type,
                    a.before_value,
                    a.after_value,
                    a.diff_pct,
                    a.created_at,
                    a.comment,
                    m.sport,
                    m.league,
                    m.home_team,
                    m.away_team
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
    test_data = [
        {
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
        }
    ]
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
                    e.event_id,
                    e.sport_key,
                    e.sport_title,
                    e.commence_time,
                    e.home_team,
                    e.away_team,
                    e.completed
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
                    o.event_id,
                    o.bookmaker_title,
                    o.market_key,
                    o.outcome_name,
                    o.outcome_price,
                    o.last_update
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
    print(f"📈 22bet Dashboard: http://localhost:5000/anomalies_22bet")
    print(f"📊 All Anomalies: http://localhost:5000/anomalies")
    app.run(host="0.0.0.0", port=5000, debug=True)
