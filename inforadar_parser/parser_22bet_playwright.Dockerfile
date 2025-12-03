FROM mcr.microsoft.com/playwright/python:v1.56.0-jammy

WORKDIR /app

# Устанавливаем системные библиотеки для cryptography
RUN apt-get update && apt-get install -y \
    build-essential \
    python3-dev \
    libssl-dev \
    libffi-dev \
    cargo \
    rustc \
    && apt-get clean

COPY requirements.txt .

RUN pip install --upgrade pip setuptools wheel
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python3", "parser_22bet_playwright.py"]
