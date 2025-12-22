import mysql.connector

conn = mysql.connector.connect(
    host="localhost",
    user="root",
    password="ryban8991!",
    database="inforadar"
)

cursor = conn.cursor()

# Проверка таблицы
cursor.execute("SHOW TABLES LIKE 'anomalies_22bet'")
result = cursor.fetchone()

if result:
    print("✅ Таблица anomalies_22bet СУЩЕСТВУЕТ")
    
    # Показать структуру
    cursor.execute("DESCRIBE anomalies_22bet")
    print("\n📋 СТРУКТУРА:")
    for row in cursor.fetchall():
        print(f"  {row[0]} | {row[1]}")
    
    # Показать данные
    cursor.execute("SELECT COUNT(*) FROM anomalies_22bet")
    count = cursor.fetchone()[0]
    print(f"\n📊 Записей: {count}")
    
    if count > 0:
        cursor.execute("SELECT * FROM anomalies_22bet ORDER BY id DESC LIMIT 5")
        print("\n🔥 Последние 5 аномалий:")
        for row in cursor.fetchall():
            print(f"  {row}")
else:
    print("❌ Таблица anomalies_22bet НЕ СУЩЕСТВУЕТ")
    print("\n🔧 Создаю таблицу...")
    cursor.execute("""
        CREATE TABLE anomalies_22bet (
            id INT AUTO_INCREMENT PRIMARY KEY,
            event_name VARCHAR(255),
            sport VARCHAR(50),
            league VARCHAR(100),
            anomaly_type VARCHAR(50),
            before_value VARCHAR(50),
            after_value VARCHAR(50),
            diff_pct DECIMAL(10,2),
            status VARCHAR(50),
            comment TEXT,
            detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    print("✅ Таблица создана!")

cursor.close()
conn.close()
