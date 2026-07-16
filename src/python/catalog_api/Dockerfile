# Python replacement for Catalog.API. Build context is src/ (same as the .NET
# image): docker build -f python/catalog_api/Dockerfile .
# Same runtime interface: HTTP on PORT (80), gRPC on GRPC_PORT (81), /hc, /liveness.
FROM python:3.12.8-slim-bookworm AS base

# Microsoft ODBC Driver 18 for SQL Server
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl gnupg2 ca-certificates apt-transport-https unixodbc \
    && curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg \
    && echo "deb [arch=amd64,arm64 signed-by=/usr/share/keyrings/microsoft-prod.gpg] https://packages.microsoft.com/debian/12/prod bookworm main" > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 \
    && apt-get purge -y curl gnupg2 \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY python/eshop_common /app/eshop_common
COPY python/catalog_api /app/catalog_api
COPY Services/Catalog/Catalog.API/Proto/catalog.proto /app/proto/catalog.proto
COPY Services/Catalog/Catalog.API/Pics /app/Pics
COPY Services/Catalog/Catalog.API/Setup /app/Setup

RUN pip install --no-cache-dir /app/eshop_common /app/catalog_api

# Frozen compose interface defaults (same as the .NET container/appsettings).
ENV PORT=80 \
    GRPC_PORT=81 \
    SubscriptionClientName=Catalog \
    PICS_PATH=/app/Pics \
    SETUP_PATH=/app/Setup \
    CATALOG_PROTO_PATH=/app/proto/catalog.proto

RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 80 81

CMD ["python", "-m", "catalog_api.main"]
