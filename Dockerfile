
FROM python:3.12-slim

# Чтобы логи сразу шли в stdout без буфера
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Системные зависимости (минимум)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
 && rm -rf /var/lib/apt/lists/*

RUN apt-get update && \
    apt-get install -y fonts-dejavu-core && \
    rm -rf /var/lib/apt/lists/*


# Сначала зависимости — для кеша
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Потом код
COPY . /app

# На всякий случай: укажем PYTHONPATH, чтобы "src.*" импортировался корректно
ENV PYTHONPATH=/app

# Запуск: предполагаем, что в src/bot_metalead/__main__.py есть точка входа
CMD ["python", "-m", "src.bot_metalead"]