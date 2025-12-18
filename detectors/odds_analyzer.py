# detectors/odds_analyzer.py
class OddsAnalyzer:
    def __init__(self):
        self.conn = get_connection()
        
    def detect_odds_drop(self, current_odds, match_id):
        """Определяет резкое падение коэффициента"""
        # Получаем предыдущие значения из БД
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT home_odd, draw_odd, away_odd, timestamp
            FROM odds_history
            WHERE match_id = %s
            ORDER BY timestamp DESC
            LIMIT 10
        """, (match_id,))
        
        history = cursor.fetchall()
        if len(history) < 2:
            return None
            
        prev_odd = history[1]['home_odd']
        current_odd = current_odds['home_odd']
        
        change_pct = ((current_odd - prev_odd) / prev_odd) * 100
        
        # Аномалия: падение > 15% за 3 секунды
        if change_pct < -15:
            return {
                'type': 'ODDS_DROP',
                'severity': 'HIGH' if change_pct < -25 else 'MEDIUM',
                'before': prev_odd,
                'after': current_odd,
                'change_pct': change_pct,
                'match_info': current_odds
            }
        
        return None
