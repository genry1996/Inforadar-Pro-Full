CREATE
DATABASE IF NOT EXISTS inforadar;
USE
inforadar;

CREATE TABLE IF NOT EXISTS matches
(
    id
    INT
    AUTO_INCREMENT
    PRIMARY
    KEY,
    league
    VARCHAR
(
    100
),
    team1 VARCHAR
(
    100
),
    team2 VARCHAR
(
    100
),
    start_time VARCHAR
(
    20
),
    win1 FLOAT,
    draw FLOAT,
    win2 FLOAT,
    change_symbol VARCHAR
(
    10
)
    );

INSERT INTO matches (league, team1, team2, start_time, win1, draw, win2, change_symbol)
VALUES (''Premier League'', ''Arsenal'', ''Chelsea'', ''19:30'', 1.85, 3.5, 4.2, ''up''),
       (''La Liga'', ''Real Madrid'', ''Valencia'', ''21:00'', 1.45, 4.1, 6.3, ''down'');
