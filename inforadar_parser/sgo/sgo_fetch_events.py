import requests

API_KEY = "8d9bd7a4f5aa932c3bcb8f0c62a59c1c"
BASE_URL = "https://api.sportsgameodds.com"

headers = {"x-api-key": API_KEY}

def fetch_events(sport_id=1):
    url = f"{BASE_URL}/odds?sport_id={sport_id}"
    r = requests.get(url, headers=headers, timeout=10)
    r.raise_for_status()
    return r.json()

if __name__ == "__main__":
    events = fetch_events(1)
    print(events)
