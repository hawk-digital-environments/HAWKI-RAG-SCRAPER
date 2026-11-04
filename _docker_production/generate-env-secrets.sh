#!/bin/bash
# Generates a fresh value for the required secret of the production stack
# (the "Required Settings" section at the top of .env.example) and prints it
# as a ready-to-paste env block:
#
#   ./generate-env-secrets.sh
#
# Copy the printed block into .env, overwriting the empty values of the same
# names. The script only prints - it never writes files - and running it
# again produces a NEW value; it cannot recover the one already in use.

set -euo pipefail

if ! command -v openssl >/dev/null 2>&1; then
    echo "generate-env-secrets: 'openssl' is required but was not found on PATH." >&2
    exit 1
fi

# The API token is a plain hex token the clients send as CRAWL4AI_API_TOKEN.
api_token="$(openssl rand -hex 32)"

# The instructions go to stderr so stdout stays a clean, redirectable block.
echo "Paste the following block into .env (Required Settings section):" >&2

# The comment line keeps the block valid env syntax even when pasted
# wholesale, and records when the value was generated.
cat <<EOF
# Required settings, generated $(date '+%Y-%m-%d %H:%M:%S %Z') by generate-env-secrets.sh
CRAWL4AI_API_TOKEN=$api_token
EOF
