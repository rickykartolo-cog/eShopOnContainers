# Python replacement for Basket.API. Build context is src/ (same as the .NET
# image): docker build -f python/basket_api/Dockerfile .
# Same runtime interface: HTTP on PORT (80), gRPC on GRPC_PORT (81), /hc, /liveness.
FROM python:3.12.8-slim-bookworm AS base

WORKDIR /app

COPY python/eshop_common /app/eshop_common
COPY python/basket_api /app/basket_api
COPY Services/Basket/Basket.API/Proto/basket.proto /app/proto/basket.proto

RUN pip install --no-cache-dir /app/eshop_common /app/basket_api

# Frozen compose interface defaults (same as the .NET container/appsettings).
ENV PORT=80 \
    GRPC_PORT=81 \
    SubscriptionClientName=Basket \
    BASKET_PROTO_PATH=/app/proto/basket.proto

RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 80 81

CMD ["python", "-m", "basket_api.main"]
