


def get_db_conn():
    """Compatibility helper (older code paths expect get_db_conn())."""
    return shared.db_connect()
import os
import json
import ast
import re
import importlib.util
import time
from datetime import datetime
from typing import Optional, Any, Dict, List, Set, Tuple

from fastapi import FastAPI, Query, Path


# --- Inforadar hotfix: PyMySQL percent escape (DATE_FORMAT/LIKE with params) ---
# Problem: PyMySQL uses Python %-formatting for params. Any literal % inside SQL query
# (inside quotes like '%Y-%m-%d' or LIKE '%abc%') must be escaped as %% or PyMySQL crashes.
def _escape_sql_percent_literals__inforadar(q: str) -> str:
    # Escapes % only inside single-quoted SQL literals.
    # Keeps already-escaped %% intact.
    out = []
    i = 0
    in_str = False
    n = len(q)
    while i < n:
        ch = q[i]
        if not in_str:
            if ch == "'":
                in_str = True
                out.append(ch)
                i += 1
                continue
            out.append(ch)
            i += 1
            continue

        # inside single-quoted literal
        if ch == "'":
            # SQL escaped quote as '' (two single quotes)
            if i + 1 < n and q[i + 1] == "'":
                out.append("''")
                i += 2
                continue
            in_str = False
            out.append(ch)
            i += 1
            continue

        if ch == "%":
            # keep already escaped %%
            if i + 1 < n and q[i + 1] == "%":
                out.append("%%")
                i += 2
                continue
            out.append("%%")
            i += 1
            continue

        out.append(ch)
        i += 1

    return "".join(out)


def _patch_pymysql_execute__inforadar():
    try:
        import pymysql  # noqa
# --- Inforadar hotfix: PyMySQL percent escape (DATE_FORMAT/LIKE with params) ---
# Problem: PyMySQL uses Python %-formatting for params. Any literal % inside SQL query
# (inside quotes like '%Y-%m-%d' or LIKE '%abc%') must be escaped as %% or PyMySQL crashes.
def _escape_sql_percent_literals__inforadar(q: str) -> str:
    # Escapes % only inside single-quoted SQL literals.
    # Keeps already-escaped %% intact.
    out = []
    i = 0
    in_str = False
    n = len(q)
    while i < n:
        ch = q[i]
        if not in_str:
            if ch == "'":
                in_str = True
                out.append(ch)
                i += 1
                continue
            out.append(ch)
            i += 1
            continue

        # inside single-quoted literal
        if ch == "'":
            # SQL escaped quote as '' (two single quotes)
            if i + 1 < n and q[i + 1] == "'":
                out.append("''")
                i += 2
                continue
            in_str = False
            out.append(ch)
            i += 1
            continue

        if ch == "%":
            # keep already escaped %%
            if i + 1 < n and q[i + 1] == "%":
                out.append("%%")
                i += 2
                continue
            out.append("%%")
            i += 1
            continue

        out.append(ch)
        i += 1

    return "".join(out)


def _patch_pymysql_execute__inforadar():
    try:
        import pymysql  # noqa: F401
        from pymysql.cursors import Cursor
    except Exception:
        return

    # idempotent: patch only once
    if getattr(Cursor.execute, "percent_escape_patched__inforadar", False):
        return

    _orig_execute = Cursor.execute
    _orig_executemany = Cursor.executemany

    def _exec(self, query, args=None):
        if args is not None and isinstance(query, str) and "%" in query and "'" in query:
            query = _escape_sql_percent_literals__inforadar(query)
        return _orig_execute(self, query, args)

    def _many(self, query, args):
        if args is not None and isinstance(query, str) and "%" in query and "'" in query:
            query = _escape_sql_percent_literals__inforadar(query)
        return _orig_executemany(self, query, args)

    setattr(_exec, "percent_escape_patched__inforadar", True)
    Cursor.execute = _exec
    Cursor.executemany = _many


