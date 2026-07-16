# Python replacement for Payment.API. Build context is src/ (same as the .NET
# image): docker build -f python/payment_api/Dockerfile .
# Same runtime interface: HTTP on PORT (80), /hc, /liveness; no gRPC listener.
FROM python:3.12.8-slim-bookworm AS base

WORKDIR /app

COPY python/eshop_common /app/eshop_common
COPY python/payment_api /app/payment_api

RUN pip install --no-cache-dir /app/eshop_common /app/payment_api

# Frozen compose interface defaults (same as the .NET container/appsettings).
ENV PORT=80 \
    SubscriptionClientName=Payment \
    PaymentSucceeded=true

RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 80

CMD ["python", "-m", "payment_api.main"]
