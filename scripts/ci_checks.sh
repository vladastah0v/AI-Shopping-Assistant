#!/bin/sh
set -eu

cd "$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
project="shopping-ci-$(openssl rand -hex 5)"
POSTGRES_PASSWORD=$(openssl rand -hex 24)
SHOPPING_POSTGRES_PASSWORD=$(openssl rand -hex 24)
export POSTGRES_PASSWORD SHOPPING_POSTGRES_PASSWORD
export API_PORT=0
export SHOPPING_OLLAMA_ENABLED=false
export SHOPPING_API_REQUESTS_PER_MINUTE=120
export SHOPPING_DEPENDENCY_TIMEOUT_SECONDS=5

compose() {
    docker compose -p "$project" -f docker-compose.yml -f infra/ci/compose.override.yml "$@"
}

cleanup() {
    status=$?
    trap - EXIT
    if [ "$status" -ne 0 ]; then
        compose logs --no-color --tail 100 api migrate postgres redis >&2 || :
    fi
    compose down --volumes >/dev/null || :
    exit "$status"
}

uv lock --check
uv sync --locked
uv run --locked ruff check .
uv run --locked ruff format --check .
compose config --quiet
docker compose -f docker-compose.yml -f docker-compose.semantic.yml config --quiet
docker compose -f docker-compose.yml -f docker-compose.ollama.yml --profile llm config --quiet
GRAFANA_ADMIN_PASSWORD=$(openssl rand -hex 24) docker compose     -f docker-compose.yml -f docker-compose.monitoring.yml --profile monitoring config --quiet
trap cleanup EXIT
compose up -d --build --wait --wait-timeout 180
compose run --rm --no-deps migrate alembic check

postgres_address=$(compose port postgres 5432)
redis_address=$(compose port redis 6379)
api_address=$(compose port api 8000)
export SHOPPING_TEST_DATABASE_URL="postgresql+asyncpg://shopping_migrator:$POSTGRES_PASSWORD@$postgres_address/shopping_assistant"
export SHOPPING_TEST_APP_DATABASE_URL="postgresql+asyncpg://shopping_app:$SHOPPING_POSTGRES_PASSWORD@$postgres_address/shopping_assistant"
export SHOPPING_TEST_REDIS_URL="redis://$redis_address/0"
export SHOPPING_TEST_BASE_URL="http://$api_address"
if [ -n "${CI_COVERAGE_PATH:-}" ]; then
    set -- --cov-report="xml:$CI_COVERAGE_PATH"
else
    set --
fi
uv run --locked pytest -q --cov=app --cov-report=term-missing --cov-fail-under=80 "$@"
