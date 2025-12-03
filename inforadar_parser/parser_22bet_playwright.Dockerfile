FROM mcr.microsoft.com/playwright/python:v1.56.0-jammy

# ==== Устанавливаем системные зависимости ====
RUN apt-get update && apt-get install -y \
    python3-dev \
    build-essential \
    libssl-dev \
    libffi-dev \
    curl \
    && apt-get clean

WORKDIR /app

# ==== Копируем requirements ====
COPY requirements.txt .

# ==== Устанавливаем Python зависимости (включая cryptography) ====
RUN pip install --upgrade pip setuptools wheel
RUN pip install --no-cache-dir cryptography
RUN pip install --no-cache-dir -r requirements.txt

# ==== Копируем проект ====
COPY . .

# ==== Playwright browsers ====
RUN playwright install --with-deps chromium
