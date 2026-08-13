FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY examples ./examples
COPY router.docker.json ./router.json

RUN python -m pip install --no-cache-dir . \
    && useradd --create-home --uid 10001 router \
    && mkdir -p /app/data \
    && chown -R router:router /app/data

USER router
EXPOSE 8080
VOLUME ["/app/data"]

CMD ["rooomtech-router", "--config", "/app/router.json"]

