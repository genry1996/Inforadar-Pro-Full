# -*- coding: utf-8 -*-
"""
fonbet_inforadar_markets.py

Помогатор для UI "как Inforadar" для Fonbet.

Задача:
- В таблицы не должны попадать "чужие" тоталы (угловые, карточки, фолы...).
- MAIN TOTAL = только тотал голов в матче (over/under).
- MAIN HANDICAP = только азиатская фора матча, знак домашней форы сохраняем.
- 1X2 = только исходы 1/X/2.

Ключевая идея: не классифицировать рынки по словам "тотал/фора" в тексте,
а строить точную карту factorId->(market, line, side) из eventView.

В eventView рынки лежат в:
events[] -> (нужный матч по id) -> subcategories[] -> quotes[].

Типичный пример:
- subcategory "Тотал" : quotes вида "Б (2.5)" / "М (2.5)".
- subcategory "Азиатская фора" : quotes идут как таблица с subtitle-строками:
    {"subtitle": true, "nameParamText": "-0.25", ...}
    {"factorId": ..., "name": "1", "p": "-0.25", ...}
    {"subtitle": true, "nameParamText": "+0.25", ...}
    {"factorId": ..., "name": "2", "p": "+0.25", ...}

Этот файл НЕ зависит от Flask и может импортироваться в app_22bet.py.
"""

from __future__ import annotations
import re

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, Iterable


def safe_float(x: Any) -> Optional[float]:
    """Convert '1.97' / '1,97' / 1.97 -> float, else None."""
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    if isinstance(x, str):
        s = x.strip().replace(",", ".")
        if not s:
            return None
        try:
            return float(s)
        except ValueError:
            return None
    return None


def _find_match_event(eventview: Dict[str, Any], event_id: Optional[int]) -> Optional[Dict[str, Any]]:
    """Find the match node inside eventView that contains subcategories."""
    if not isinstance(eventview, dict):
        return None
    ev_id = event_id or eventview.get("eventId")
    for e in eventview.get("events", []) or []:
        if not isinstance(e, dict):
            continue
        if ev_id is not None and e.get("id") != ev_id:
            continue
        if isinstance(e.get("subcategories"), list) and e.get("team1") and e.get("team2"):
            return e
    # Fallback: first event with subcategories + teams
    for e in eventview.get("events", []) or []:
        if isinstance(e, dict) and isinstance(e.get("subcategories"), list) and e.get("team1") and e.get("team2"):
            return e
    return None


def _pick_subcategory(
    subs: List[Dict[str, Any]],
    prefer_exact_names: Iterable[str],
    predicate: Optional[callable] = None,
) -> Optional[Dict[str, Any]]:
    """Pick best subcategory by exact name, else by predicate."""
    name_map = {s.get("name"): s for s in subs if isinstance(s, dict) and s.get("name")}
    for n in prefer_exact_names:
        if n in name_map:
            return name_map[n]
    if predicate:
        for s in subs:
            try:
                if predicate(s):
                    return s
            except Exception:
                continue
    return None


def _parse_total_pairs_from_subcategory(sub: Dict[str, Any]) -> Dict[str, Tuple[int, int]]:
    """
    Parse Total(Goals) pairs from subcategory quotes:
    line -> (over_factor_id, under_factor_id)
    """
    pairs: Dict[str, Dict[str, int]] = {}
    for q in sub.get("quotes", []) or []:
        if not isinstance(q, dict):
            continue
        fid = q.get("factorId")
        p = q.get("p")
        name = (q.get("name") or "").strip()
        if not fid or p is None or not name:
            continue
        side: Optional[str] = None
        # Fonbet RU: "Б (2.5)" / "М (2.5)"
        if name.startswith("Б"):
            side = "O"
        elif name.startswith("М"):
            side = "U"
        if not side:
            continue
        line = str(p).strip()
        pairs.setdefault(line, {})[side] = int(fid)
    out: Dict[str, Tuple[int, int]] = {}
    for line, d in pairs.items():
        if "O" in d and "U" in d:
            out[line] = (d["O"], d["U"])
    return out


def _parse_1x2_from_subcategory(sub: Dict[str, Any]) -> Dict[str, int]:
    """Return factorIds for 1/X/2 if present."""
    res: Dict[str, int] = {}
    for q in sub.get("quotes", []) or []:
        if not isinstance(q, dict):
            continue
        name = q.get("name")
        fid = q.get("factorId")
        if name in ("1", "X", "2") and fid:
            res[name] = int(fid)
    return res


