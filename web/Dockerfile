FROM python:3.11-slim

WORKDIR /app

# Install system dependencies (libpq-dev & build-essential for psycopg2/C-extensions, curl for healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY web/requirements.txt ./web/requirements.txt
RUN pip install --no-cache-dir -r web/requirements.txt

COPY . .

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --retries=3 \
    CMD curl --fail http://localhost:8000/health || exit 1

CMD ["sh", "-c", "uvicorn web.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
