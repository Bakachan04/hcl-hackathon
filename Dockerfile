# One image for both services (api and ui). Build from the repo root:
#   docker compose up --build
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY backend/requirements.txt backend/requirements.txt
RUN pip install -r backend/requirements.txt

COPY backend backend
COPY ui ui
COPY docs docs

# SQLite file and generated CSVs live here (mounted as a volume by compose).
RUN mkdir -p /app/data/raw
ENV DB_PATH=/app/data/planner.db \
    DATA_DIR=/app/data/raw

WORKDIR /app/backend
EXPOSE 8000 8501
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
