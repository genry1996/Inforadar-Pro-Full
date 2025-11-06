# Используем стабильный Python
FROM python:3.10

# Рабочая директория внутри контейнера
WORKDIR /app

# Копируем все файлы проекта
COPY . /app

# Устанавливаем зависимости
RUN pip install --no-cache-dir -r requirements.txt

# Запускаем Flask через Gunicorn
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:5000", "app:app"]
