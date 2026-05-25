#!/bin/sh
set -e

SECRETS_FILE="/app/secrets/.env"

if [ ! -f "$SECRETS_FILE" ]; then
    mkdir -p /app/secrets
    python - <<'PY'
from cryptography.fernet import Fernet
import secrets
from pathlib import Path

path = Path("/app/secrets/.env")
path.write_text(
    f"LLMOPS_ENCRYPTION_KEY={Fernet.generate_key().decode()}\n"
    f"LLMOPS_GRAFANA_SIGNING_SECRET={secrets.token_hex(32)}\n"
)
print(f"Generated secrets at {path}")
PY
fi

set -a
# shellcheck disable=SC1090
. "$SECRETS_FILE"
set +a

exec "$@"
