import asyncio
from pinnacle_parser import PinnacleParser

async def test():
    parser = PinnacleParser()
    
    # Получи события футбола
    events = await parser.parse_all_events(sport_id=1)
    
    print(f"Найдено {len(events)} матчей")
    for event in events[:3]:
        print(f"  {event['home_team']} vs {event['away_team']}")
        print(f"  Коэффициенты: {event['odds']}")

asyncio.run(test())
