#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
patch_fonbet_fix_v5.py  (single file, overwrite-friendly)
========================================================

Idempotent patcher for Inforadar-Pro (patches files in place, makes .bak_* backups).
This version fixes the *exact* traceback you showed:

ValueError: unsupported format character 'Y' ... in PyMySQL mogrify
coming from /app/app_22bet.py::_sql_fonbet_events (Flask UI) and/or fonbet_api.

Root cause:
PyMySQL formats params using Python %-formatting. Any literal % inside SQL string
literals (DATE_FORMAT('%Y...'), LIKE '%abc%') must be escaped as %% or it crashes.

What this patch does:
1) Adds a safe monkey-patch for PyMySQL Cursor.execute/executemany that escapes
   % only inside single-quoted SQL literals (keeps existing %%).
   Applied to:
     - services/fonbet_api/main.py
     - inforadar_ui/app_22bet.py (and common alternative paths)

2) Adds FastAPI 500 JSON handler to services/fonbet_api/main.py (so UI won't parse HTML/text).

Apply (PowerShell):
  cd D:\Inforadar_Pro
  python .\patch_fonbet_fix_v5.py

Then rebuild WITHOUT pulling mysql (avoids your docker blob I/O error on mysql image):
  docker-compose up -d --no-deps --build --force-recreate fonbet_api inforadar_ui
(or if rebuild is blocked, just restart containers)
  docker restart fonbet_api inforadar_ui
"""

from __future__ import annotations

import re
import sys
import shutil
from pathlib import Path
from datetime import datetime


# idempotency markers
MARK_SQL_PATCH = "percent_escape_patched__inforadar"
MARK_JSON_HANDLER = "_inforadar_json_500_handler"


SQL_PATCH_BLOCK = r"""
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
    if getattr(Cursor.execute, "{mark}", False):
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

    setattr(_exec, "{mark}", True)
    Cursor.execute = _exec
    Cursor.executemany = _many


_patch_pymysql_execute__inforadar()
# --- end Inforadar hotfix ---
""".replace("{mark}", MARK_SQL_PATCH)


JSON_HANDLER_BLOCK = r"""
# --- Inforadar hotfix: always return JSON on 500 for UI ---
# Starlette default returns plain text "Internal Server Error". UI ожидает JSON.
try:
    import os as _os
    import traceback as _traceback
    import logging as _logging
    from starlette.requests import Request as _Request
    from starlette.responses import JSONResponse as _JSONResponse

    @app.exception_handler(Exception)  # type: ignore[name-defined]
    async def {mark}(request: _Request, exc: Exception):
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
""".replace("{mark}", MARK_JSON_HANDLER)


def backup_file(path: Path) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    b = path.with_suffix(path.suffix + f".bak_{ts}")
    shutil.copy2(path, b)
    return b


def insert_after(text: str, anchor: re.Pattern, block: str) -> tuple[str, bool]:
    m = anchor.search(text)
    if not m:
        return text, False
    idx = m.end()
    ins = "\n" + block.strip("\n") + "\n"
    return text[:idx] + ins + text[idx:], True


def patch_sql_monkeypatch(file_path: Path) -> int:
    if not file_path.exists():
        return 0

    raw = file_path.read_text(encoding="utf-8", errors="ignore")
    if MARK_SQL_PATCH in raw:
        return 0

    new = raw
    changed = False

    # insert after "import pymysql" if possible
    anchor = re.compile(r"^\s*import\s+pymysql\s*(?:#.*)?$", re.M)
    if anchor.search(new):
        new, ok = insert_after(new, anchor, SQL_PATCH_BLOCK)
        if ok:
            changed = True
    else:
        # fallback: after last import line near top
        anchor2 = re.compile(r"^(?:from\s+\S+\s+import\s+.+|import\s+\S+)(?:\s+#.*)?\s*$", re.M)
        last = None
        for m in anchor2.finditer(new[:8000]):
            last = m
        if last:
            idx = last.end()
            new = new[:idx] + "\n" + SQL_PATCH_BLOCK.strip("\n") + "\n" + new[idx:]
            changed = True

    if not changed:
        print(f"[warn] cannot insert SQL patch into {file_path}")
        return 0

    b = backup_file(file_path)
    file_path.write_text(new, encoding="utf-8")
    print(f"[ok] SQL % hotfix inserted into {file_path} (backup {b.name})")
    return 1


def patch_fastapi_json_500(main_path: Path) -> int:
    if not main_path.exists():
        return 0

    raw = main_path.read_text(encoding="utf-8", errors="ignore")
    if MARK_JSON_HANDLER in raw:
        return 0

    new = raw
    m = re.search(r"^\s*app\s*=\s*FastAPI\s*\(", new, flags=re.M)
    if not m:
        print("[warn] cannot find app = FastAPI( in main.py for JSON handler")
        return 0

    close = new.find(")", m.end())
    if close == -1:
        print("[warn] found 'app = FastAPI(' but cannot find closing ')'")
        return 0

    idx = close + 1
    new = new[:idx] + "\n" + JSON_HANDLER_BLOCK.strip("\n") + "\n" + new[idx:]

    b = backup_file(main_path)
    main_path.write_text(new, encoding="utf-8")
    print(f"[ok] JSON 500 handler inserted into {main_path} (backup {b.name})")
    return 1


def main() -> int:
    repo_root = Path(__file__).resolve().parent
    print(f"[repo] {repo_root}")

    # targets
    targets = []

    # fonbet_api main.py
    main_py = repo_root / "services" / "fonbet_api" / "main.py"
    targets.append(("fonbet_api.main.py", main_py))

    # UI app_22bet.py (try common paths)
    candidates = [
        repo_root / "inforadar_ui" / "app_22bet.py",
        repo_root / "services" / "inforadar_ui" / "app_22bet.py",
        repo_root / "app_22bet.py",
    ]
    ui_path = next((p for p in candidates if p.exists()), candidates[0])
    targets.append(("inforadar_ui.app_22bet.py", ui_path))

    changed = 0

    # 1) SQL monkeypatch in both
    for name, path in targets:
        c = patch_sql_monkeypatch(path)
        if c:
            print(f"  patched: {name}")
        changed += c

    # 2) JSON handler only in fonbet_api main.py
    changed += patch_fastapi_json_500(main_py)

    if changed == 0:
        print("[done] nothing changed (already patched or files not found)")
    else:
        print(f"[done] patched files: {changed}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
