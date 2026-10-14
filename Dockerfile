FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PROF_DEMO=0 \
    HOST=0.0.0.0 \
    PORT=8091

WORKDIR /app
COPY pyproject.toml README.md ./
COPY prof ./prof
RUN pip install --no-cache-dir -e . \
    && useradd -r -u 10001 prof && mkdir -p /data && chown prof:prof /data
USER prof
VOLUME ["/data"]
EXPOSE 8091
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8091/healthz', timeout=4).status==200 else 1)"
CMD ["python", "-m", "prof", "gateway"]
