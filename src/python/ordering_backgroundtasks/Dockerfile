# Python replacement for Ordering.BackgroundTasks. Build context is src/:
# docker build -f python/ordering_backgroundtasks/Dockerfile .
# Same runtime interface: /hc + /liveness on PORT (80).
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
COPY python/ordering_backgroundtasks /app/ordering_backgroundtasks

RUN pip install --no-cache-dir /app/eshop_common /app/ordering_backgroundtasks

# Frozen compose interface defaults (same as the .NET container/appsettings).
ENV PORT=80 \
    SubscriptionClientName=BackgroundTasks \
    GracePeriodTime=1 \
    CheckUpdateTime=1000

RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 80

CMD ["python", "-m", "ordering_backgroundtasks.main"]
