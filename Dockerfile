FROM node:22-alpine AS web-builder

WORKDIR /build/apps/web
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci
COPY apps/web/ ./
RUN npm run build

FROM python:3.12-slim AS runtime

ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
RUN addgroup --system app && adduser --system --ingroup app app

COPY pyproject.toml README.md ./
COPY src/ ./src/
COPY apps/ ./apps/
COPY alembic.ini ./
COPY infra/migrations/ ./infra/migrations/
RUN python -m pip install --index-url "$PIP_INDEX_URL" --retries 2 --timeout 30 .

COPY --from=web-builder /build/apps/web/dist ./apps/web/dist

USER app
EXPOSE 8000
CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
