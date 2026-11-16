#!/usr/bin/env bash
# Copies the API description from the panel repository, so the contract test checks this library
# against the version of the API it claims to speak. Usage: scripts/sync-spec.sh [path-to-panel-repo]
set -euo pipefail
panel="${1:-../../commypanel}"
cp "$panel/docs/openapi.yaml" "$(dirname "$0")/../testdata/openapi.yaml"
echo "Copied $panel/docs/openapi.yaml"
