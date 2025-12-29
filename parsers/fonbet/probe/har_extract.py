import argparse
import base64
import json
import os
import re
from pathlib import Path
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

def decode_har_text(content: dict) -> str | None:
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
    ap.add_argument("--top", type=int, default=30, help="How many endpoints to print")
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
        req = e.get("request", {})
        res = e.get("response", {})
        url = req.get("url", "")
        mime = res.get("content", {}).get("mimeType", "")
        text = res.get("content", {}).get("text", "")
        if not url:
            continue
        if any(k in (mime or "").lower() for k in ("json", "text")) or "application" in (mime or "").lower():
            hits.append((url, mime, len(text or "")))

    hits.sort(key=lambda x: x[2], reverse=True)

    print("Top endpoints by response size:")
    for url, mime, size in hits[: args.top]:
        print(f"{size:>8}  {mime:<30}  {url}")

    saved = 0
    for e in entries:
        if saved >= args.save:
            break
        req = e.get("request", {})
        res = e.get("response", {})
        url = req.get("url", "")
        content = res.get("content", {}) or {}
        body = decode_har_text(content)
        if not body:
            continue
        fname = safe_name(url) + ".txt"
        out_path = os.path.join(args.out, fname)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(body)
        saved += 1

    print(f"Saved {saved} response bodies into: {args.out}")

if __name__ == "__main__":
    main()
