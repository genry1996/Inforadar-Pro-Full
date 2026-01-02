# -*- coding: utf-8 -*-
"""
fonbet_inforadar_markets.py

Помогатор для UI "как Inforadar" для Fonbet.

Что делаем:
- Жёстко фильтруем рынки, чтобы в таблицы не попадали "чужие" тоталы/форы
  (угловые, карточки, фолы и т.п.).
- 1X2 = только исходы 1/X/2 (матч, основное время).
- Total = только тотал голов матча (Over/Under) и его MAINLINE.
- Handicap = только фора матча (включая азиатскую/обычную), знак домашней форы сохраняем,
  и MAINLINE берём как на сайте Fonbet (обычно из блока "Основные"), а не по "балансу" 2.00/2.00.

Ключевая идея:
Не пытаться угадывать по словам "тотал/фора" в labels из history,
а построить точную карту factorId из eventView:
events[] -> (нужный матч по id) -> subcategories[] -> quotes[].

ВАЖНО:
В Fonbet subcategory "Основные" часто содержит именно те линии, которые показаны на сайте по умолчанию:
- ФОРА 1 / ФОРА 2 (main handicap)
- Тотал Б / Тотал М (main total)
Именно их используем как MAINLINE, чтобы совпасть с Fonbet + Inforadar.

Этот модуль не делает сетевых запросов. Он работает с уже полученным JSON eventView.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple


def safe_float(x: Any) -> Optional[float]:
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).strip().replace(",", ".")
    if not s:
        return None
    try:
        return float(s)
    except Exception:
        return None


def _fmt_line(v: Any) -> str:
    f = safe_float(v)
    if f is None:
        return str(v) if v is not None else ""
    # trim like 2.500 -> 2.5, -1.000 -> -1
    s = f"{f:.6f}".rstrip("0").rstrip(".")
    if s == "-0":
        s = "0"
    return s


def _find_match_event(eventview: Dict[str, Any], event_id: Optional[int]) -> Optional[Dict[str, Any]]:
    if not isinstance(eventview, dict):
        return None
    events = eventview.get("events") or []
    if not isinstance(events, list):
        return None
    if event_id:
        for e in events:
            try:
                if int(e.get("id")) == int(event_id):
                    return e
            except Exception:
                continue
    return events[0] if events else None


def _pick_subcategory(subs: List[Dict[str, Any]], prefer: List[str] = None, pred=None) -> Optional[Dict[str, Any]]:
    prefer = prefer or []
    # 1) exact/contains prefers
    for key in prefer:
        k2 = (key or "").strip().lower()
        if not k2:
            continue
        for s in subs:
            nm = str(s.get("name") or s.get("nameParametered") or "").strip().lower()
            if nm == k2 or (k2 in nm):
                return s
    # 2) predicate fallback
    if pred:
        for s in subs:
            try:
                if pred(s):
                    return s
            except Exception:
                continue
    return None


# -------------------- OUTCOMES (1X2) --------------------

def _parse_1x2_factor_ids(sub: Dict[str, Any]) -> Dict[str, int]:
    """Return mapping {'1': fid, 'X': fid, '2': fid} if present."""
    out: Dict[str, int] = {}
    qs = sub.get("quotes", []) or []
    for q in qs:
        if not isinstance(q, dict):
            continue
        fid = q.get("factorId")
        if not fid:
            continue
        nm = str(q.get("name") or q.get("nameParamText") or "").strip().upper()
        if nm in ("1", "X", "2", "Х"):
            out["X" if nm == "Х" else nm] = int(fid)
    # sometimes names are team names; then 1/X/2 may be in nameParametered or shortName
    # but eventView usually gives explicit 1/X/2 for match outcome.
    return out


# -------------------- TOTALS --------------------

def _tot_side_from_name(name: str) -> Optional[str]:
    t = re.sub(r"\s+", " ", (name or "").strip().lower())
    # common RU labels
    if t.startswith("тб") or t.startswith("б") or "тотал б" in t or "больше" in t or t.startswith("over") or t.startswith("o "):
        return "over"
    if t.startswith("тм") or t.startswith("м") or "тотал м" in t or "меньше" in t or t.startswith("under") or t.startswith("u "):
        return "under"
    return None


def _parse_total_pairs_from_subcategory(sub: Dict[str, Any]) -> Dict[str, Tuple[int, int]]:
    """Return dict line->(factorIdOver, factorIdUnder)"""
    qs = sub.get("quotes", []) or []
    tmp: Dict[float, Dict[str, int]] = {}
    for q in qs:
        if not isinstance(q, dict):
            continue
        fid = q.get("factorId")
        if not fid:
            continue
        line = safe_float(q.get("p") or q.get("param") or q.get("line") or q.get("value"))
        if line is None:
            # try parse from name: "Б (2.5)"
            nm = str(q.get("name") or "")
            m = re.search(r"\(([-+]?\d+(?:\.\d+)?)\)", nm)
            line = safe_float(m.group(1)) if m else None
        if line is None:
            continue
        side = _tot_side_from_name(str(q.get("name") or q.get("nameParamText") or ""))
        if side not in ("over", "under"):
            continue
        tmp.setdefault(float(line), {})[side] = int(fid)
    out: Dict[str, Tuple[int, int]] = {}
    for ln, d in tmp.items():
        if "over" in d and "under" in d:
            out[_fmt_line(ln)] = (int(d["over"]), int(d["under"]))
    return out


def choose_mainline_total(total_pairs: Dict[str, Tuple[int, int]], odds_by_fid: Dict[int, float]) -> Optional[str]:
    """
    Fallback chooser when no explicit mainline is present.
    Heuristic: minimal |over-under|, then avg closer to 2.0, then line closer to 2.5.
    """
    best: Optional[Tuple[Tuple[float, float, float, float], str]] = None
    for line, (fo, fu) in (total_pairs or {}).items():
        o = odds_by_fid.get(int(fo))
        u = odds_by_fid.get(int(fu))
        if o is None or u is None:
            continue
        diff = abs(o - u)
        avg = (o + u) / 2.0
        lf = safe_float(line) or 0.0
        score = (diff, abs(avg - 2.0), abs(lf - 2.5), lf)
        if best is None or score < best[0]:
            best = (score, line)
    return best[1] if best else None


# -------------------- HANDICAPS --------------------

def _hcp_side_from_name(name: str) -> Optional[str]:
    t = re.sub(r"\s+", " ", (name or "").strip().lower())
    # RU
    if "ф1" in t or t.startswith("ф1") or "фора 1" in t or t.startswith("1 ") or t.startswith("1(") or t.startswith("1 ("):
        return "home"
    if "ф2" in t or t.startswith("ф2") or "фора 2" in t or t.startswith("2 ") or t.startswith("2(") or t.startswith("2 ("):
        return "away"
    # EN
    if t.startswith("home") or "home" in t:
        return "home"
    if t.startswith("away") or "away" in t:
        return "away"
    return None


def _parse_asian_handicap_rows(sub: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Parse Asian handicap rows from a subcategory like "Азиатская фора".
    Format: quotes list mixes subtitle rows and selection rows.
    Returns rows like:
        [{"hcp":"-0.25","home_factorId":983,"away_factorId":984}, ...]
    """
    qs = sub.get("quotes", []) or []
    rows: List[Dict[str, Any]] = []

    i = 0
    n = len(qs)
    while i < n - 1:
        a = qs[i]
        b = qs[i + 1]
        if isinstance(a, dict) and a.get("subtitle") and isinstance(b, dict) and b.get("factorId"):
            j = i + 2
            while j < n - 1:
                c = qs[j]
                d = qs[j + 1]
                if isinstance(c, dict) and c.get("subtitle") and isinstance(d, dict) and d.get("factorId"):
                    def hcp_text(x: Dict[str, Any]) -> str:
                        t = x.get("nameParamText") or x.get("name") or x.get("p") or ""
                        t = str(t).replace("Фора", "").strip()
                        return _fmt_line(t)

                    b_name = str(b.get("name") or "").strip()
                    d_name = str(d.get("name") or "").strip()

                    if b_name == "1" and d_name == "2":
                        rows.append({"hcp": hcp_text(a), "home_factorId": int(b["factorId"]), "away_factorId": int(d["factorId"])})
                    elif b_name == "2" and d_name == "1":
                        rows.append({"hcp": hcp_text(c), "home_factorId": int(d["factorId"]), "away_factorId": int(b["factorId"])})
                    else:
                        # fallback
                        if b_name == "1":
                            rows.append({"hcp": hcp_text(a), "home_factorId": int(b["factorId"]), "away_factorId": int(d["factorId"])})
                        elif d_name == "1":
                            rows.append({"hcp": hcp_text(c), "home_factorId": int(d["factorId"]), "away_factorId": int(b["factorId"])})
                    i = j + 2
                    break
                j += 1
            else:
                i += 1
        else:
            i += 1
    return rows


