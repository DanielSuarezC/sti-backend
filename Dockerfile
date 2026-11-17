# STI backend - producción (Render). Python 3.11 + libs de WeasyPrint.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000

# Librerías de sistema de WeasyPrint (PDF) y fuentes
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpango-1.0-0 libpangoft2-1.0-0 libpangocairo-1.0-0 libharfbuzz0b libharfbuzz-subset0 \
        libfontconfig1 libgdk-pixbuf-2.0-0 libcairo2 libffi-dev shared-mime-info fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 10001 sti
WORKDIR /app

COPY requirements.txt requirements-ai.txt ./
RUN pip install -r requirements.txt \
    && (pip install -r requirements-ai.txt || echo "IA opcional no instalada: se usará texto por plantilla")

COPY --chown=sti:sti . .
RUN mkdir -p /app/storage && chown -R sti:sti /app/storage
USER sti

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD python -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8000')+'/health')" || exit 1

# Migra la BD y arranca (Render inyecta $PORT). Para el worker: celery -A app.workers.celery_app.celery_app worker -l info
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
