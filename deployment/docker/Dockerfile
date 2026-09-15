FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY resiliencelab ./resiliencelab
COPY benchmarks ./benchmarks
COPY configs ./configs

RUN pip install --upgrade pip && pip install ".[parquet]"

EXPOSE 8000

ENV RESILIENCELAB_STORE=/data/results
ENV RESILIENCELAB_SERVER_MODE=true

VOLUME ["/data"]

CMD ["uvicorn", "resiliencelab.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
