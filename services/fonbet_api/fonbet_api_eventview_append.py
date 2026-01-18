# --- Fonbet API: add eventView endpoint for UI compatibility ---
# Paste this block at the END of services/fonbet_api/main.py (or /app/main.py in the container build context).

from fastapi import HTTPException
import os
import requests


def _fonbet_proxy_dict():
    """
    Prefer prematch proxy if present; fallback to generic FONBET_PROXY / HTTP(S)_PROXY.
    """
    p = (os.getenv("FONBET_PREMATCH_PROXY") or "").strip()
    if not p:
        p = (os.getenv("FONBET_PROXY") or "").strip()
    if not p:
        p = (os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY") or "").strip()
    if not p:
        return None
    return {"http": p, "https": p}


def _fonbet_line_base():
    """
    Fonbet CY line base used by prematch parser.
    You can override with FONBET_LINE_BASE in .env if needed.
    """
    return (os.getenv("FONBET_LINE_BASE") or "https://line01.cy8cff-resources.com").rstrip("/")


# IMPORTANT: assumes your FastAPI app instance is named `app`
@app.get("/fonbet/event/{event_id}/eventView")
def fonbet_event_view(event_id: int, lang: str = "ru", sysId: int = 1):
    """
    Proxy upstream eventView (needed by inforadar_ui /api/fonbet/event/<id>/eventView).
    """
    base = _fonbet_line_base()
    url = f"{base}/line/eventView"
    proxies = _fonbet_proxy_dict()

    try:
        r = requests.get(
            url,
            params={"eventId": event_id, "lang": lang, "sysId": sysId},
            proxies=proxies,
            timeout=25,
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"eventView fetch failed: {e}")
