from .db import get_conn

def load_event_raw(event_id: int) -> dict:
    """
    Тут ты используешь свои реальные SQL и структуру.
    Сейчас заглушка: верни dict с event_name, league_name, totals, handicaps...
    """
    with get_conn().cursor() as cur:
        # TODO: заменить на твой реальный запрос
        cur.execute("SELECT %s as event_id", (event_id,))
        row = cur.fetchone() or {}
    return {
        "event_id": event_id,
        "event_name": row.get("event_id", str(event_id)),
        "league_name": "",
        "totals": [],
        "handicaps": [],
    }
