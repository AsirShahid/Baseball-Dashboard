# The site and its updater share this image (see docker-compose.yml).
FROM python:3.12-slim
WORKDIR /app
# uid 1001 matches the host user that owns the bind-mounted CSV folders.
RUN useradd -m -u 1001 -s /usr/sbin/nologin app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py ./
COPY pipeline pipeline
COPY web web
COPY Logos Logos
USER app
ENV DATA_ROOT=/data PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
EXPOSE 8050
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8050/healthz', timeout=4).status==200 else 1)"
CMD ["gunicorn", "app:app", "-b", "0.0.0.0:8050", "--workers", "2", "--threads", "4", "--timeout", "60", \
     "--graceful-timeout", "20", "--max-requests", "3000", "--max-requests-jitter", "300"]
