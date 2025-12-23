-- ===== CLEANUP OLD DUPLICATES FROM odds_22bet =====
-- Очистим данные старше 1 суток
DELETE FROM odds_22bet 
WHERE updated_at < DATE_SUB(NOW(), INTERVAL 1 DAY);

PRINT '✅ Deleted old records from odds_22bet';

-- ===== CLEANUP OLD RECORDS FROM odds_full_history =====
-- Очистим историю старше 1 суток
DELETE FROM odds_full_history 
WHERE timestamp < DATE_SUB(NOW(), INTERVAL 1 DAY);

PRINT '✅ Deleted old records from odds_full_history';

-- ===== CHECK CURRENT COUNTS =====
SELECT 
    (SELECT COUNT(*) FROM odds_22bet) as total_matches_22bet,
    (SELECT COUNT(DISTINCT event_name) FROM odds_22bet) as unique_matches,
    (SELECT COUNT(*) FROM odds_full_history) as history_records;

PRINT '✅ Database cleanup completed!';