_patch_pymysql_execute__inforadar()
# --- end Inforadar hotfix ---

        from pymysql.cursors import Cursor
    except Exception:
        return

    # idempotent: patch only once
    if getattr(Cursor.execute, "percent_escape_patched", False):
        return

    _orig_execute = Cursor.execute
    _orig_executemany = Cursor.executemany

    def _exec(self, query, args=None):
        if args is not None and isinstance(query, str) and "%" in query and "'" in query:
            query = _escape_sql_percent_literals__inforadar(query)
        return _orig_execute(self, query, args)

    def _many(self, query, args):
        if args is not None and isinstance(query, str) and "%" in query and "'" in query:
            query = _escape_sql_percent_literals__inforadar(query)
        return _orig_executemany(self, query, args)

    setattr(_exec, "percent_escape_patched", True)
    Cursor.execute = _exec
    Cursor.executemany = _many


_patch_pymysql_execute__inforadar()
# --- end Inforadar hotfix ---

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


# --- Inforadar hotfix: always return JSON on 500 for UI ---
# Starlette default returns plain text "Internal Server Error". UI ожидает JSON.
try:
    import os as _os
    import traceback as _traceback
    from starlette.requests import Request as _Request
    from starlette.responses import JSONResponse as _JSONResponse
    import logging as _logging

    @app.exception_handler(Exception)  # type: ignore[name-defined]
    async def _inforadar_json_500_handler(request: _Request, exc: Exception):
        _logging.exception("Unhandled exception in fonbet_api: %s", exc)
        dbg = (_os.getenv("FONBET_API_DEBUG", "0") or "").lower() in ("1", "true", "yes")
        if dbg:
            return _JSONResponse(
                status_code=500,
                content={
                    "error": str(exc),
                    "type": type(exc).__name__,
                    "traceback": _traceback.format_exc(),
                },
            )
        return _JSONResponse(status_code=500, content={"error": "Internal Server Error"})
except Exception:
    pass
# --- end Inforadar hotfix ---

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


def _try_int(v: Any) -> Optional[int]:
    try:
        if v is None or isinstance(v, bool):
            return None
        return int(v)
    except Exception:
        return None


def _pick_existing(cols: Set[str], candidates: List[str]) -> Optional[str]:
    for c in candidates:
        if c in cols:
            return c
    return None


def _history_table_and_cols(cur) -> Tuple[Optional[str], Set[str]]:
    """Pick best history table and return its columns."""
    for t in ("fonbet_odds_history", "odds_history"):
        try:
            cur.execute("SHOW TABLES LIKE %s", (t,))
            if not cur.fetchone():
                continue
            cur.execute(f"SHOW COLUMNS FROM {t}")
            rows = cur.fetchall() or []
            cols = {str(r.get("Field") or "").strip() for r in rows if isinstance(r, dict)}
            cols = {c for c in cols if c}
            return t, cols
        except Exception:
            continue
    return None, set()


