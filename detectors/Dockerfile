FROM python:3.10-slim

WORKDIR /app

RUN pip install --no-cache-dir pymysql requests python-telegram-bot

COPY . /app/

CMD ["python", "odds_analyzer.py"]