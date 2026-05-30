FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

# Presidio pulls spaCy + a small English model.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY packages/llm_logger /opt/llm_logger
RUN pip install --no-cache-dir /opt/llm_logger

COPY apps/worker/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
 && python -m spacy download en_core_web_sm

COPY apps/worker/app ./app

CMD ["python", "-m", "app.consumer"]
