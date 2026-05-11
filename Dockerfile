FROM python:3.10-slim AS builder

WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml src/ ./
RUN pip install --upgrade pip \
    && pip install --target=/install -e .

FROM python:3.10-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --shell /bin/bash appuser

WORKDIR /home/appuser

COPY --from=builder /install /home/appuser/.local
ENV PATH=/home/appuser/.local/bin:$PATH

USER appuser
ENTRYPOINT ["claude-bridge"]
