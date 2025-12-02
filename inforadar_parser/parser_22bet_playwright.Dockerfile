FROM mcr.microsoft.com/playwright/python:v1.46.0-jammy

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Chromium будет использовать прокси через ENV ALL_PROXY, задаваемый в docker-compose
CMD ["python", "parser_22bet_playwright.py"]