def _fetch_odds_history_rows(
    event_id: int,
    half: str = "ft",
    hours: int = 12,
    limit: int = 8000,
) -> Tuple[List[Dict[str, Any]], Optional[str], Optional[str], Optional[str], Optional[str]]:
    """Fetch odds-history rows for a single Fonbet event.

    This service has to tolerate different schemas and timestamp formats:
    - time-like column: DATETIME (time/created_at/...)
    - numeric ts column: unix seconds / unix ms / YYYYMMDDHHMMSS (14 digits)
    - string ts column: 'YYYY-MM-DD HH:MM:SS'

    We normalize timestamps to make the 'hours' filter work reliably.
    """
    conn = get_db_conn()
    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        table, cols = _detect_history_table_and_cols(cur)
        if not table:
            return [], None, None, None, None

        # ---- detect columns
        # time column (DATETIME)
        time_col = None
        for c in ("time", "created_at", "updated_at", "dt", "datetime", "ts_time"):
            if c in cols:
                time_col = c
                break

        # numeric/string timestamp column
        ts_col = None
        for c in ("ts", "timestamp", "ts_ms", "ts_sec"):
            if c in cols:
                ts_col = c
                break

        # label/param columns (used by market builder)
        label_col = "label" if "label" in cols else ("name" if "name" in cols else None)
        param_col = "param" if "param" in cols else ("line" if "line" in cols else None)

        # half column (ft/ht)
        half_col = None
        for c in ("half", "period", "part"):
            if c in cols:
                half_col = c
                break

        where = ["event_id = %s"]
        params: List[Any] = [int(event_id)]

        if half_col:
            half_norm = (half or "ft").strip().lower()
            half_db = "1h" if half_norm in ("ht", "1h", "1") else "ft"
            where.append(f"{half_col} = %s")
            params.append(half_db)

        # ---- decide how to filter/order by time
        ts_norm_expr = None
        ts_kind = None  # "time", "numeric", "str_dt", "unknown"

        if time_col:
            ts_kind = "time"
            where.append(f"{time_col} >= DATE_SUB(NOW(), INTERVAL %s HOUR)")
            params.append(int(hours))
            order_by = f"{time_col} DESC"
        elif ts_col:
            # peek one sample
            sample = None
            try:
                # try common pk names first
                order_pk = "id" if "id" in cols else (time_col if time_col else ts_col)
                cur.execute(
                    f"SELECT {ts_col} AS v FROM {table} WHERE event_id=%s ORDER BY {order_pk} DESC LIMIT 1",
                    (int(event_id),),
                )
                sample = (cur.fetchone() or {}).get("v")
            except Exception:
                sample = None

            if isinstance(sample, (int, float)) or (isinstance(sample, str) and sample.strip().isdigit()):
                ts_kind = "numeric"
                raw = f"CAST({ts_col} AS UNSIGNED)"
                ts_norm_expr = (
                    "CASE "
                    f"WHEN {raw} >= 10000000000000 THEN UNIX_TIMESTAMP(STR_TO_DATE(CAST({ts_col} AS CHAR), '%Y%m%d%H%i%s')) "
                    f"WHEN {raw} >= 1000000000000 THEN FLOOR({raw}/1000) "
                    f"ELSE {raw} "
                    "END"
                )
                where.append(f"{ts_norm_expr} >= UNIX_TIMESTAMP(DATE_SUB(NOW(), INTERVAL %s HOUR))")
                params.append(int(hours))
                order_by = f"{ts_norm_expr} DESC"
            elif isinstance(sample, str) and re.match(r"^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}", sample.strip()):
                ts_kind = "str_dt"
                dt_expr = f"STR_TO_DATE({ts_col}, '%Y-%m-%d %H:%i:%s')"
                where.append(f"{dt_expr} >= DATE_SUB(NOW(), INTERVAL %s HOUR)")
                params.append(int(hours))
                order_by = f"{dt_expr} DESC"
            else:
                ts_kind = "unknown"
                order_by = f"id DESC" if "id" in cols else "event_id DESC"
        else:
            ts_kind = "unknown"
            order_by = f"id DESC" if "id" in cols else "event_id DESC"

        # ---- build query
        select_parts = ["h.*"]
        ts_col_name = time_col or ts_col

        if ts_kind == "numeric" and ts_norm_expr:
            # override/standardize 'ts' to a readable datetime string for the UI
            select_parts.append(f"FROM_UNIXTIME({ts_norm_expr}) AS ts")
            ts_col_name = "ts"
        elif ts_kind == "time" and time_col:
            # keep consistent key for UI
            select_parts.append(f"{time_col} AS ts")
            ts_col_name = "ts"

        sql = f"""
        SELECT {', '.join(select_parts)}
        FROM {table} h
        WHERE {' AND '.join(where)}
        ORDER BY {order_by}
        LIMIT %s
        """
        params.append(int(limit))

        try:
            cur.execute(sql, params)
            rows = cur.fetchall() or []
        except Exception:
            rows = []

        return rows, ts_col_name, label_col, param_col, half_col
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


