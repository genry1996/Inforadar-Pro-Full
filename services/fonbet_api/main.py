import os
import json
import ast
import re
import importlib.util
import time
from datetime import datetime
from typing import Optional, Any, Dict, List, Set, Tuple

from fastapi import FastAPI, Query, Path


SHARED_APP_PATH = os.getenv("FONBET_SHARED_APP_PATH", "/opt/shared/app_22bet.py")


def _load_shared_module(path: str):
    spec = importlib.util.spec_from_file_location("shared_app_22bet", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load shared module from {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


shared = _load_shared_module(SHARED_APP_PATH)

app = FastAPI(title="Fonbet Microservice", version="0.2.6")


def _sql_has_col(cur, table: str, col: str) -> bool:
    """Return True if `table` has column `col`. Uses SHOW COLUMNS."""
    try:
        cur.execute(f"SHOW COLUMNS FROM {table} LIKE %s", (col,))
        return bool(cur.fetchone())
    except Exception:
        return False

def _fmt_start_ts(start_ts: int) -> str:
    # Convert unix seconds -> local-ish string (same style as other endpoints)
    try:
        return datetime.fromtimestamp(int(start_ts)).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ""
@app.get("/health")
def health():
    return {"ok": True, "shared": SHARED_APP_PATH, "version": "0.3.0"}


def _fids_from_rows(rows: List[Dict[str, Any]]) -> List[int]:
    fids: Set[int] = set()
    for r in rows or []:
        try:
            fid = int(r.get("factor_id") or 0)
        except Exception:
            fid = 0
        if fid > 0:
            fids.add(fid)
    return sorted(fids)


def _norm_market(m: str) -> str:
    s = (m or "").strip().lower()
    if not s:
        return ""

    # detect first half / HT markers
    is_1h = any(k in s for k in ("_1h", "1h", "ht", "half1", "1sthalf", "1st_half", "1_half", "1 тайм", "1-й тайм"))

    if any(k in s for k in ("outcomes", "1x2", "win_draw_win", "w-d-w", "result", "match_result", "1х2", "исход", "исходы")):
        return "outcomes_1h" if is_1h else "outcomes"
    if any(k in s for k in ("handicap", "hcp", "fora", "asian_handicap", "фора", "форы", "ah")):
        return "handicap_1h" if is_1h else "handicap"
    if any(k in s for k in ("total", "totals", "тотал", "тоталы", "over", "under", "тб", "тм", "tb", "tm", "больше", "меньше")):
        return "total_1h" if is_1h else "total"

    return s


def _pick_col(cols: Set[str], candidates: List[str]) -> Optional[str]:
    for c in candidates:
        if c in cols:
            return c
    return None


def _factor_catalog_columns() -> Tuple[Optional[str], Optional[str], Optional[str], List[str]]:
    """
    Return (market_col, label_col, param_col, all_cols) for fonbet_factor_catalog table
    based on SHOW COLUMNS.
    """
    try:
        with shared.db_connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SHOW COLUMNS FROM fonbet_factor_catalog")
                rows = cur.fetchall() or []
    except Exception:
        return (None, None, None, [])

    cols = {str(r.get("Field") or "").strip() for r in rows if isinstance(r, dict) and r.get("Field")}
    cols = {c for c in cols if c}
    all_cols = sorted(cols)

    market_col = _pick_col(
        cols,
        [
            "market", "market_key", "market_name", "market_id", "marketid",
            "mkt", "mkt_id",
            "type", "type_id",
            "kind", "kind_id",
            "group", "group_id",
            "section", "section_id",
            "tab", "tab_id",
            "period", "period_id",
            "pt", "pt_id",
        ],
    )
    label_col = _pick_col(cols, ["label", "name", "title", "factor_name", "outcome", "caption", "text"])
    param_col = _pick_col(cols, ["param", "line", "value", "handicap", "total", "p", "param_value"])

    return (market_col, label_col, param_col, all_cols)


def _parse_raw_any(raw: Any) -> Any:
    if raw is None:
        return None
    try:
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8", errors="ignore")
    except Exception:
        pass

    raw_s = str(raw or "").strip()
    if not raw_s:
        return None

    # JSON
    if raw_s[:1] in ("{", "["):
        try:
            return json.loads(raw_s)
        except Exception:
            pass

    # Python-literal dict/list (часто бывает с одинарными кавычками)
    try:
        obj = ast.literal_eval(raw_s)
        if isinstance(obj, (dict, list)):
            return obj
    except Exception:
        pass

    return None



def _is_noneish(v: Any) -> bool:
    if v is None:
        return True
    try:
        s = str(v).strip()
    except Exception:
        return False
    if not s:
        return True
    return s.lower() in ("none", "null", "nan")


def _keep_ctx_str(s: str) -> bool:
    ss = (s or "").strip()
    if not ss:
        return False
    if len(ss) > 160:
        return False
    if ss.lower().startswith(("http://", "https://")):
        return False
    # если вообще нет букв — обычно мусор
    if not re.search(r"[A-Za-zА-Яа-яЁё]", ss):
        return False
    return True


def _collect_strings_from_json(node: Any, out: List[str], depth: int = 0) -> None:
    """
    Extract strings from nested JSON/Python-literal structures.
    We keep ALL strings (с фильтрами), чтобы не зависеть от конкретных ключей в raw_json.
    """
    if depth > 8:
        return

    if isinstance(node, dict):
        for k, v in node.items():
            if isinstance(v, str):
                if _keep_ctx_str(v):
                    out.append(v.strip())
            elif isinstance(v, (dict, list)):
                _collect_strings_from_json(v, out, depth + 1)

            # иногда полезны и ключи
            try:
                kk = str(k)
                if _keep_ctx_str(kk) and kk.lower() in ("name", "title", "caption", "text", "market", "period", "kind", "type", "group"):
                    out.append(kk.strip())
            except Exception:
                pass

    elif isinstance(node, list):
        for item in node[:200]:
            _collect_strings_from_json(item, out, depth + 1)


def _classify_market_text(ctx: str) -> str:
    """
    Classify market by text.
    Prefer shared._fonbet_classify_market if present, else fallback heuristics.
    """
    s = (ctx or "").strip()
    if not s:
        return "other"

    fn = getattr(shared, "_fonbet_classify_market", None)
    if callable(fn):
        try:
            m = fn(s) or ""
            m = (m or "").strip()
            if m:
                return m
        except Exception:
            pass

    l = s.lower()

    # totals
    if any(k in l for k in ("тотал", "total", "totals", "over", "under", "тб", "тм", "tb", "tm", "больше", "меньше")):
        return "total"

    # handicap
    if any(k in l for k in ("фора", "форы", "handicap", "hcp", "fora", "asian", "ah", "азиат")):
        return "handicap"

    # outcomes (1X2 / double chance)
    if any(k in l for k in ("1x2", "1х2", "исход", "исходы", "result", "match result", "победа", "ничья", "draw", "double chance", "двойной шанс", "1x", "x2", "12")):
        return "outcomes"

    return "other"


def _fetch_factor_catalog_map(fids: List[int]) -> Tuple[Dict[int, Dict[str, Any]], Optional[str], List[str], Dict[int, str]]:
    """
    Fetch factor_id -> {market,label,param} from DB table fonbet_factor_catalog.

    Your schema (as seen): factor_id, name, raw_json, updated_at
    There is no market column, so market is parsed from raw_json (and classified).
    """
    if not fids:
        return ({}, None, [], {})

    market_col, label_col, param_col, all_cols = _factor_catalog_columns()

    # If schema has explicit market column, use it.
    if market_col:
        select_cols = ["factor_id", market_col]
        if label_col:
            select_cols.append(label_col)
        if param_col:
            select_cols.append(param_col)

        placeholders = ",".join(["%s"] * len(fids))
        sql = f"SELECT {', '.join(select_cols)} FROM fonbet_factor_catalog WHERE factor_id IN ({placeholders})"

        try:
            with shared.db_connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(sql, fids)
                    rows = cur.fetchall() or []
        except Exception as e:
            return ({}, f"fonbet_factor_catalog query failed: {type(e).__name__}: {e}", all_cols, {})

        fmap: Dict[int, Dict[str, Any]] = {}
        ctx_map: Dict[int, str] = {}
        for r in rows:
            try:
                fid = int(r.get("factor_id") or 0)
            except Exception:
                continue
            if fid <= 0:
                continue

            market_raw = r.get(market_col) if market_col else ""
            label_raw = r.get(label_col) if label_col else ""
            param_raw = r.get(param_col) if param_col else None

            mkt = _norm_market(str(market_raw or ""))
            lbl = "" if _is_noneish(label_raw) else str(label_raw).strip()
            fmap[fid] = {"market": mkt, "label": lbl, "param": param_raw}
            ctx_map[fid] = f"{market_raw} {lbl}".strip()

        return (fmap, None, all_cols, ctx_map)

    # --- No market column: parse raw_json ---
    if "raw_json" not in all_cols:
        return ({}, "fonbet_factor_catalog: cannot find market column and no raw_json to parse", all_cols, {})

    label_col = label_col or ("name" if "name" in all_cols else None)
    if not label_col:
        return ({}, "fonbet_factor_catalog: cannot find label/name column", all_cols, {})

    placeholders = ",".join(["%s"] * len(fids))
    sql = f"SELECT factor_id, {label_col} AS name, raw_json FROM fonbet_factor_catalog WHERE factor_id IN ({placeholders})"

    try:
        with shared.db_connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, fids)
                rows = cur.fetchall() or []
    except Exception as e:
        return ({}, f"fonbet_factor_catalog raw_json query failed: {type(e).__name__}: {e}", all_cols, {})

    fmap: Dict[int, Dict[str, Any]] = {}
    ctx_map: Dict[int, str] = {}

    for r in rows:
        try:
            fid = int(r.get("factor_id") or 0)
        except Exception:
            continue
        if fid <= 0:
            continue

        name_raw = r.get("name")
        name = "" if _is_noneish(name_raw) else str(name_raw).strip()
        raw = r.get("raw_json")

        parts: List[str] = []
        if name and _keep_ctx_str(name):
            parts.append(name)

        obj = _parse_raw_any(raw)
        if obj is not None:
            extras: List[str] = []
            _collect_strings_from_json(obj, extras, 0)
            if extras:
                # не раздуваем контекст
                parts.extend(extras[:80])

        # fallback: если raw_json совсем не парсится — хоть строку добавим
        if obj is None:
            raw_s = str(raw or "").strip()
            if raw_s and len(raw_s) <= 220 and _keep_ctx_str(raw_s):
                parts.append(raw_s)

        ctx = " ".join(parts).strip()
        mkt = _classify_market_text(ctx)
        mkt = _norm_market(mkt)

        fmap[fid] = {"market": mkt or "other", "label": name, "param": None}
        ctx_map[fid] = ctx[:400] if ctx else (name[:200] if name else "")

    return (fmap, None, all_cols, ctx_map)


def _merge_maps(primary: Dict[int, Any], secondary: Dict[int, Any]) -> Dict[int, Any]:
    merged = dict(primary or {})
    for fid, info in (secondary or {}).items():
        try:
            fid_i = int(fid)
        except Exception:
            continue
        if not isinstance(info, dict):
            continue

        old = merged.get(fid_i)
        if not isinstance(old, dict):
            merged[fid_i] = info
            continue

        new = dict(old)
        if (not new.get("market") or new.get("market") == "other") and info.get("market"):
            new["market"] = info.get("market")
        if not new.get("label") and info.get("label"):
            new["label"] = info.get("label")
        if new.get("param") in (None, "", 0) and info.get("param") not in (None, "", 0):
            new["param"] = info.get("param")
        merged[fid_i] = new
    return merged


def _enrich_from_eventview(
    base_event_id: int,
    effective_event_id: int,
    half_norm: str,
    fmap: Dict[int, Any],
    fids: List[int],
    lang: str,
    sys_id: int,
) -> Tuple[Dict[int, Any], Optional[str]]:
    try:
        ev = shared._fonbet_fetch_event_view(lang=lang, sys_id=sys_id, event_id=effective_event_id)
        ev_map = shared._fonbet_extract_factor_map(
            ev, only_event_id=effective_event_id, base_event_id=base_event_id, half=half_norm
        ) or {}
    except Exception as e:
        return fmap, f"eventView failed: {type(e).__name__}: {e}"

    if fids and ev_map:
        ev_map = {fid: ev_map[fid] for fid in fids if fid in ev_map} or ev_map

    return _merge_maps(fmap, ev_map), None


def _infer_market_from_row(label: str, param: Any) -> str:
    l = (label or "").strip().lower()
    if not l:
        return ""

    l_nospace = re.sub(r"\s+", "", l)

    # totals
    if any(k in l for k in ("тотал", "total", "totals", "over", "under", "тб", "тм", "tb", "tm", "больше", "меньше")):
        return "total"

    # handicap
    if any(k in l for k in ("фора", "форы", "handicap", "hcp", "fora", "asian", "ah", "азиат")):
        return "handicap"
    if param not in (None, "", 0) and re.search(r"[+-]\s*\d", l):
        return "handicap"

    # outcomes (1X2 + doubles)
    if l_nospace in ("1", "п1", "home", "w1", "team1"):
        return "outcomes"
    if l_nospace in ("x", "х", "ничья", "draw", "d"):
        return "outcomes"
    if l_nospace in ("2", "п2", "away", "w2", "team2"):
        return "outcomes"
    if l_nospace in ("1x", "1х", "x2", "х2", "12", "1x2"):
        return "outcomes"

    if "победа" in l or "win" in l:
        return "outcomes"
    if "ничья" in l or "draw" in l:
        return "outcomes"
    if "двойной шанс" in l or "double chance" in l:
        return "outcomes"
    if re.search(r"\bп1\b", l) or re.search(r"\bп2\b", l):
        return "outcomes"

    return ""


def _apply_inferred_markets(rows: List[Dict[str, Any]], fmap: Dict[int, Any], half_norm: str) -> Dict[int, Any]:
    """
    If factor map cannot classify, try infer from odds_history row label/param.
    """
    if not rows:
        return fmap

    for r in rows:
        try:
            fid = int(r.get("factor_id") or 0)
        except Exception:
            continue
        if fid <= 0:
            continue

        info = fmap.get(fid)
        if not isinstance(info, dict):
            info = {}

        market = str(info.get("market") or "")
        if market and market != "other":
            continue

        label = r.get("label") or info.get("label") or ""
        param = r.get("param") if r.get("param") is not None else info.get("param")

        inferred = _infer_market_from_row(str(label), param)
        if not inferred:
            # попробуем ещё по label из каталога (часто там "Победа 1"/"Тотал Больше")
            inferred = _infer_market_from_row(str(info.get("label") or ""), param)

        if not inferred:
            continue

        if half_norm == "1h" and not inferred.endswith("_1h"):
            inferred = inferred + "_1h"

        info2 = dict(info)
        info2["market"] = inferred
        if not info2.get("label") and label:
            info2["label"] = str(label)
        if info2.get("param") in (None, "", 0) and param not in (None, "", 0):
            info2["param"] = param

        fmap[fid] = info2

    return fmap


def _normalize_half_markets(fmap: Dict[int, Any], half_norm: str) -> Dict[int, Any]:
    """
    Never mix FT and HT markets. Enforce suffix based on requested half.
    """
    if not fmap:
        return fmap

    for fid, info in list(fmap.items()):
        if not isinstance(info, dict):
            continue
        m = str(info.get("market") or "")
        if not m:
            continue

        if half_norm == "1h":
            if m in ("outcomes", "handicap", "total"):
                info2 = dict(info)
                info2["market"] = m + "_1h"
                fmap[int(fid)] = info2
        else:
            if m.endswith("_1h"):
                info2 = dict(info)
                info2["market"] = m[:-3]
                fmap[int(fid)] = info2

    return fmap



def _apply_factor_id_fallback(fmap: Dict[int, Any], half_norm: str) -> Dict[int, Any]:
    """
    Hard fallback for the most common Fonbet factor_ids when catalog/eventView do not provide labels/markets.
    This prevents /tables returning only "other" when label/name are NULL.
    """
    if fmap is None:
        fmap = {}

    # NOTE: IDs below are based on observed usage in this project DB:
    # 921/922/923/924/925/1571 = outcomes (1X2 + double chance),
    # 930/931 = totals (over/under),
    # 927/928 = handicaps (team1/team2)
    fid_map: Dict[int, Tuple[str, str]] = {
        921: ("outcomes", "1"),
        922: ("outcomes", "X"),
        923: ("outcomes", "2"),
        924: ("outcomes", "1X"),
        925: ("outcomes", "12"),
        1571: ("outcomes", "X2"),
        930: ("total", "ТБ"),
        931: ("total", "ТМ"),
        927: ("handicap", "Ф1"),
        928: ("handicap", "Ф2"),
    }

    for fid, (mkt_base, lbl) in fid_map.items():
        info = fmap.get(fid)
        if not isinstance(info, dict):
            info = {}

        cur_m = str(info.get("market") or "").strip()
        if cur_m and cur_m != "other":
            continue

        mkt = mkt_base + "_1h" if half_norm == "1h" else mkt_base

        info2 = dict(info)
        info2["market"] = mkt

        if _is_noneish(info2.get("label")):
            info2["label"] = lbl

        fmap[int(fid)] = info2

    return fmap


@app.get("/fonbet/events")
def fonbet_events(
    hours: int = Query(12, ge=1, le=168),
    limit: int = Query(200, ge=1, le=2000),
    q: str = Query("", max_length=100),
    sport_id: Optional[int] = Query(None),
):
    env_football_sid = shared.safe_int(os.getenv("FONBET_FOOTBALL_SPORT_ID", "1"), 0)
    sid = int(sport_id) if sport_id is not None else (env_football_sid if env_football_sid > 0 else 0)

    with shared.db_connect() as conn:
        with conn.cursor() as cur:
            rows = shared._sql_fonbet_events(
                cur, hours=int(hours), q=(q or "").strip(), limit=int(limit), sport_id=int(sid)
            )
            drops_map = {}
            try:
                ts_col = shared._fonbet_ts_col(cur)
                drops_map = shared._sql_fonbet_drops_map(cur, ts_col=ts_col, hours=6) or {}
            except Exception:
                drops_map = {}

    items: List[Dict[str, Any]] = []
    for r in rows or []:
        eid = shared.safe_int(r.get("event_id"), 0)
        dm = drops_map.get(eid) or {}
        item = {
            "event_id": eid,
            "sport_id": shared.safe_int(r.get("sport_id"), 0),
            "league_name": r.get("league_name") or "",
            "team1": r.get("team1") or "",
            "team2": r.get("team2") or "",
            "start_time": str(r.get("start_time") or ""),
            "drops": int(dm.get("drops") or 0),
            "max_drop": dm.get("max_drop"),
        }
        item["match"] = f'{item["team1"]} — {item["team2"]}'.strip(" —")
        if shared._is_special_row(item):
            continue
        items.append(item)

    return {"events": items}


@app.get("/fonbet/live")
def fonbet_live_events(
    limit: int = Query(200, ge=1, le=2000),
    q: str = Query("", max_length=100),
    sport_id: Optional[int] = Query(None),
    seen_secs: int = Query(180, ge=10, le=3600),
):
    """List live football events (requires fonbet_events.is_live + last_seen_ts)."""
    env_football_sid = shared.safe_int(os.getenv("FONBET_FOOTBALL_SPORT_ID", "1"), 0)
    sid = int(sport_id) if sport_id is not None else (env_football_sid if env_football_sid > 0 else 0)
    qq = (q or "").strip()

    now_ms = int(time.time() * 1000)
    min_seen_ms = now_ms - int(seen_secs) * 1000

    items = []
    with shared.db_connect() as conn:
        with conn.cursor() as cur:
            # if schema not migrated yet -> return empty with hint
            if not _sql_has_col(cur, "fonbet_events", "is_live") or not _sql_has_col(cur, "fonbet_events", "last_seen_ts"):
                return {
                    "events": [],
                    "note": "fonbet_events.is_live/last_seen_ts not found. Run fonbet_live_migration.sql first.",
                }

            # basic query
            sql = """
                SELECT event_id, sport_id, league_name, team1, team2, start_ts, last_seen_ts
                FROM fonbet_events
                WHERE is_live=1
                  AND (%s=0 OR sport_id=%s)
                  AND (last_seen_ts IS NULL OR last_seen_ts >= %s)
                ORDER BY COALESCE(last_seen_ts, 0) DESC
                LIMIT %s
            """
            cur.execute(sql, (sid, sid, min_seen_ms, int(limit)))
            rows = cur.fetchall() or []

    for r in rows:
        team1 = (r.get("team1") or "").strip()
        team2 = (r.get("team2") or "").strip()
        item = {
            "event_id": int(r.get("event_id") or 0),
            "sport_id": shared.safe_int(r.get("sport_id"), 0),
            "league_name": r.get("league_name") or "",
            "team1": team1,
            "team2": team2,
            "start_time": _fmt_start_ts(shared.safe_int(r.get("start_ts"), 0)),
            "last_seen_ms": shared.safe_int(r.get("last_seen_ts"), 0),
        }
        item["match"] = f'{team1} — {team2}'.strip(" —")
        if qq and qq.lower() not in (item["match"] + " " + (item["league_name"] or "")).lower():
            continue
        if shared._is_special_row(item):
            continue
        items.append(item)

    return {"events": items}

@app.get("/fonbet/event/{event_id}/tables")
def fonbet_event_tables(
    event_id: int = Path(..., ge=1),
    hours: int = Query(48, ge=1, le=168),
    limit: int = Query(8000, ge=1, le=20000),
    half: str = Query("ft"),
    debug: int = Query(0, ge=0, le=1),
):
    half_norm = shared._fonbet_norm_half(half)

    lang = os.getenv("FONBET_LANG", "ru") or "ru"
    sys_id = int(os.getenv("FONBET_SYS_ID", "1") or "1")
base_event_id = int(event_id)
    effective_event_id = base_event_id

    ht_now = None
    ht_status = None

    # Resolve HT event id and status (Inforadar-like)
    if half_norm == "1h":
        effective_event_id = shared._fonbet_resolve_1h_event_id(base_event_id, lang=lang, sys_id=sys_id)

        try:
            ev_base_now = shared._fonbet_fetch_event_view(lang=lang, sys_id=sys_id, event_id=base_event_id)
        except Exception:
            ev_base_now = None

        try:
            ht_now = bool(shared._fonbet_ev_find_1h_child(ev_base_now, base_event_id))
        except Exception:
            ht_now = False

        if not ht_now:
            try:
                fm0 = shared._fonbet_extract_factor_map(ev_base_now, base_event_id=base_event_id, half="ft") or {}
                ht_now = any(str((info or {}).get("market") or "").endswith("_1h") for info in fm0.values())
            except Exception:
                ht_now = False

    last_ts = None
    ts_col_name = None
    used_label_col = None
    used_param_col = None

    # Load odds history rows
    with shared.db_connect() as conn:
        with conn.cursor() as cur:
            ts_col_name = shared._fonbet_ts_col(cur)
            cond, params = shared._fonbet_ts_where(cur, ts_col_name, int(hours))
            ts_select = shared._fonbet_ts_select_expr(cur, ts_col_name)

            used_label_col = shared._fonbet_label_col(cur) or ("label" if _sql_has_col(cur, "fonbet_odds_history", "label") else None)
            label_select = f", {used_label_col} AS label" if used_label_col else ""
            used_param_col = shared._fonbet_param_col(cur) or ("param" if _sql_has_col(cur, "fonbet_odds_history", "param") else None)
            param_select = f", {used_param_col} AS param" if used_param_col else ""

            phase_norm = (phase or "prematch").strip().lower()
            if phase_norm not in ("prematch", "live"):
                phase_norm = "prematch"

            phase_cond = ""
            phase_params: List[Any] = []
            has_phase = _sql_has_col(cur, "fonbet_odds_history", "phase")
            if has_phase:
                if phase_norm == "prematch":
                    phase_cond = " AND (phase=%s OR phase IS NULL OR phase='')"
                    phase_params = [phase_norm]
                else:
                    phase_cond = " AND phase=%s"
                    phase_params = [phase_norm]


            sql = f"""
                SELECT factor_id, odd, {ts_select} AS ts{label_select}{param_select}
                FROM fonbet_odds_history
                WHERE event_id=%s{phase_cond} AND {cond}
                ORDER BY {ts_col_name} ASC
                LIMIT %s
            """
            cur.execute(sql, [effective_event_id] + phase_params + list(params) + [int(limit)])
            rows = cur.fetchall() or []

            try:
                cur.execute(
                    f"SELECT MAX({ts_select}) AS mx FROM fonbet_odds_history WHERE event_id=%s{phase_cond}",
                    (effective_event_id, *phase_params),
                )
                last_ts = (cur.fetchone() or {}).get("mx")
            except Exception:
                last_ts = None

    # HT status logic
    if half_norm == "1h":
        ht_hist = bool(rows)
        if ht_now is True:
            ht_status = "active"
        elif ht_hist:
            ht_status = "removed"
        else:
            ht_status = "never"

        if ht_status == "never":
            return {
                "outcomes": [],
                "handicap": [],
                "total": [],
                "meta": {
                    "half": "1h",
                    "half_status": "never",
                    "no_data_text": "Нет рынков 1-го тайма (HT) на Fonbet",
                    "snapshots": 0,
                    "raw_rows": 0,
                    "main_handicap": None,
                    "main_total": None,
                    "hours": int(hours),
                    "last_ts": str(last_ts) if last_ts else None,
                    "ts_col": ts_col_name,
                    "label_col": used_label_col,
                    "param_col": used_param_col,
                },
            }

    if not rows:
        return {
            "outcomes": [],
            "handicap": [],
            "total": [],
            "meta": {
                "half": "1h" if half_norm == "1h" else "ft",
                "snapshots": 0,
                "raw_rows": 0,
                "main_handicap": None,
                "main_total": None,
                "hours": int(hours),
                "last_ts": str(last_ts) if last_ts else None,
                "hint": "Нет данных за выбранный период. Увеличь hours (например 72/168).",
                "ts_col": ts_col_name,
                "label_col": used_label_col,
                "param_col": used_param_col,
            },
        }

    fids = _fids_from_rows(rows)

    # Build factor map: raw_json-aware factor catalog + shared cache
    fmap_catalog, catalog_err, catalog_cols, ctx_map = _fetch_factor_catalog_map(fids)
    try:
        fmap_shared = shared.fonbet_factor_catalog_map(force=False) or {}
    except Exception:
        fmap_shared = {}

    fmap = _merge_maps(fmap_catalog, fmap_shared)

    # If HT stored as dedicated sub-event: force *_1h to avoid mixing
    if half_norm == "1h" and effective_event_id != base_event_id:
        for fid, info in list((fmap or {}).items()):
            if not isinstance(info, dict):
                continue
            mkt = str(info.get("market") or "")
            if mkt in ("outcomes", "handicap", "total") and not mkt.endswith("_1h"):
                info2 = dict(info)
                info2["market"] = mkt + "_1h"
                fmap[int(fid)] = info2

    # Enrich by eventView (if available)
    fmap, ev_err = _enrich_from_eventview(
        base_event_id=base_event_id,
        effective_event_id=effective_event_id,
        half_norm=half_norm,
        fmap=fmap,
        fids=fids,
        lang=lang,
        sys_id=sys_id,
    )

    # Hard fallback by factor_id (when label/name are NULL)
    fmap = _apply_factor_id_fallback(fmap, half_norm)

    # Fallback infer from history label/param
    fmap = _apply_inferred_markets(rows, fmap, half_norm)

    # Final normalize suffix for requested half
    fmap = _normalize_half_markets(fmap, half_norm)

    # Teams (for handicap sign correctness)
    team1 = team2 = ""
    try:
        with shared.db_connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT team1, team2 FROM fonbet_events WHERE event_id=%s LIMIT 1", (base_event_id,))
                er = cur.fetchone() or {}
                team1 = (er.get("team1") or "").strip()
                team2 = (er.get("team2") or "").strip()
    except Exception:
        team1 = team2 = ""

    data = shared._fonbet_tables_from_rows(rows, fmap, half=half_norm, team1=team1, team2=team2)

    # Fallback: build handicap table when shared returns empty but handicap factors exist (often param=0)
    try:
        if not data.get("handicap"):
            h: List[Tuple[Any, int, float, Any]] = []
            for r in rows:
                fid = int(r.get("factor_id") or 0)
                info = fmap.get(fid) or {}
                if (info.get("market") or "") != "handicap":
                    continue
                # param can be 0 -> MUST NOT be treated as empty
                if r.get("param") is None:
                    continue
                try:
                    p = float(r.get("param")) / 100.0
                except Exception:
                    continue
                ts = r.get("ts")
                odd = r.get("odd")
                h.append((ts, fid, p, odd))

            if h:
                counts: Dict[float, int] = {}
                signed_home: Dict[float, float] = {}
                for ts, fid, p, odd in h:
                    abs_line = round(abs(p), 4)
                    counts[abs_line] = counts.get(abs_line, 0) + 1
                    lbl = str((fmap.get(fid) or {}).get("label") or "").lower()
                    is_home = ("f1" in lbl) or ("ф1" in lbl) or (lbl.strip() == "1") or (fid in (927,))
                    if is_home and abs_line not in signed_home:
                        signed_home[abs_line] = p

                def _prio(x: float) -> int:
                    frac = round(abs(x) % 1.0, 4)
                    if abs(frac - 0.5) < 1e-6:
                        return 0
                    if abs(frac - 0.25) < 1e-6 or abs(frac - 0.75) < 1e-6:
                        return 1
                    return 2

                main_abs = sorted(counts.keys(), key=lambda x: (_prio(x), -counts.get(x, 0), x))[0]

                home_line = signed_home.get(main_abs)
                if home_line is None:
                    home_line = 0.0 if main_abs == 0 else -float(main_abs)

                by_ts: Dict[str, Dict[str, Any]] = {}
                for ts, fid, p, odd in h:
                    if round(abs(p), 4) != main_abs:
                        continue
                    ts_s = str(ts)
                    row = by_ts.get(ts_s)
                    if row is None:
                        row = {"Time": ts_s, "H1": None, "Handicap": float(home_line), "H2": None}
                        by_ts[ts_s] = row

                    lbl = str((fmap.get(fid) or {}).get("label") or "").lower()
                    is_home = ("f1" in lbl) or ("ф1" in lbl) or (lbl.strip() == "1") or (fid in (927,))
                    if is_home:
                        row["H1"] = odd
                    else:
                        row["H2"] = odd

                data["handicap"] = [by_ts[k] for k in sorted(by_ts.keys())]
                data.setdefault("meta", {})
                data["meta"]["main_handicap"] = float(home_line)
    except Exception:
        pass

    data.setdefault("meta", {})
    data["meta"]["hours"] = int(hours)
    data["meta"]["last_ts"] = str(last_ts) if last_ts else None
    data["meta"]["ts_col"] = ts_col_name
    data["meta"]["label_col"] = used_label_col
    data["meta"]["param_col"] = used_param_col
    if half_norm == "1h":
        data["meta"]["half_status"] = ht_status

    if catalog_err:
        data["meta"]["catalog_err"] = catalog_err
    if catalog_cols:
        data["meta"]["catalog_cols"] = catalog_cols

    if ev_err:
        data["meta"]["eventview_err"] = ev_err

    # Debug: markets seen
    try:
        markets = {str((fmap.get(fid) or {}).get("market") or "") for fid in fids}
        data["meta"]["markets_seen"] = sorted(m for m in markets if m)
    except Exception:
        pass

    # Debug: show first factors classification context
    if int(debug or 0) == 1:
        dbg: List[Dict[str, Any]] = []
        for fid in fids[:40]:
            info = fmap.get(fid) or {}
            dbg.append(
                {
                    "factor_id": fid,
                    "market": (info.get("market") or ""),
                    "label": (info.get("label") or ""),
                    "param": info.get("param"),
                    "ctx": (ctx_map.get(fid) or "")[:260],
                }
            )
        data["meta"]["debug_factors"] = dbg

    return data
