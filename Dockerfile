FROM python:3.13-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_ENV=production \
    FLASK_ENV=production \
    FLASK_DEBUG=0 \
    HOST=0.0.0.0 \
    PORT=5000

COPY requirements.txt requirements-prod.txt ./
RUN pip install --no-cache-dir -r requirements-prod.txt

COPY . .

# Generate .env with random SECRET_KEY at build time is wrong for prod —
# mount .env or set SECRET_KEY via orchestrator at runtime.
RUN APP_ENV=development SECRET_KEY=build-install-only-not-for-production \
    python scripts/install.py --non-interactive

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/health')" || exit 1

CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:5000", "--timeout", "120", "app:app"]
