FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app
WORKDIR /app

COPY backend/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY backend /app
RUN mkdir -p /app/data/uploads /app/data/exports

EXPOSE 8000
CMD ["sh", "-c", "python -m alembic -c alembic.ini upgrade head && python scripts/seed.py && uvicorn app.main:app --host 0.0.0.0 --port 8000"]

