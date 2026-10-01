FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY docker/processing-entrypoint.sh /processing-entrypoint.sh

RUN pip install --no-cache-dir . \
    && chmod +x /processing-entrypoint.sh \
    && mkdir -p /tmp/prometheus

ENV PROMETHEUS_MULTIPROC_DIR=/tmp/prometheus
ENV ENERGYFLOW_METRICS_PORT=9100

EXPOSE 9100

ENTRYPOINT ["/processing-entrypoint.sh"]
CMD ["celery", "-A", "processing_service.worker:celery_app", "worker", "--loglevel=info", "--concurrency=4"]
