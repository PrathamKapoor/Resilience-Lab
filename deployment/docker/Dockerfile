FROM node:22.14.0-bookworm-slim AS dashboard-builder

WORKDIR /dashboard

COPY dashboard/package.json dashboard/package-lock.json ./
RUN npm ci

COPY dashboard ./
RUN npm run build


FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN addgroup --system --gid 10001 resiliencelab \
    && adduser --system --uid 10001 --ingroup resiliencelab resiliencelab \
    && mkdir -p /data \
    && chown resiliencelab:resiliencelab /data

WORKDIR /app

COPY pyproject.toml README.md LICENSE alembic.ini ./
COPY resiliencelab ./resiliencelab
COPY benchmarks ./benchmarks
COPY configs ./configs
COPY --from=dashboard-builder --chown=resiliencelab:resiliencelab /dashboard/dist ./dashboard/dist

RUN pip install --upgrade pip && pip install ".[parquet]"

EXPOSE 8000

ENV RESILIENCELAB_STORE=/data/results
ENV RESILIENCELAB_SERVER_MODE=false

VOLUME ["/data"]

USER resiliencelab

CMD ["uvicorn", "resiliencelab.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