def _classify_half_text(txt: str) -> str:
    """
    Detect whether factor/label belongs to 1st half (HT / 1H).
    Returns: "1h" or "ft"
    """
    if not txt:
        return "ft"
    s = str(txt).lower()

    # RU hints
    if re.search(r"\b(1[-\s]?й|1)\s*тайм\b", s):
        return "1h"
    if re.search(r"\bперв(ый|ого)\s*тайм\b", s):
        return "1h"
    if re.search(r"\bв\s*1[-\s]?м\s*тайм", s):
        return "1h"

    # EN hints
    if re.search(r"\b(1st|first)\s*half\b", s):
        return "1h"
    if re.search(r"\bhalf\s*1\b", s):
        return "1h"

    # Short hints (careful but useful for Fonbet context strings)
    if re.search(r"\b(1h|ht)\b", s):
        return "1h"

    return "ft"


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


def _merge_fmaps(primary: Dict[int, Any], secondary: Dict[int, Any]) -> Dict[int, Any]:
    """Backward-compatible alias: older code called this _merge_fmaps."""
    return _merge_maps(primary, secondary)


def _enrich_fmap_with_catalog(
    fmap: Dict[int, Any],
    catalog_map: Dict[int, Any],
    half_norm: str,
) -> Dict[int, Any]:
    """
    Merge factor map with catalog-derived info.
    We intentionally keep it conservative: only fill missing market/label/param.
    """
    try:
        return _merge_maps(fmap or {}, catalog_map or {})
    except Exception:
        return fmap or {}



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
    Infer market from odds_history row label/param when catalog/eventView are missing.
    IMPORTANT: half (FT vs 1H) must be inferred from label/context, NOT from requested half,
    otherwise FT lines will leak into HT.
    """
    if not rows:
        return fmap

    if fmap is None:
        fmap = {}

    for r in rows:
        fid = _try_int(r.get("factor_id"))
        if fid is None:
            continue

        info = fmap.get(fid)
        if not isinstance(info, dict):
            info = {}

        cur_m = str(info.get("market") or "").strip()
        if cur_m and cur_m != "other":
            continue

        label = r.get("label") or r.get("name") or ""
        inferred_base = _infer_market_from_row(label, r.get("param"))
        if inferred_base == "other":
            continue

        half_hint = info.get("half_hint") or _classify_half_text(label)

        inferred = inferred_base
        if half_hint == "1h" and inferred_base in ("outcomes", "handicap", "total"):
            inferred = inferred_base + "_1h"

        info2 = dict(info)
        info2["market"] = inferred
        info2["half_hint"] = half_hint

        if _is_noneish(info2.get("label")):
            info2["label"] = label

        fmap[int(fid)] = info2

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
    Strictly prevent mixing FT and 1H markets.

    - For FT request: drop *_1h markets (set to "other").
    - For 1H request: keep only *_1h markets (FT markets become "other").
    """
    if not fmap:
        return fmap

    if half_norm not in ("ft", "1h"):
        return fmap

    for fid, info in list(fmap.items()):
        if not isinstance(info, dict):
            continue

        m = str(info.get("market") or "").strip()
        if not m:
            continue

        if half_norm == "ft":
            # drop first-half markets
            if m.endswith("_1h"):
                info2 = dict(info)
                info2["market"] = "other"
                fmap[int(fid)] = info2
        else:
            # keep only first-half markets
            if m in ("outcomes", "handicap", "total"):
                info2 = dict(info)
                info2["market"] = "other"
                fmap[int(fid)] = info2

    return fmap


def _filter_rows_by_half(rows: List[Dict[str, Any]], fmap: Dict[int, Any], half_norm: str) -> List[Dict[str, Any]]:
    """
    Filter odds_history rows so that:
      - for FT: exclude factors classified as *_1h
      - for 1H: keep only factors classified as *_1h
    """
    if not rows:
        return rows
    if not fmap or half_norm not in ("ft", "1h"):
        return rows

    if half_norm == "ft":
        bad = set()
        for fid, info in fmap.items():
            if isinstance(info, dict) and str(info.get("market") or "").endswith("_1h"):
                bad.add(int(fid))
        if not bad:
            return rows
        return [r for r in rows if _try_int(r.get("factor_id")) not in bad]

    good = set()
    for fid, info in fmap.items():
        if isinstance(info, dict) and str(info.get("market") or "").endswith("_1h"):
            good.add(int(fid))
    if not good:
        return []
    return [r for r in rows if _try_int(r.get("factor_id")) in good]




    if half_norm not in ("ft", "1h"):
        return fmap

    for fid, info in list(fmap.items()):
        if not isinstance(info, dict):
            continue

        m = str(info.get("market") or "").strip()
        if not m:
            continue

        if half_norm == "ft":
            if m.endswith("_1h"):
                info2 = dict(info)
                info2["market"] = "other"
                fmap[int(fid)] = info2
        else:
            if m in ("outcomes", "handicap", "total"):
                info2 = dict(info)
                info2["market"] = "other"
                fmap[int(fid)] = info2

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



