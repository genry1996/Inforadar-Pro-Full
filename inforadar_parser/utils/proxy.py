from __future__ import annotations
import os
from urllib.parse import quote

def build_proxy_url(prefix: str) -> str | None:
    """
    Build proxy URL from:
      {PREFIX}_PROXY_SERVER=http://IP:PORT
      {PREFIX}_PROXY_USERNAME=USER
      {PREFIX}_PROXY_PASSWORD=PASS

    returns: http://USER:PASS@IP:PORT
    """
    server = (os.getenv(f"{prefix}_PROXY_SERVER", "") or "").strip()
    user = (os.getenv(f"{prefix}_PROXY_USERNAME", "") or "").strip()
    pwd = (os.getenv(f"{prefix}_PROXY_PASSWORD", "") or "").strip()

    if not server:
        return None

    if "://" in server:
        scheme, rest = server.split("://", 1)
    else:
        scheme, rest = "http", server

    if user and pwd:
        return f"{scheme}://{quote(user)}:{quote(pwd)}@{rest}"

    return f"{scheme}://{rest}"
