# Python replacement for Ordering.SignalrHub.
# Build context is src/ (same as the other compose services):
#   docker compose -f docker-compose.yml -f docker-compose.override.yml build ordering-signalrhub
FROM python:3.12.11-slim-bookworm

# ODBC Driver 18 is intentionally NOT installed: this service has no SQL dependency.
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY python/eshop_common/pyproject.toml python/eshop_common/README.md /app/eshop_common/
COPY python/eshop_common/eshop_common /app/eshop_common/eshop_common
COPY python/ordering_signalrhub/pyproject.toml /app/ordering_signalrhub/
COPY python/ordering_signalrhub/ordering_signalrhub /app/ordering_signalrhub/ordering_signalrhub

RUN pip install --no-cache-dir /app/eshop_common /app/ordering_signalrhub

RUN useradd --create-home --uid 10001 appuser
USER appuser

# Same internal HTTP port as the .NET service (compose maps 5112:80).
ENV PORT=80
EXPOSE 80

CMD ["python", "-m", "ordering_signalrhub.main"]
