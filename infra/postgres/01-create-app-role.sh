#!/bin/sh
set -eu

psql --no-psqlrc --set=ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
\getenv app_password SHOPPING_POSTGRES_PASSWORD
CREATE ROLE shopping_app LOGIN PASSWORD :'app_password';
GRANT USAGE ON SCHEMA public TO shopping_app;
SQL
