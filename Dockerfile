FROM ghcr.io/astral-sh/uv:0.13.7 AS uv

FROM python:3.12-slim-bookworm AS dependencies
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /service
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-python-downloads

FROM dependencies AS embedding-dependencies
RUN uv sync --locked --no-dev --extra embeddings --no-python-downloads

FROM scratch AS application-code
WORKDIR /service
COPY app ./app
COPY scripts ./scripts
COPY alembic.ini ./
COPY migrations ./migrations

FROM python:3.12-slim-bookworm AS runtime
ENV PATH="/service/.venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /service
RUN groupadd --gid 10001 shopping && \
    useradd --uid 10001 --gid 10001 --no-create-home --no-log-init --shell /usr/sbin/nologin shopping
USER 10001:10001
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM runtime AS embeddings
USER root
ENV HF_HOME=/var/cache/huggingface \
    HF_HUB_DISABLE_TELEMETRY=1 \
    OMP_NUM_THREADS=2 \
    MKL_NUM_THREADS=2 \
    TOKENIZERS_PARALLELISM=false
RUN install -d -o 10001 -g 10001 /var/cache/huggingface
COPY --from=embedding-dependencies /service/.venv ./.venv
COPY --from=application-code /service/ ./
USER 10001:10001

FROM runtime AS api
COPY --from=dependencies /service/.venv ./.venv
COPY --from=application-code /service/ ./
