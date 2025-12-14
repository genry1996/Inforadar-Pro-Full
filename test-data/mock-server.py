from flask import Flask, render_template
app = Flask(__name__)

@app.route('/anomalies_22bet')
def anomalies_22bet():
    # Возвращаем HTML с тестовыми данными
    return render_template('anomalies_22bet.html', anomalies=[
        {
            'id': 1,
            'event_name': 'Test Match',
            'sport': 'football',
            'league': 'Premier League',
            'anomaly_type': 'ODDS_DROP',
            'old_odd': 2.5,
            'new_odd': 1.8,
            'change_percent': -28.0,
            'detected_at': '2025-12-14 16:00:00'
        }
    ])

if __name__ == '__main__':
    app.run(port=5000)
