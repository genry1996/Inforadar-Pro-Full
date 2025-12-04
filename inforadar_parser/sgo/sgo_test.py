import requests

API_KEY = "8d9bd7a4f5aa932c3bcb8f0c62a59c1c"
BASE_URL = "https://api.sportsgameodds.com"

headers = {
    "x-api-key": API_KEY,
    "Accept": "application/json"
}

def main():
    try:
        r = requests.get(f"{BASE_URL}/status", headers=headers, timeout=10)
        print("HTTP:", r.status_code)
        print("Response:", r.text)
    except Exception as e:
        print("❌ Ошибка:", e)

if __name__ == "__main__":
    main()
