-- Fonbet: convert fonbet_events.start_ts from seconds -> milliseconds (ms).
-- Needed if UI/API does FROM_UNIXTIME(start_ts/1000) and filters with now_ms.
-- Safe: only changes rows that still look like "seconds".

SELECT COUNT(*) AS cnt_before,
       MIN(start_ts) AS min_ts_before,
       MAX(start_ts) AS max_ts_before
FROM fonbet_events;

UPDATE fonbet_events
SET start_ts = start_ts * 1000
WHERE start_ts < 20000000000; -- ~year 2603 in seconds, so anything smaller is definitely seconds

SELECT COUNT(*) AS cnt_after,
       MIN(start_ts) AS min_ts_after,
       MAX(start_ts) AS max_ts_after
FROM fonbet_events;

-- Quick sanity check: should now show real dates
SELECT start_ts,
       FROM_UNIXTIME(start_ts/1000) AS dt
FROM fonbet_events
ORDER BY start_ts DESC
LIMIT 5;
