import requests

PROXY = {
    "http":  "http://lknhyffv:ts7sg1ki2xhs@142.111.48.253:7030",
    "https": "http://lknhyffv:ts7sg1ki2xhs@142.111.48.253:7030",
}

# 30 возможных API-зеркал 22BET / 1XBET (API совместимо)
MIRRORS = [
    "https://22bet.com",
    "https://22bet1.com",
    "https://22bet2.com",
    "https://22bet3.com",
    "https://22bet4.com",
    "https://22bet5.com",
    "https://22bet-api.com",
    "https://22betapi.com",
    "https://api22bet.com",
    "https://22-bet.com",
    "https://22b.co",
    "https://22bet-365.com",
    "https://1xbet.com",
    "https://1xbet1.com",
    "https://1xbet2.com",
    "https://1xbet-api.com",
    "https://1x-bet.com",
    "https://1x-bet1.com",
    "https://1xbetapi.com",
    "https://mobile.22bet.com",
    "https://mobile1.22bet.com",
    "https://bet22api.com",
    "https://22api.com",
    "https://api22b.com",
]

URL_PATH = "/LineFeed/GetEvents?sportId=1&lng=en"

print("=== START MIRROR CHECK ===")
for m in MIRRORS:
    url = m + URL_PATH
    try:
        r = requests.get(url, proxies=PROXY, timeout=10)
        if r.status_code == 200 and r.text.startswith("{"):
            print(f"[+] WORKING API MIRROR: {m}")
        else:
            print(f"[-] {m} → {r.status_code}")
    except Exception as e:
        print(f"[X] {m} → ERROR: {str(e)}")

print("=== DONE ===")
