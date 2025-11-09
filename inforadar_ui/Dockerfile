# Используем официальный образ Python
FROM python:3.10-slim

# Рабочая директория внутри контейнера
WORKDIR /app

# Копируем только файлы из папки inforadar_ui
COPY requirements.txt /app/requirements.txt

# Устанавливаем зависимости
RUN pip install --no-cache-dir -r requirements.txt

# Копируем всё из текущей директории (только inforadar_ui)
COPY . /app

# Открываем порт
EXPOSE 5000

# Запускаем Flask напрямую (без gunicorn, для отладки)
CMD ["python", "app.py"]
