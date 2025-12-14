# backend/main.py
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
import mysql.connector

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/odds/{sport}")
async def get_odds(sport: str, bookmaker: str = "all"):
    """Получить коэффициенты по виду спорта"""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    if bookmaker == "all":
        query = "SELECT * FROM odds_22bet WHERE sport=%s ORDER BY created_at DESC LIMIT 100"
        cursor.execute(query, (sport,))
    else:
        query = "SELECT * FROM odds_22bet WHERE sport=%s AND bookmaker=%s ORDER BY created_at DESC LIMIT 100"
        cursor.execute(query, (sport, bookmaker))
    
    results = cursor.fetchall()
    cursor.close()
    conn.close()
    
    return {"data": results}

@app.get("/api/anomalies/latest")
async def get_latest_anomalies(limit: int = 20):
    """Получить последние аномалии"""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    query = """
        SELECT * FROM anomalies_22bet 
        WHERE status='active' 
        ORDER BY detected_at DESC 
        LIMIT %s
    """
    cursor.execute(query, (limit,))
    results = cursor.fetchall()
    cursor.close()
    conn.close()
    
    return {"data": results}

@app.websocket("/ws/live-odds")
async def websocket_odds(websocket: WebSocket):
    """WebSocket для real-time обновлений"""
    await websocket.accept()
    
    while True:
        # Отправка обновлений каждые 2 сек
        latest_data = await get_latest_odds_from_db()
        await websocket.send_json(latest_data)
        await asyncio.sleep(2)
