# Build stage: a toolchain is available here to compile any wheels that need
# it, but none of it reaches the runtime image.
FROM python:3.12-slim AS build
# NOTE: a bare tag is still mutable. Pin by digest once the deploy host can
# resolve one:  FROM python:3.12-slim@sha256:<digest> AS build
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt gunicorn

# Runtime stage: no build toolchain, no curl, runs as a non-root user.
FROM python:3.12-slim
WORKDIR /app
# uid 1001 matches the host user that owns the bind-mounted CSV directories, so
# the watcher and the live-fetch path can still write them as a non-root user.
RUN useradd -m -u 1001 -s /usr/sbin/nologin app
COPY --from=build /install /usr/local
COPY . .
RUN chown -R app:app /app
USER app
ENV HOST=0.0.0.0 PORT=8050
EXPOSE 8050
# Report unhealthy if the Dash server stops answering (hung worker, crashed
# import). Uses python so the image needs no curl.
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8050/', timeout=4).status==200 else 1)"
CMD ["bash", "/app/entrypoint.sh"]
