#!/bin/sh
# Production entrypoint. Secrets live in Infisical (env `prod`, folder `/backend`); the
# host only holds a machine identity allowed to read them, so a changed secret needs a
# restart, not a redeploy with new config.
set -eu

token=$(infisical login --method=universal-auth \
  --client-id="$INFISICAL_CLIENT_ID" --client-secret="$INFISICAL_CLIENT_SECRET" \
  --plain --silent)

exec infisical secrets-manager run --token="$token" --projectId="$INFISICAL_PROJECT_ID" \
  --env=prod --path=/backend --silent -- python -m app
