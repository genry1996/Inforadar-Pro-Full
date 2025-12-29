import argparse
import base64
import json
import os
import re
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse


def safe_name(url: str) -> str:
    p = urlparse(url)
    path = re.sub(r"[^a-zA-Z0-9]+", "_", p.path.strip("/"))[:120]
    return f"{p.netloc}_{path or 'root'}"


def find_latest_har(har_dir: str) -> str:
    p = Path(har_dir)
    files = sorted(p.glob("*.har"), key=lambda x: x.stat().st_mtime, reverse=True)
    if not files:
        raise FileNotFoundError(f"No .har files found in: {har_dir}")
    return str(files[0])


def decode_har_text(content: dict) -> Optional[str]:
    text = content.get("text")
    if not text:
        return None
    encoding = content.get("encoding")
    if encoding == "base64":
        try:
            return base64.b64decode(text).decode("utf-8", errors="replace")
        except Exception:
            return text
    return text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--har", default="", help="Path to .har (default: latest from data/fonbet_probe)")
    ap.add_argument("--har-dir", default="data/fonbet_probe", help="Directory with HAR files")
    ap.add_argument("--out", default="data/fonbet_probe/extracted", help="Output directory for saved responses")
    ap.add_argument("--top", type=int, default=50, help="How many endpoints to print")
    ap.add_argument("--save", type=int, default=10, help="How many response bodies to save")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    har_path = args.har.strip() or find_latest_har(args.har_dir)
    print(f"Using HAR: {har_path}")

    with open(har_path, "r", encoding="utf-8") as f:
        har = json.load(f)

    entries = har.get("log", {}).get("entries", [])
    hits = []

    for e in entries:
        req = e.get("request", {}) or {}
        res = e.get("response", {}) or {}
        url = req.get("url", "") or ""
        method = req.get("method", "") or ""
        status = res.get("status", 0) or 0
        mime = (res.get("content", {}) or {}).get("mimeType", "") or ""
        text_len = len((res.get("content", {}) or {}).get("text", "") or "")
        if not url:
            continue
        m = mime.lower()
        if ("json" in m) or ("text" in m) or ("application" in m):
            hits.append((text_len, status, method, mime, url))

    hits.sort(reverse=True, key=lambda x: x[0])

    print("\nTop endpoints by response size:")
    for size, status, method, mime, url in hits[: args.top]:
        print(f"{size:>8}  {status:<3} {method:<4}  {mime:<28}  {url}")

    saved = 0
    for e in entries:
        if saved >= args.save:
            break
        req = e.get("request", {}) or {}
        res = e.get("response", {}) or {}
        url = req.get("url", "") or ""
        body = decode_har_text((res.get("content", {}) or {}))
        if not url or not body:
            continue
        out_path = os.path.join(args.out, safe_name(url) + ".txt")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(body)
        saved += 1

    print(f"\nSaved {saved} response bodies into: {args.out}")


if __name__ == "__main__":
    main()
