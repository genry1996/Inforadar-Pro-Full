FROM python:3.10

WORKDIR /app
COPY . /app

# Устанавливаем зависимости, включая cryptography
RUN pip install --no-cache-dir flask pymysql cryptography

EXPOSE 5000
CMD ["python", "app.py"]
