import os
from datetime import datetime, timedelta
from flask import Flask, jsonify, request, render_template
from flask_cors import CORS
import MySQLdb
import MySQLdb.cursors

def get_db():
    return MySQLdb.connect(
        host=os.getenv("MYSQL_HOST", "mysql"),
        user=os.getenv("MYSQL_USER", "root"),
        passwd=os.getenv("MYSQL_PASSWORD", "root"),
        db=os.getenv("MYSQL_DATABASE", "inforadar"),
        charset="utf8mb4",
        cursorclass=MySQLdb.cursors.DictCursor,
    )

app = Flask(__name__, template_folder="templates", static_folder="static")
CORS(app)

# ---------- HELPER ----------
def paging():
    try:
        page = max(1, int(request.args.get("page", 1)))
        per_page = max(1, min(200, int(request.args.get("per_page", 50))))
    except ValueError:
        page, per_page = 1, 50
    return page, per_page

# ---------- PAGES ----------
@app.route("/")
def index():
    return render_template("index.html")

# ---------- API ----------
@app.route("/api/matches")
def api_matches():
    """
    Параметры:
      league, team, since_minutes, page, per_page
    """
    league = request.args.get("league")
    team = request.args.get("team")
    since_minutes = int(request.args.get("since_minutes", 180))
    page, per_page = paging()
    offset = (page - 1) * per_page

    dt_from = datetime.utcnow() - timedelta(minutes=since_minutes)

    where = ["m.start_time >= %s"]
    params = [dt_from]

    if league:
        where.append("m.league LIKE %s")
        params.append(f"%{league}%")
    if team:
        where.append("(m.team_home LIKE %s OR m.team_away LIKE %s)")
        params += [f"%{team}%", f"%{team}%"]

    where_sql = " AND ".join(where)

    sql = f"""
    SELECT
      m.id, m.league, m.team_home, m.team_away, m.start_time,
      o.bookmaker, o.market, o.outcome, o.odds, o.updated_at
    FROM matches m
    LEFT JOIN odds o ON o.match_id = m.id
    WHERE {where_sql}
    ORDER BY m.start_time ASC, o.updated_at DESC
    LIMIT %s OFFSET %s
    """
    params += [per_page, offset]

    db = get_db()
    with db as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        rows = cur.fetchall()

        # total
        cur.execute(f"SELECT COUNT(*) AS cnt FROM matches m WHERE {where_sql}", params[:-2])
        total = cur.fetchone()["cnt"]

    return jsonify({
        "page": page, "per_page": per_page, "total": total, "items": rows
    })

@app.route("/api/markets/<int:match_id>")
def api_markets(match_id: int):
    db = get_db()
    sql = """
    SELECT market, outcome, bookmaker, odds, updated_at
    FROM odds
    WHERE match_id=%s
    ORDER BY market, outcome, updated_at DESC
    """
    with db as conn:
        cur = conn.cursor()
        cur.execute(sql, [match_id])
        rows = cur.fetchall()
    return jsonify(rows)

@app.route("/api/stats")
def api_stats():
    db = get_db()
    with db as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS matches_cnt FROM matches")
        matches_cnt = cur.fetchone()["matches_cnt"]

        cur.execute("SELECT COUNT(*) AS odds_cnt FROM odds")
        odds_cnt = cur.fetchone()["odds_cnt"]

        cur.execute("SELECT MAX(updated_at) AS last_update FROM odds")
        last_update = cur.fetchone()["last_update"]

    return jsonify({
        "matches": matches_cnt,
        "odds": odds_cnt,
        "last_update_utc": None if not last_update else last_update.strftime("%Y-%m-%d %H:%M:%S")
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