def _parse_simple_handicap_pairs(sub: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Parse normal handicap pairs from subcategories like:
      - "Исход с учетом форы"
      - "Фора"

    Quotes format usually: "Ф1 (-1.5)" / "Ф2 (+1.5)" with p holding line.
    Returns rows:
      [{"hcp":"-1.5","home_factorId":...,"away_factorId":...}, ...]
    """
    qs = sub.get("quotes", []) or []
    tmp: Dict[float, Dict[str, Any]] = {}
    for q in qs:
        if not isinstance(q, dict):
            continue
        fid = q.get("factorId")
        if not fid:
            continue
        name = str(q.get("name") or q.get("nameParamText") or "")
        side = _hcp_side_from_name(name)
        if side not in ("home", "away"):
            continue
        line = safe_float(q.get("p") or q.get("param") or q.get("line") or q.get("value"))
        if line is None:
            m = re.search(r"\(([-+]?\d+(?:\.\d+)?)\)", name)
            line = safe_float(m.group(1)) if m else None
        if line is None:
            continue
        key = abs(float(line))
        d = tmp.setdefault(key, {})
        d[side] = {"fid": int(fid), "line": float(line)}
    rows: List[Dict[str, Any]] = []
    for key, d in tmp.items():
        if "home" in d and "away" in d:
            home_line = d["home"]["line"]
            # Inforadar wants Hcp as HOME line sign
            rows.append({
                "hcp": _fmt_line(home_line),
                "home_factorId": int(d["home"]["fid"]),
                "away_factorId": int(d["away"]["fid"]),
            })
        elif "home" in d and "away" not in d:
            # if only away present in some odd schemas, could infer, but skip
            pass
    return rows


def choose_mainline_asian_hcp(rows: List[Dict[str, Any]], odds_by_fid: Dict[int, float]) -> Optional[str]:
    """
    Fallback chooser for handicap rows (asian or normal).
    Heuristic: minimal |home-away| then avg closer to 2.0, then abs(hcp) smaller.
    Returns hcp string (signed HOME line).
    """
    best: Optional[Tuple[Tuple[float, float, float, float], str]] = None
    for r in rows or []:
        try:
            h = odds_by_fid.get(int(r["home_factorId"]))
            a = odds_by_fid.get(int(r["away_factorId"]))
            if h is None or a is None:
                continue
            hcp_s = str(r.get("hcp") or "")
            hcp_f = safe_float(hcp_s)
            diff = abs(h - a)
            avg = (h + a) / 2.0
            score = (diff, abs(avg - 2.0), abs(hcp_f or 0.0), hcp_f or 0.0)
            if best is None or score < best[0]:
                best = (score, hcp_s)
        except Exception:
            continue
    return best[1] if best else None


# -------------------- BASIC MAINLINES --------------------

def _parse_mainlines_from_basics(sub: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse block "Основные" (or similar) and extract:
      - main_total_line + factorIds
      - main_hcp_line (HOME signed) + factorIds
    Returns dict with keys:
      main_total_line (str|None), main_total_over_fid, main_total_under_fid
      main_hcp_line (str|None), main_hcp_home_fid, main_hcp_away_fid
    """
    out: Dict[str, Any] = {
        "main_total_line": None,
        "main_total_over_fid": None,
        "main_total_under_fid": None,
        "main_hcp_line": None,
        "main_hcp_home_fid": None,
        "main_hcp_away_fid": None,
    }
    qs = sub.get("quotes", []) or []
    # collect candidates by line
    tot: Dict[float, Dict[str, int]] = {}
    hcp: Dict[float, Dict[str, Dict[str, Any]]] = {}
    for q in qs:
        if not isinstance(q, dict):
            continue
        fid = q.get("factorId")
        if not fid:
            continue
        nm = str(q.get("name") or q.get("nameParamText") or "")
        p = safe_float(q.get("p") or q.get("param") or q.get("line") or q.get("value"))
        if p is None:
            m = re.search(r"\(([-+]?\d+(?:\.\d+)?)\)", nm)
            p = safe_float(m.group(1)) if m else None

        low = re.sub(r"\s+", " ", nm.strip().lower())

        # totals in basics
        if ("тотал" in low) or low.startswith("тб") or low.startswith("тм") or low.startswith("over") or low.startswith("under") or low.startswith("б ") or low.startswith("м "):
            side = _tot_side_from_name(nm)
            if side in ("over", "under") and p is not None:
                tot.setdefault(float(p), {})[side] = int(fid)
                continue

        # handicaps in basics
        if "фора" in low or "ф1" in low or "ф2" in low or low.startswith("ф1") or low.startswith("ф2") or low.startswith("1 ") or low.startswith("2 "):
            side = _hcp_side_from_name(nm)
            if side in ("home", "away") and p is not None:
                key = abs(float(p))
                d = hcp.setdefault(key, {})
                d[side] = {"fid": int(fid), "line": float(p)}
                continue

    # choose main total: prefer line with both over & under
    for ln, d in tot.items():
        if "over" in d and "under" in d:
            out["main_total_line"] = _fmt_line(ln)
            out["main_total_over_fid"] = int(d["over"])
            out["main_total_under_fid"] = int(d["under"])
            break

    # choose main handicap: prefer line with both home & away
    for key, d in hcp.items():
        if "home" in d and "away" in d:
            out["main_hcp_line"] = _fmt_line(d["home"]["line"])
            out["main_hcp_home_fid"] = int(d["home"]["fid"])
            out["main_hcp_away_fid"] = int(d["away"]["fid"])
            break

    return out


# -------------------- PUBLIC API --------------------

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


def build_market_map_from_eventview(eventview: Dict[str, Any], event_id: Optional[int] = None) -> Dict[str, Any]:
    """
    Build mapping of the match's allowed factor IDs + mainlines.

    Returns dict:
      - outcomes_fids: {'1':..., 'X':..., '2':...}
      - total_pairs: {line_str: (over_fid, under_fid)}
      - handicap_rows: [{'hcp': '-1.5', 'home_factorId':..., 'away_factorId':...}, ...]
      - main_total: line_str or None
      - main_hcp: hcp_str or None
      - allowed_factor_ids: [..]
      - also keeps 'asian_hcp_rows' for backward compatibility (same as handicap_rows when asian is used)
    """
    match = _find_match_event(eventview, event_id)
    if not match:
        return {"outcomes_fids": {}, "total_pairs": {}, "handicap_rows": [], "main_total": None, "main_hcp": None, "allowed_factor_ids": []}

    subs = match.get("subcategories", []) or []
    subs = [s for s in subs if isinstance(s, dict)]

    # 1) Basics: mainline as on site
    sub_basics = _pick_subcategory(
        subs,
        prefer=["Основные", "Основное", "Основные рынки", "Главные", "Главное"],
        pred=lambda s: ("основ" in str(s.get("name") or "").lower()) or ("главн" in str(s.get("name") or "").lower()),
    )
    basics = _parse_mainlines_from_basics(sub_basics) if sub_basics else {}

    # 2) Outcomes (1X2)
    sub_out = _pick_subcategory(
        subs,
        prefer=["Исходы", "Исход матча", "Исход матча (основное время)", "1X2"],
        pred=lambda s: any(str(q.get("name") or "").strip().upper() in ("1", "X", "2", "Х") for q in (s.get("quotes") or []) if isinstance(q, dict)),
    )
    outcomes_fids = _parse_1x2_factor_ids(sub_out) if sub_out else {}

    # 3) Total goals: prefer subcategory mentioning goals, otherwise plain total
    sub_tot = _pick_subcategory(
        subs,
        prefer=["Тотал голов", "Тотал"],
        pred=lambda s: ("тотал" in str(s.get("name") or "").lower()) and ("углов" not in str(s.get("name") or "").lower()) and ("карт" not in str(s.get("name") or "").lower()),
    )
    total_pairs = _parse_total_pairs_from_subcategory(sub_tot) if sub_tot else {}

    # 4) Handicap: parse both asian and simple handicap
    sub_asian = _pick_subcategory(subs, prefer=["Азиатская фора"], pred=lambda s: "азиат" in str(s.get("name") or "").lower())
    asian_rows = _parse_asian_handicap_rows(sub_asian) if sub_asian else []

    sub_hcp = _pick_subcategory(
        subs,
        prefer=["Исход с учетом форы", "Фора"],
        pred=lambda s: ("фора" in str(s.get("name") or "").lower()) and ("углов" not in str(s.get("name") or "").lower()) and ("карт" not in str(s.get("name") or "").lower()),
    )
    simple_rows = _parse_simple_handicap_pairs(sub_hcp) if sub_hcp else []

    handicap_rows: List[Dict[str, Any]] = []
    # prefer asian if present, but keep simple rows too (some events have only simple)
    if asian_rows:
        handicap_rows.extend(asian_rows)
    if simple_rows:
        # merge unique by (hcp, home_fid, away_fid)
        seen = {(str(r.get("hcp")), int(r.get("home_factorId")), int(r.get("away_factorId"))) for r in handicap_rows if r.get("home_factorId") and r.get("away_factorId")}
        for r in simple_rows:
            key = (str(r.get("hcp")), int(r.get("home_factorId")), int(r.get("away_factorId")))
            if key not in seen:
                handicap_rows.append(r)
                seen.add(key)

    # 5) Add mainline pairs from Basics if they exist (to be safe even if sub_tot/sub_hcp parsing failed)
    if basics.get("main_total_line") and basics.get("main_total_over_fid") and basics.get("main_total_under_fid"):
        total_pairs.setdefault(str(basics["main_total_line"]), (int(basics["main_total_over_fid"]), int(basics["main_total_under_fid"])))

    if basics.get("main_hcp_line") and basics.get("main_hcp_home_fid") and basics.get("main_hcp_away_fid"):
        # ensure row exists
        key = (str(basics["main_hcp_line"]), int(basics["main_hcp_home_fid"]), int(basics["main_hcp_away_fid"]))
        if not any((str(r.get("hcp")), int(r.get("home_factorId")), int(r.get("away_factorId"))) == key for r in handicap_rows):
            handicap_rows.append({
                "hcp": str(basics["main_hcp_line"]),
                "home_factorId": int(basics["main_hcp_home_fid"]),
                "away_factorId": int(basics["main_hcp_away_fid"]),
            })

    # Allowed factor ids: only these markets
    allowed: set = set()
    for oc in ("1", "X", "2"):
        if oc in outcomes_fids:
            allowed.add(int(outcomes_fids[oc]))
    for _, (fo, fu) in (total_pairs or {}).items():
        allowed.add(int(fo))
        allowed.add(int(fu))
    for r in handicap_rows or []:
        try:
            allowed.add(int(r["home_factorId"]))
            allowed.add(int(r["away_factorId"]))
        except Exception:
            continue

    # Choose mainlines: prefer Basics (site mainline), fallback to heuristics
    odds_by_fid = extract_current_odds_from_eventview(eventview, event_id)

    main_total = basics.get("main_total_line") or None
    if not main_total:
        main_total = choose_mainline_total(total_pairs, odds_by_fid) if total_pairs else None

    main_hcp = basics.get("main_hcp_line") or None
    if not main_hcp:
        main_hcp = choose_mainline_asian_hcp(handicap_rows, odds_by_fid) if handicap_rows else None

    return {
        "outcomes_fids": outcomes_fids,
        "total_pairs": total_pairs,
        "handicap_rows": handicap_rows,
        # backward compatibility
        "asian_hcp_rows": asian_rows,
        "main_total": main_total,
        "main_hcp": main_hcp,
        "allowed_factor_ids": sorted(int(x) for x in allowed),
    }
