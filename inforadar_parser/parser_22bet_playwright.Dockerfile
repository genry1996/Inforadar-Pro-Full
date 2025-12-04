FROM mcr.microsoft.com/playwright/python:v1.42.0-jammy

# системные зависимости
RUN apt-get update && apt-get install -y \
    python3-dev build-essential libssl-dev libffi-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# копируем зависимости
COPY requirements.txt .

RUN pip install --upgrade pip setuptools wheel
RUN pip install cryptography
RUN pip install --no-cache-dir -r requirements.txt

# КОПИРУЕМ ВСЁ (включая dump_html.py)
COPY . .

# ставим Chromium
RUN playwright install --with-deps chromium

CMD ["python3", "parser_22bet_playwright.py"]
