import os
import json
from datetime import datetime, timedelta
from typing import Optional, List
import mysql.connector
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="Betwatch API")

# Serve dashboard.html
@app.get("/dashboard.html")
async def get_dashboard():
    return FileResponse("dashboard.html")

# Serve static files (if needed)
app.mount("/static", StaticFiles(directory="."), name="static")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ... остальной код ...

MYSQL_CONFIG = {
    "host": os.getenv("MYSQL_HOST", "mysql_inforadar"),
    "user": os.getenv("MYSQL_USER", "root"),
    "password": os.getenv("MYSQL_PASSWORD", ""),
    "database": os.getenv("MYSQL_DB", "inforadar_db"),
}

def get_db():
    """Подключение к БД"""
    try:
        conn = mysql.connector.connect(**MYSQL_CONFIG)
        return conn
    except Exception as e:
        print(f"DB Error: {e}")
        return None

# ===== API ENDPOINTS =====

@app.get("/api/health")
async def health():
    """Health check"""
    conn = get_db()
    if conn:
        conn.close()
        return {"status": "healthy"}
    return {"status": "unhealthy"}

@app.get("/api/signals/recent")
async def get_recent_signals(hours: int = 1, limit: int = 50):
    """Последние сигналы (по умолчанию за последний час)"""
    conn = get_db()
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection failed")
    
    try:
        cursor = conn.cursor(dictionary=True)
        query = f"""
        SELECT id, signal_type, event_name, league, market_type, timestamp
        FROM betwatch_signals 
        WHERE timestamp >= DATE_SUB(NOW(), INTERVAL {hours} HOUR)
        ORDER BY timestamp DESC
        LIMIT {limit}
        """
        cursor.execute(query)
        signals = cursor.fetchall()
        
        # Конвертируем datetime в строку
        for signal in signals:
            signal['timestamp'] = signal['timestamp'].isoformat()
        
        return {"status": "success", "data": signals}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        conn.close()

@app.get("/api/signals/stats")
async def get_signal_stats(hours: int = 24):
    """Статистика по типам сигналов"""
    conn = get_db()
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection failed")
    
    try:
        cursor = conn.cursor(dictionary=True)
        query = f"""
        SELECT 
            signal_type,
            COUNT(*) as count
        FROM betwatch_signals
        WHERE timestamp >= DATE_SUB(NOW(), INTERVAL {hours} HOUR)
        GROUP BY signal_type
        ORDER BY count DESC
        """
        cursor.execute(query)
        stats = cursor.fetchall()
        
        return {"status": "success", "data": stats}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        conn.close()

@app.get("/api/events/top")
async def get_top_events(limit: int = 20):
    """Топ событий по количеству сигналов"""
    conn = get_db()
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection failed")
    
    try:
        cursor = conn.cursor(dictionary=True)
        query = f"""
        SELECT 
            event_name,
            league,
            COUNT(*) as signal_count,
            GROUP_CONCAT(DISTINCT signal_type SEPARATOR ', ') as signals
        FROM betwatch_signals
        WHERE timestamp >= DATE_SUB(NOW(), INTERVAL 24 HOUR)
        GROUP BY event_name, league
        ORDER BY signal_count DESC
        LIMIT {limit}
        """
        cursor.execute(query)
        events = cursor.fetchall()
        
        return {"status": "success", "data": events}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        conn.close()

@app.get("/api/signals/by-type/{signal_type}")
async def get_signals_by_type(signal_type: str, limit: int = 30):
    """Все сигналы конкретного типа"""
    conn = get_db()
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection failed")
    
    try:
        cursor = conn.cursor(dictionary=True)
        query = """
        SELECT id, event_name, league, market_type, timestamp
        FROM betwatch_signals 
        WHERE signal_type LIKE %s
        ORDER BY timestamp DESC
        LIMIT %s
        """
        cursor.execute(query, (f"%{signal_type}%", limit))
        signals = cursor.fetchall()
        
        for signal in signals:
            signal['timestamp'] = signal['timestamp'].isoformat()
        
        return {"status": "success", "data": signals}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        conn.close()

@app.get("/api/dashboard/summary")
async def get_dashboard_summary():
    """Полная сводка для главной страницы"""
    conn = get_db()
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection failed")
    
    try:
        cursor = conn.cursor(dictionary=True)
        
        # Счетчики
        cursor.execute("""
            SELECT 
                COUNT(*) as total_signals,
                (SELECT COUNT(DISTINCT event_name) FROM betwatch_signals 
                 WHERE timestamp >= DATE_SUB(NOW(), INTERVAL 24 HOUR)) as unique_events,
                (SELECT COUNT(*) FROM betwatch_signals 
                 WHERE signal_type LIKE '%Sharp%' 
                 AND timestamp >= DATE_SUB(NOW(), INTERVAL 1 HOUR)) as sharp_moves_1h,
                (SELECT COUNT(*) FROM betwatch_signals 
                 WHERE timestamp >= DATE_SUB(NOW(), INTERVAL 1 HOUR)) as signals_1h
            FROM betwatch_signals
            WHERE timestamp >= DATE_SUB(NOW(), INTERVAL 24 HOUR)
        """)
        summary = cursor.fetchone()
        
        # Топ сигналов по типам
        cursor.execute("""
            SELECT signal_type, COUNT(*) as count
            FROM betwatch_signals
            WHERE timestamp >= DATE_SUB(NOW(), INTERVAL 24 HOUR)
            GROUP BY signal_type
            ORDER BY count DESC
            LIMIT 5
        """)
        top_signals = cursor.fetchall()
        
        # Последние 10 сигналов
        cursor.execute("""
            SELECT id, signal_type, event_name, league, timestamp
            FROM betwatch_signals
            ORDER BY timestamp DESC
            LIMIT 10
        """)
        recent = cursor.fetchall()
        
        for item in recent:
            item['timestamp'] = item['timestamp'].isoformat()
        
        return {
            "status": "success",
            "summary": summary,
            "top_signals": top_signals,
            "recent": recent
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        conn.close()

# ===== RUN =====
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)