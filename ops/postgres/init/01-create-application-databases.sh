#!/bin/sh
set -eu

psql \
  --username "$POSTGRES_USER" \
  --dbname "$POSTGRES_DB" \
  --set=ON_ERROR_STOP=1 \
  --set=publisher_password="$PUBLISHER_DB_PASSWORD" \
  --set=n8n_password="$N8N_DB_PASSWORD" <<'SQL'
CREATE USER publisher WITH PASSWORD :'publisher_password' NOSUPERUSER NOCREATEDB NOCREATEROLE;
CREATE DATABASE publisher OWNER publisher;
CREATE USER n8n WITH PASSWORD :'n8n_password' NOSUPERUSER NOCREATEDB NOCREATEROLE;
CREATE DATABASE n8n OWNER n8n;
SQL

