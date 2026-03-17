#!/bin/bash
set -e

echo "Initializing application role: ${N8N_DB_USER}"

psql -v ON_ERROR_STOP=1 \
  --username "$POSTGRES_USER" \
  --dbname "$POSTGRES_DB" <<EOSQL
DO
\$\$
BEGIN
   IF NOT EXISTS (
      SELECT
      FROM pg_catalog.pg_roles
      WHERE rolname = '${N8N_DB_USER}'
   ) THEN
      CREATE ROLE ${N8N_DB_USER} LOGIN PASSWORD '${N8N_DB_PASSWORD}';
   END IF;
END
\$\$;

ALTER DATABASE ${POSTGRES_DB} OWNER TO ${N8N_DB_USER};
GRANT CONNECT ON DATABASE ${POSTGRES_DB} TO ${N8N_DB_USER};
GRANT USAGE, CREATE ON SCHEMA public TO ${N8N_DB_USER};
EOSQL