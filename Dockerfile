FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000
# Popula o banco na primeira subida (só se estiver vazio) e inicia a API.
CMD ["sh", "-c", "python seed.py --se-vazio && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
