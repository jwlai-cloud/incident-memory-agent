#!/usr/bin/env bash
# Write COCKROACH_URL into .env from a silently-prompted password, and keep a
# copy in the macOS Keychain so a clobbered .env is recoverable.
#
#   ./scripts/set_db_password.sh mimir_app        # prompt for the password
#   ./scripts/set_db_password.sh mimir_app --from-keychain   # rebuild .env
#
# Read the stored password back any time:
#   security find-generic-password -s mimir-crdb -a <username> -w
set -euo pipefail

HOST="mimir-memory-30177.j77.aws-us-east-1.cockroachlabs.cloud:26257"
SERVICE="mimir-crdb"
cd "$(dirname "$0")/.."

USER_NAME="${1:-}"
[[ -n "$USER_NAME" ]] || { echo "usage: $0 <sql-username> [--from-keychain]"; exit 1; }

if [[ "${2:-}" == "--from-keychain" ]]; then
  PW="$(security find-generic-password -s "$SERVICE" -a "$USER_NAME" -w)"
else
  read -rs -p "Password for SQL user '$USER_NAME': " PW; echo
  [[ -n "$PW" ]] || { echo "empty password, aborting"; exit 1; }
  security add-generic-password -U -s "$SERVICE" -a "$USER_NAME" -w "$PW"
  echo "stored in Keychain (service=$SERVICE account=$USER_NAME)"
fi

PW="$PW" HOST="$HOST" USER_NAME="$USER_NAME" python3 - <<'PY'
import os, pathlib, urllib.parse
pw = urllib.parse.quote(os.environ["PW"], safe="")
p = pathlib.Path(".env")
p.write_text(
    f"COCKROACH_URL=postgresql://{os.environ['USER_NAME']}:{pw}@{os.environ['HOST']}/defaultdb?sslmode=verify-full\n"
    "AWS_REGION=us-east-1\n"
    "BEDROCK_REASONING_MODEL=amazon.nova-micro-v1:0\n"
)
p.chmod(0o600)
print(f"wrote .env for user {os.environ['USER_NAME']}")
PY
unset PW
