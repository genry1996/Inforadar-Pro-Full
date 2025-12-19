import pymysql
import os
import json
from datetime import datetime
import time

# DB Config
DB_CONFIG = {
    'host': os.getenv('MYSQL_HOST', 'mysql_inforadar'),
    'user': os.getenv('MYSQL_USER', 'root'),
    'password': os.getenv('MYSQL_PASSWORD', 'ryban8991!'),
    'database': os.getenv('MYSQL_DB', 'inforadar')
}

def get_connection():
    try:
        conn = pymysql.connect(**DB_CONFIG)
        return conn
    except Exception as e:
        print(f"❌ DB Connection Error: {e}")
        return None

def detect_anomalies():
    conn = get_connection()
    if not conn:
        print("❌ Cannot connect to database")
        return
    
    print("✅ Anomaly Detector Started")
    print("🔄 Monitoring odds changes...")
    
    cursor = conn.cursor()
    
    while True:
        try:
            cursor.execute("""
                SELECT match_id, home_odd, draw_odd, away_odd, timestamp
                FROM odds_history
                ORDER BY timestamp DESC
                LIMIT 100
            """)
            
            results = cursor.fetchall()
            
            if results:
                print(f"📊 Checking {len(results)} records...")
            
            time.sleep(int(os.getenv('CHECK_INTERVAL', 5)))
            
        except Exception as e:
            print(f"❌ Error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    detect_anomalies()
