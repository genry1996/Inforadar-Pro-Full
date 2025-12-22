import mysql.connector

conn = mysql.connector.connect(
    host="localhost",
    user="root",
    password="ryban8991!",
    database="inforadar"
)

cursor = conn.cursor()

# Проверка таблицы anomalies_22bet
cursor.execute("SHOW TABLES LIKE 'anomalies_22bet'")
result = cursor.fetchone()

if result:
    print("✅ Таблица anomalies_22bet существует")
    cursor.execute("DESCRIBE anomalies_22bet")
    print("\n📋 СТРУКТУРА:")
    for row in cursor.fetchall():
        print(f"  {row[0]:20} | {row[1]}")
    
    cursor.execute("SELECT COUNT(*) FROM anomalies_22bet")
    print(f"\n📊 Записей: {cursor.fetchone()[0]}")
else:
    print("❌ Таблица НЕ существует, создаю...")
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

# Проверка таблицы odds_22bet
cursor.execute("SHOW TABLES LIKE 'odds_22bet'")
result = cursor.fetchone()

if result:
    print("\n✅ Таблица odds_22bet существует")
else:
    print("\n❌ Таблица odds_22bet НЕ существует, создаю...")
    cursor.execute("""
        CREATE TABLE odds_22bet (
            id INT AUTO_INCREMENT PRIMARY KEY,
            event_name VARCHAR(255) UNIQUE,
            sport VARCHAR(50),
            market_type VARCHAR(50),
            odd_1 DECIMAL(10,3),
            odd_x DECIMAL(10,3),
            odd_2 DECIMAL(10,3),
            status VARCHAR(50),
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    print("✅ Таблица создана!")

cursor.close()
conn.close()
print("\n🎉 Проверка завершена!")
