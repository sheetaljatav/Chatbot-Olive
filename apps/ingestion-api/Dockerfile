FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

WORKDIR /app

# Install the shared SDK first (relative to build context = repo root).
COPY packages/llm_logger /opt/llm_logger
RUN pip install --no-cache-dir /opt/llm_logger

COPY apps/ingestion-api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY apps/ingestion-api/app ./app

EXPOSE 8001
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