def _parse_asian_handicap_rows(sub: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Parse Asian handicap rows from a subcategory "Азиатская фора".

    Returns list of rows:
        [{"hcp": "-0.25", "home_factorId": 983, "away_factorId": 984}, ...]
    """
    qs = sub.get("quotes", []) or []
    rows: List[Dict[str, Any]] = []

    # We scan for two consecutive (subtitle + selection) pairs and treat them as a row.
    i = 0
    n = len(qs)
    while i < n - 1:
        a = qs[i]
        b = qs[i + 1]
        if isinstance(a, dict) and a.get("subtitle") and isinstance(b, dict) and b.get("factorId"):
            # find next subtitle+selection pair
            j = i + 2
            while j < n - 1:
                c = qs[j]
                d = qs[j + 1]
                if isinstance(c, dict) and c.get("subtitle") and isinstance(d, dict) and d.get("factorId"):
                    # We have (a,b) and (c,d) as the row's two cells.
                    # Determine which one is home (name == '1') and which is away (name == '2').
                    def hcp_text(x: Dict[str, Any]) -> str:
                        t = x.get("nameParamText") or x.get("name") or ""
                        t = str(t).replace("Фора", "").strip()
                        return t

                    b_name = str(b.get("name") or "").strip()
                    d_name = str(d.get("name") or "").strip()

                    if b_name == "1" and d_name == "2":
                        rows.append({"hcp": hcp_text(a), "home_factorId": int(b["factorId"]), "away_factorId": int(d["factorId"])})
                    elif b_name == "2" and d_name == "1":
                        rows.append({"hcp": hcp_text(c), "home_factorId": int(d["factorId"]), "away_factorId": int(b["factorId"])})
                    else:
                        # fallback: choose the cell where selection name == '1' as home
                        if b_name == "1":
                            rows.append({"hcp": hcp_text(a), "home_factorId": int(b["factorId"]), "away_factorId": int(d["factorId"])})
                        elif d_name == "1":
                            rows.append({"hcp": hcp_text(c), "home_factorId": int(d["factorId"]), "away_factorId": int(b["factorId"])})
                        # else: skip row
                    i = j + 2
                    break
                j += 1
            else:
                # no second cell found
                i += 1
        else:
            i += 1
    return rows


def extract_current_odds_from_eventview(eventview: Dict[str, Any], event_id: Optional[int] = None) -> Dict[int, float]:
    """Build factorId -> current odds from eventView (quotes[].value / quote)."""
    match = _find_match_event(eventview, event_id)
    if not match:
        return {}
    odds: Dict[int, float] = {}
    for sub in match.get("subcategories", []) or []:
        for q in sub.get("quotes", []) or []:
            if not isinstance(q, dict):
                continue
            fid = q.get("factorId")
            if not fid:
                continue
            v = q.get("value")
            if v is None:
                v = q.get("quote")
            fv = safe_float(v)
            if fv is None:
                continue
            odds[int(fid)] = fv
    return odds


def choose_mainline_total(total_pairs: Dict[str, Tuple[int, int]], odds_by_fid: Dict[int, float]) -> Optional[str]:
    """
    Choose total line (string) that is most "mainline" like Inforadar:
    minimal |over-under|, then average odds closer to 2.0, then line closer to 2.5.
    """
    best: Optional[Tuple[Tuple[float, float, float, float], str]] = None
    for line, (fo, fu) in total_pairs.items():
        o = odds_by_fid.get(int(fo))
        u = odds_by_fid.get(int(fu))
        if not o or not u:
            continue
        diff = abs(o - u)
        avg = (o + u) / 2.0
        lf = safe_float(line) or 0.0
        score = (diff, abs(avg - 2.0), abs(lf - 2.5), lf)
        if best is None or score < best[0]:
            best = (score, line)
    return best[1] if best else None


def _parse_simple_handicap_rows_from_subcategory(sub: Optional[dict]) -> List[Dict[str, Any]]:
    """Parse Fonbet 'Фора' subcategory where quotes look like:
       name='1 (-2.5)', p='-2.5'  and  name='2 (+2.5)', p='+2.5'
       Returns rows compatible with the existing asian_hcp_rows consumer.
    """
    if not sub:
        return []
    quotes = sub.get("quotes") or []
    groups: Dict[float, Dict[str, Tuple[int, float]]] = {}
    for q in quotes:
        if not isinstance(q, dict):
            continue
        fid = q.get("factorId")
        if fid is None:
            continue
        p = safe_float(q.get("p"))
        if p is None:
            continue

        name = str(q.get("name") or "").strip()
        if not name:
            continue
        side = None
        # Fonbet uses '1 (...)' and '2 (...)' for handicap outcomes.
        if name.startswith("1"):
            side = "home"
        elif name.startswith("2"):
            side = "away"
        else:
            continue

        key = round(abs(p), 4)
        groups.setdefault(key, {})[side] = (int(fid), float(p))

    rows: List[Dict[str, Any]] = []
    for _, d in groups.items():
        if "home" not in d or "away" not in d:
            continue
        home_fid, home_p = d["home"]
        away_fid, _away_p = d["away"]

        # Keep sign for UI. Use '+X' for positive handicaps, '0' for zero.
        if abs(home_p) < 1e-9:
            hcp_str = "0"
        elif home_p > 0:
            hcp_str = f"+{home_p:g}"
        else:
            hcp_str = f"{home_p:g}"

        rows.append({"hcp": hcp_str, "home_factorId": home_fid, "away_factorId": away_fid})

    # sort: smaller absolute handicap first (nicer, and matches common UI ordering)
    def _sort_key(r: Dict[str, Any]) -> float:
        v = safe_float(r.get("hcp"))
        return abs(v) if v is not None else 999.0

    rows.sort(key=_sort_key)
    return rows


def _parse_handicap_rows_from_subcategory(sub: Optional[dict]) -> List[Dict[str, Any]]:
    """Unified handicap parser:
    - If quotes have 'subtitle' -> parse asian-style rows (existing logic)
    - Else -> parse simple 'Фора' rows ('1 (-x)' / '2 (+x)')
    """
    if not sub:
        return []
    quotes = sub.get("quotes") or []
    has_subtitle = any(isinstance(q, dict) and q.get("subtitle") for q in quotes)
    if has_subtitle:
        return _parse_asian_handicap_rows(sub)
    return _parse_simple_handicap_rows_from_subcategory(sub)
def choose_mainline_asian_hcp(rows: List[Dict[str, Any]], odds_by_fid: Dict[int, float]) -> Optional[str]:
    """
    Choose asian handicap row by similar rule:
    minimal |home-away|, avg odds closer to 2.0, then |hcp| closer to 0.
    Returns hcp string (home sign).
    """
    best: Optional[Tuple[Tuple[float, float, float, float], str]] = None
    for r in rows:
        fo = int(r["home_factorId"])
        fu = int(r["away_factorId"])
        o = odds_by_fid.get(fo)
        u = odds_by_fid.get(fu)
        if not o or not u:
            continue
        diff = abs(o - u)
        avg = (o + u) / 2.0
        h = safe_float(r.get("hcp")) or 0.0
        score = (diff, abs(avg - 2.0), abs(h), h)
        if best is None or score < best[0]:
            best = (score, str(r.get("hcp")))
    return best[1] if best else None


def build_market_map_from_eventview(eventview: Dict[str, Any], event_id: Optional[int] = None) -> Dict[str, Any]:
    """
    Build a compact market map for a match:
    {
      "event_id": 60904529,
      "team1": "...",
      "team2": "...",
      "outcomes": {"1": 921, "X": 922, "2": 923},
      "total_pairs": {"2.5": (930, 931), ...},
      "asian_hcp_rows": [{"hcp":"-0.25","home_factorId":983,"away_factorId":984}, ...],
      "allowed_factor_ids": [...],
      "main_total": "2.5",
      "main_hcp": "-0.25",
    }
    """
    match = _find_match_event(eventview, event_id)
    if not match:
        return {"event_id": event_id or eventview.get("eventId"), "error": "match_not_found"}

    subs = match.get("subcategories", []) or []

    # Pick subcategories strictly by name first, then fallback heuristics.
    sub_1x2 = _pick_subcategory(subs, ["Исходы"], predicate=lambda s: (s.get("name") or "").lower().strip() == "исходы")
    sub_total = _pick_subcategory(
        subs,
        ["Тотал"],
        predicate=lambda s: any(isinstance(q, dict) and (q.get("name") or "").startswith(("Б", "М")) and safe_float(q.get("p")) is not None
                               for q in (s.get("quotes") or [])),
    )
    sub_hcp = _pick_subcategory(
        subs,
        ["Азиатская фора", "Фора"],
        predicate=lambda s: (
            any(isinstance(q, dict) and q.get("subtitle") for q in (s.get("quotes") or []))
            or any(
                isinstance(q, dict)
                and safe_float(q.get("p")) is not None
                and str(q.get("name") or "").strip().startswith(("1", "2"))
                for q in (s.get("quotes") or [])
            )
        ),
    )

    outcomes = _parse_1x2_from_subcategory(sub_1x2) if sub_1x2 else {}
    total_pairs = _parse_total_pairs_from_subcategory(sub_total) if sub_total else {}
    asian_rows = _parse_handicap_rows_from_subcategory(sub_hcp) if sub_hcp else []

    allowed: set[int] = set()
    allowed.update(outcomes.values())
    for fo, fu in total_pairs.values():
        allowed.add(int(fo))
        allowed.add(int(fu))
    for r in asian_rows:
        allowed.add(int(r["home_factorId"]))
        allowed.add(int(r["away_factorId"]))

    odds = extract_current_odds_from_eventview(eventview, event_id or match.get("id"))
    main_total = choose_mainline_total(total_pairs, odds) if total_pairs else None
    main_hcp = choose_mainline_asian_hcp(asian_rows, odds) if asian_rows else None

    return {
        "event_id": match.get("id"),
        "team1": match.get("team1"),
        "team2": match.get("team2"),
        "outcomes": outcomes,
        "total_pairs": total_pairs,
        "asian_hcp_rows": asian_rows,
        "allowed_factor_ids": sorted(allowed),
        "main_total": main_total,
        "main_hcp": main_hcp,
    }