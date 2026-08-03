FROM python:3.13-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_ENV=production \
    FLASK_ENV=production \
    FLASK_DEBUG=0 \
    HOST=0.0.0.0 \
    PORT=5000

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-prod.txt ./
RUN pip install --no-cache-dir -r requirements-prod.txt

COPY . .

# Generate .env with random SECRET_KEY at build time is wrong for prod —
# mount .env or set SECRET_KEY via orchestrator at runtime.
RUN APP_ENV=development SECRET_KEY=build-install-only-not-for-production \
    python scripts/install.py --non-interactive

EXPOSE 5000

RUN chmod +x scripts/docker-entrypoint.sh

# GC-PERF-PROD-001: probe liveness (/healthz), not deep readiness (/health).
# Railway deploy gate still uses /health via railway.toml.
HEALTHCHECK --interval=30s --timeout=5s --start-period=45s --retries=3 \
  CMD sh -c 'python -c "import os,urllib.request; urllib.request.urlopen(\"http://127.0.0.1:%s/healthz\" % (os.environ.get(\"PORT\") or \"5000\"))"' || exit 1

# Migrate on start (volume mounted), then gunicorn. See scripts/docker-entrypoint.sh.
CMD ["scripts/docker-entrypoint.sh"]
