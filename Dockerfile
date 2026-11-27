FROM ghcr.io/astral-sh/uv:0.13.7 AS uv

FROM python:3.12-slim-bookworm AS dependencies
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /service
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-python-downloads

FROM python:3.12-slim-bookworm
ENV PATH="/service/.venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /service
RUN groupadd --gid 10001 shopping && \
    useradd --uid 10001 --gid 10001 --no-create-home --no-log-init --shell /usr/sbin/nologin shopping
COPY --from=dependencies /service/.venv ./.venv
COPY app ./app
COPY scripts ./scripts
COPY alembic.ini ./
COPY migrations ./migrations
USER 10001:10001
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
