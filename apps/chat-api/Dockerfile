FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

WORKDIR /app

COPY packages/llm_logger /opt/llm_logger
RUN pip install --no-cache-dir /opt/llm_logger

COPY apps/chat-api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY apps/chat-api/app ./app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
