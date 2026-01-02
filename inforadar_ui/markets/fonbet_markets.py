import re

ESPORT_RE = re.compile(r"\b(esports?|кибер|cyber)\b", re.I)

def is_esport_or_virtual(text: str) -> bool:
    if not text:
        return False
    t = text.lower()
    # твои правила: vs/ники в скобках/подчёркивания и т.п.
    if " vs " in t:
        return True
    if "_" in t:
        return True
    if re.search(r"\([^)]+\)", t):  # (Liu_Kang)
        return True
    if ESPORT_RE.search(t):
        return True
    return False

def classify_total_market(market_name: str) -> str:
    """
    Вернёт тип тотала:
    - "goals" только голы матча
    - "other" угловые/карточки/фолы/и т.д.
    """
    if not market_name:
        return "other"
    n = market_name.lower()

    # жёстко отсекаем “не голы”
    bad = ["углов", "corn", "карточ", "card", "фол", "foul", "удар", "shots", "офсайд", "offside"]
    if any(x in n for x in bad):
        return "other"

    # голы матча (можно расширять под реальные названия фонбета)
    good = ["гол", "goals", "итог", "матч"]
    if "тотал" in n and (any(x in n for x in good) or "total" in n):
        return "goals"

    return "other"

def pick_mainline_total(candidates: list[dict]) -> dict | None:
    """
    candidates: список рынков тотала (как ты их достаёшь из БД/JSON)
    Вернём 1 “mainline” как inforadar.
    Пока заглушка: выбираем первый, который goals.
    """
    goals = [m for m in candidates if classify_total_market(m.get("name","")) == "goals"]
    if not goals:
        return None
    # TODO: выбрать line ближе к "основной" (часто 2.5), либо по признаку “основной”
    return goals[0]

def pick_mainline_handicap(candidates: list[dict]) -> dict | None:
    """
    Аналогично, но для форы (азиатская фора матча).
    """
    if not candidates:
        return None
    # TODO: отсеять фору по угловым/картам и т.п. по названию рынка
    return candidates[0]