def _apply_factor_id_fallback(fmap: Dict[int, Any], half_norm: str, force_1h: bool = False) -> Dict[int, Any]:
    """
    Hard fallback for the most common Fonbet factor_ids when catalog/eventView do not provide labels/markets.

    CRITICAL:
    - Do NOT blindly mark factors as 1H just because requested half=1h.
      That makes FT lines appear in HT tab for matches that do not have 1H markets.
    - Only force "_1h" when we are confident the whole event_id represents 1H (child event_id).
    """
    if fmap is None:
        fmap = {}

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

        mkt = mkt_base + "_1h" if force_1h else mkt_base

        info2 = dict(info)
        info2["market"] = mkt
        if "half_hint" not in info2:
            info2["half_hint"] = "1h" if force_1h else "ft"

        if _is_noneish(info2.get("label")):
            info2["label"] = lbl

        fmap[int(fid)] = info2

    return fmap





def _try_float(v: Any) -> Optional[float]:
    try:
        if v is None:
            return None
        if isinstance(v, bool):
            return None
        return float(v)
    except Exception:
        return None


def _norm_line_value(v: Any) -> Any:
    """
    Normalize Fonbet line values stored as 250 -> 2.5, 150 -> 1.5, 100 -> 1.0.
    Leaves already-normal values (<=20 by abs) unchanged.
    """
    fv = _try_float(v)
    if fv is None:
        return v
    if abs(fv) >= 20:
        return fv / 100.0
    return fv


