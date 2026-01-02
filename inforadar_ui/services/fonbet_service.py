from ..repo_fonbet import load_event_raw
from ..markets.fonbet_markets import pick_mainline_total, pick_mainline_handicap, is_esport_or_virtual

def build_event_view(event_id: int):
    raw = load_event_raw(event_id)

    # Пример: отсекаем кибер/виртуал по названиям
    name = raw.get("event_name","")
    league = raw.get("league_name","")
    if is_esport_or_virtual(name) or is_esport_or_virtual(league):
        return None

    totals = raw.get("totals", [])
    handicaps = raw.get("handicaps", [])

    main_total = pick_mainline_total(totals)
    main_handicap = pick_mainline_handicap(handicaps)

    raw["main_total"] = main_total
    raw["main_handicap"] = main_handicap
    return raw
