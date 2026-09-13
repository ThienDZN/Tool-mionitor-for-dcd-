#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [[ ! -x ".venv/bin/python" ]]; then
  echo "Missing virtual environment. Run the setup steps in README.md first."
  exit 1
fi

exec .venv/bin/python -m clip_overlay_ai
