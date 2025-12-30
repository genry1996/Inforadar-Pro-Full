from __future__ import annotations

import os
from flask import Blueprint, render_template, request
import pymysql

bp_fonbet = Blueprint("fonbet", __name__, url_prefix="/fonbet")


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name, default) or "").strip()


def get_db():
    # поддержка MYSQL_* (как у тебя в .env)
    host = _env("MYSQL_HOST") or _env("DB_HOST") or "127.0.0.1"
    user = _env("MYSQL_USER") or _env("DB_USER") or "root"
    password = _env("MYSQL_PASSWORD") or _env("DB_PASSWORD") or ""
    database = _env("MYSQL_DB") or _env("MYSQL_DATABASE") or _env("DB_NAME") or "inforadar"

    return pymysql.connect(
        host=host,
        user=user,
        password=password,
        database=database,
        charset="utf8mb4",
        autocommit=True,
        cursorclass=pymysql.cursors.DictCursor,
    )


@bp_fonbet.get("/")
def fonbet_index():
    # фильтры
    q = (request.args.get("q") or "").strip()
    hours = int(request.args.get("hours") or "12")
    limit = int(request.args.get("limit") or "200")

    sql = """
    SELECT
      e.event_id,
      e.league_name,
      e.team1, e.team2,
      FROM_UNIXTIME(e.start_ts) AS start_time,
      e.start_ts,
      e.updated_at
    FROM fonbet_events e
    WHERE e.start_ts IS NULL OR e.start_ts <= UNIX_TIMESTAMP(NOW()) + %s
    """
    params = [hours * 3600]

    if q:
        sql += " AND (e.team1 LIKE %s OR e.team2 LIKE %s OR e.league_name LIKE %s)"
        like = f"%{q}%"
        params += [like, like, like]

    sql += " ORDER BY e.start_ts ASC LIMIT %s"
    params.append(limit)

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            events = cur.fetchall()

    return render_template(
        "prematch_fonbet.html",
        events=events,
        q=q,
        hours=hours,
        limit=limit,
    )


@bp_fonbet.get("/event/<int:event_id>")
def fonbet_event(event_id: int):
    hours = int(request.args.get("hours") or "6")
    limit = int(request.args.get("limit") or "800")

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT event_id, league_name, team1, team2, FROM_UNIXTIME(start_ts) AS start_time "
                "FROM fonbet_events WHERE event_id=%s",
                (event_id,),
            )
            ev = cur.fetchone()

            # последние изменения по фактору (с prev_odd)
            cur.execute(
                """
                SELECT
                  h.ts,
                  h.factor_id,
                  h.odd,
                  LAG(h.odd) OVER (PARTITION BY h.event_id, h.factor_id ORDER BY h.ts) AS prev_odd
                FROM fonbet_odds_history h
                WHERE h.event_id=%s AND h.ts >= NOW() - INTERVAL %s HOUR
                ORDER BY h.ts DESC
                LIMIT %s
                """,
                (event_id, hours, limit),
            )
            rows = cur.fetchall()

    return render_template(
        "prematch_event_fonbet.html",
        event=ev,
        rows=rows,
        hours=hours,
        limit=limit,
    )
