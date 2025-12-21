"""
Финальные критерии для продакшн-версии
Единые пороги на весь матч, метка 75+ только визуально
"""

PRODUCTION_CONFIG = {
    # === Sharp Drop критерии (единые для всего матча) ===
    "odds_drops": [
        {
            "name": "10→5",
            "from_min": 10.0,
            "to_max": 5.0,
            "drop_percent_min": 30  # Минимум 30% падение
        },
        {
            "name": "5→2.0",
            "from_min": 5.0,
            "to_max": 2.0,
            "drop_percent_min": 20  # Минимум 20% падение
        },
        {
            "name": "2.0→1.3",
            "from_min": 2.0,
            "to_max": 1.3,
            "drop_percent_min": 15  # Минимум 15% падение
        }
    ],
    
    # === Превышение средней суммы ===
    "money_multiplier": 1.5,  # В 1.5 раза выше средней
    
    # === Метка позднего времени (только визуал) ===
    "late_game_minute": 75,
    
    # === Прочие настройки ===
    "send_only_on_drop": True,  # Слать только при падении
    "min_money_absolute": 1000,  # Минимальная сумма в евро
}


def check_odds_drop(odds_before: float, odds_now: float) -> dict:
    """Проверка падения коэффициента по продакшн-критериям"""
    if odds_before <= odds_now:
        return None
    
    drop_percent = ((odds_before - odds_now) / odds_before) * 100
    
    for rule in PRODUCTION_CONFIG["odds_drops"]:
        if odds_before >= rule["from_min"] and odds_now <= rule["to_max"]:
            if drop_percent >= rule["drop_percent_min"]:
                return {
                    "type": rule["name"],
                    "drop_percent": round(drop_percent, 1),
                    "odds_from": odds_before,
                    "odds_to": odds_now
                }
    
    return None


def check_money_spike(current_money: float, avg_money: float) -> bool:
    """Проверка превышения средней суммы"""
    if current_money < PRODUCTION_CONFIG["min_money_absolute"]:
        return False
    
    if avg_money == 0:
        return current_money >= PRODUCTION_CONFIG["min_money_absolute"]
    
    return current_money >= (avg_money * PRODUCTION_CONFIG["money_multiplier"])


def detect_signal(odds_before: float, odds_now: float, 
                 current_money: float, avg_money: float, 
                 minute: int) -> dict:
    """
    Главная функция детекта сигнала для прода
    Возвращает словарь с данными сигнала или None
    """
    # 1. Проверка падения коэффициента
    drop_info = check_odds_drop(odds_before, odds_now)
    if not drop_info:
        return None
    
    # 2. Проверка превышения денег
    if not check_money_spike(current_money, avg_money):
        return None
    
    # 3. Метка времени (если >= 75 минуты) - только визуал
    late_game = minute >= PRODUCTION_CONFIG["late_game_minute"]
    
    return {
        "signal_type": f"sharpdrop_{drop_info['type'].replace('→', '-')}",
        "drop_range": drop_info["type"],
        "odds_from": drop_info["odds_from"],
        "odds_to": drop_info["odds_to"],
        "drop_percent": drop_info["drop_percent"],
        "money": current_money,
        "money_multiplier": round(current_money / avg_money, 1) if avg_money > 0 else 0,
        "minute": minute,
        "late_game": late_game
    }