def _ui_add_aliases_inplace(payload: Dict[str, Any]) -> None:
    """
    Add backward-compatible aliases for UI rendering:
    - outcomes: time, p1/px/p2, k1/kx/k2
    - handicap/total: time, hcp/total, alg1/alg2, Alg.1/Alg.2
    Also normalizes Total/main_total if stored as 250 -> 2.5.
    This is safe: only adds keys / normalizes obvious line scalings.
    """
    if not isinstance(payload, dict):
        return

    # outcomes (1X2)
    for r in payload.get("outcomes") or []:
        if not isinstance(r, dict):
            continue
        if "Time" in r and "time" not in r:
            r["time"] = r.get("Time")
        # JS cannot do row.1, so provide dot-safe aliases
        if "1" in r:
            r.setdefault("p1", r.get("1"))
            r.setdefault("k1", r.get("1"))
        if "X" in r:
            r.setdefault("px", r.get("X"))
            r.setdefault("kx", r.get("X"))
        if "2" in r:
            r.setdefault("p2", r.get("2"))
            r.setdefault("k2", r.get("2"))

    # handicap
    for r in payload.get("handicap") or []:
        if not isinstance(r, dict):
            continue
        if "Time" in r and "time" not in r:
            r["time"] = r.get("Time")
        if "Hcp" in r and "hcp" not in r:
            r["hcp"] = r.get("Hcp")
        # alg aliases
        if "Alg1" in r:
            r.setdefault("alg1", r.get("Alg1"))
            r.setdefault("Alg.1", r.get("Alg1"))
        if "Alg2" in r:
            r.setdefault("alg2", r.get("Alg2"))
            r.setdefault("Alg.2", r.get("Alg2"))
        # if dotted came from somewhere, mirror back
        if "Alg.1" in r and "Alg1" not in r:
            r["Alg1"] = r.get("Alg.1")
        if "Alg.2" in r and "Alg2" not in r:
            r["Alg2"] = r.get("Alg.2")

    # total
    for r in payload.get("total") or []:
        if not isinstance(r, dict):
            continue
        if "Time" in r and "time" not in r:
            r["time"] = r.get("Time")

        if "Total" in r:
            r["Total"] = _norm_line_value(r.get("Total"))
            r.setdefault("total", r.get("Total"))

        if "Alg1" in r:
            r.setdefault("alg1", r.get("Alg1"))
            r.setdefault("Alg.1", r.get("Alg1"))
        if "Alg2" in r:
            r.setdefault("alg2", r.get("Alg2"))
            r.setdefault("Alg.2", r.get("Alg2"))
        if "Alg.1" in r and "Alg1" not in r:
            r["Alg1"] = r.get("Alg.1")
        if "Alg.2" in r and "Alg2" not in r:
            r["Alg2"] = r.get("Alg.2")

    # meta lines
    meta = payload.get("meta")
    if isinstance(meta, dict):
        if "main_total" in meta:
            meta["main_total"] = _norm_line_value(meta.get("main_total"))
        if "main_handicap" in meta:
            meta["main_handicap"] = _norm_line_value(meta.get("main_handicap"))
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
    event_id: int,
    half: str = "ft",
    hours: int = 12,
    limit: int = 8000,
    debug: int = 0,
) -> Dict[str, Any]:
    """
    Return pre-aggregated tables for UI (1X2, Handicap mainline, Total mainline).
    Fixes:
      - HT/1H must not show FT markets when 1H markets are absent.
      - If 1H markets existed earlier but are now removed -> show last history with half_status="removed".
    """
    half_norm = shared._fonbet_norm_half(half)  # "ft" or "1h"
    base_event_id = int(event_id)
    effective_event_id = base_event_id

    # Try to fetch eventView to get teams and detect whether HT exists now
    ev: Optional[Dict[str, Any]] = None
    ht_now = False
    try:
        ev = shared._fonbet_fetch_event_view(base_event_id)
        if isinstance(ev, dict):
            # Most reliable: explicit child-event id for 1H, if present
            child = ev.get("child_1h_event_id") or ev.get("childEventId") or ev.get("eventId1h")
            if child:
                ht_now = True
            else:
                # Fallback: if factor_map already contains *_1h markets
                try:
                    fmap_now = shared._fonbet_extract_factor_map(ev) or {}
                    for _fid, info in fmap_now.items():
                        if isinstance(info, dict) and str(info.get("market") or "").endswith("_1h"):
                            ht_now = True
                            break
                except Exception:
                    pass
    except Exception:
        ev = None

    # If HT requested, try to resolve child 1H event_id (if book provides it)
    if half_norm == "1h":
        try:
            effective_event_id = shared._fonbet_resolve_1h_event_id(base_event_id, ev)
        except Exception:
            effective_event_id = base_event_id
        if effective_event_id != base_event_id:
            ht_now = True

    # Pull history rows
    rows, last_ts, ts_col_name, label_col_name, param_col_name = _fetch_odds_history_rows(
        event_id=effective_event_id,
        hours=int(hours),
        limit=int(limit),
    )
    used_label_col = label_col_name or "label"
    used_param_col = param_col_name or "param"

    # No DB rows at all
    if not rows:
        ht_status = None
        if half_norm == "1h":
            ht_status = "active" if ht_now else "never"
        return {
            "outcomes": [],
            "handicap": [],
            "total": [],
            "meta": {
                "half": half_norm,
                "half_status": ht_status,
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
                "catalog_cols": ["factor_id", "name", "raw_json", "updated_at"],
                "markets_seen": [],
            },
        }

    fids = _fids_from_rows(rows)

    # Factor map from event view + shared parsing
    fmap: Dict[int, Any] = {}
    try:
        if isinstance(ev, dict):
            fmap = shared._fonbet_extract_factor_map(ev) or {}
    except Exception:
        fmap = {}

    try:
        fmap = _merge_fmaps(fmap, shared._fonbet_parse_factors_from_eventview(ev) if isinstance(ev, dict) else {})
    except Exception:
        pass
    # Catalog (name/raw_json) for factor_ids we see in history
    catalog_map, catalog_err, catalog_cols, ctx_map = _fetch_factor_catalog_map(fids)

    # Enrich/normalize factor map with catalog context
    try:
        fmap = _enrich_fmap_with_catalog(fmap, catalog_map, half_norm)
    except Exception:
        pass

    # If we have a dedicated child event_id for 1H - treat all base markets as 1H inside it
    if half_norm == "1h" and effective_event_id != base_event_id:
        for fid, info in list(fmap.items()):
            if not isinstance(info, dict):
                continue
            m = str(info.get("market") or "")
            if m in ("outcomes", "handicap", "total"):
                info2 = dict(info)
                info2["market"] = m + "_1h"
                info2["half_hint"] = "1h"
                fmap[int(fid)] = info2

    # Hard fallback for common factor_ids (only force 1H when child event_id is used)
    fmap = _apply_factor_id_fallback(
        fmap,
        half_norm,
        force_1h=(half_norm == "1h" and effective_event_id != base_event_id),
    )

    # Infer missing markets from label/param (half inferred from text)
    fmap = _apply_inferred_markets(rows, fmap, half_norm)

    # Final strict normalization (no mixing)
    fmap = _normalize_half_markets(fmap, half_norm)

    # Filter rows by half (core fix)
    rows = _filter_rows_by_half(rows, fmap, half_norm)

    # HT status AFTER filtering
    ht_status = None
    if half_norm == "1h":
        ht_hist = bool(rows)
        if ht_now:
            ht_status = "active"
        else:
            ht_status = "removed" if ht_hist else "never"

        if ht_status == "never":
            return {
                "outcomes": [],
                "handicap": [],
                "total": [],
                "meta": {
                    "half": half_norm,
                    "half_status": ht_status,
                    "snapshots": 0,
                    "raw_rows": 0,
                    "main_handicap": None,
                    "main_total": None,
                    "hours": int(hours),
                    "last_ts": str(last_ts) if last_ts else None,
                    "ts_col": ts_col_name,
                    "label_col": used_label_col,
                    "param_col": used_param_col,
                    "catalog_cols": ["factor_id", "name", "raw_json", "updated_at"],
                    "markets_seen": [],
                },
            }

    # After filtering we might have no rows (e.g., HT active but history window too small)
    if not rows:
        return {
            "outcomes": [],
            "handicap": [],
            "total": [],
            "meta": {
                "half": half_norm,
                "half_status": ht_status,
                "snapshots": 0,
                "raw_rows": 0,
                "main_handicap": None,
                "main_total": None,
                "hours": int(hours),
                "last_ts": str(last_ts) if last_ts else None,
                "ts_col": ts_col_name,
                "label_col": used_label_col,
                "param_col": used_param_col,
                "catalog_cols": ["factor_id", "name", "raw_json", "updated_at"],
                "markets_seen": [],
            },
        }

    team1 = (ev.get("team1") if isinstance(ev, dict) else None) or (ev.get("homeTeam") if isinstance(ev, dict) else None) or ""
    team2 = (ev.get("team2") if isinstance(ev, dict) else None) or (ev.get("awayTeam") if isinstance(ev, dict) else None) or ""

    data = shared._fonbet_tables_from_rows(
        rows=rows,
        fmap=fmap,
        half=half_norm,
        team1=team1,
        team2=team2,
        hours=int(hours),
        last_ts=last_ts,
        ts_col=ts_col_name,
        label_col=used_label_col,
        param_col=used_param_col,
    )

    if not isinstance(data, dict):
        data = {"outcomes": [], "handicap": [], "total": [], "meta": {"half": half_norm}}

    data.setdefault("meta", {})
    if ht_status is not None:
        data["meta"]["half_status"] = ht_status

    if debug:
        dbg = []
        for fid in sorted(set(_fids_from_rows(rows))):
            info = fmap.get(fid) if fmap else None
            if not isinstance(info, dict):
                info = {}
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

    # UI compatibility: add safe aliases and normalize obvious line scalings
    try:
        _ui_add_aliases_inplace(data)
    except Exception:
        pass

    return data
