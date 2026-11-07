#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [[ ! -x ".venv/bin/python" ]]; then
  echo "Missing virtual environment. Run the setup steps in README.md first."
  exit 1
fi

# Wayland hotkeys read /dev/input, which needs the 'input' group. If the user
# was added to the group but this login session predates it, re-run under the
# group with sg so there is no need to log out first.
if [[ "${XDG_SESSION_TYPE:-}" == "wayland" ]] \
  && id -nG "$(id -un)" | grep -qw input \
  && ! id -nG | grep -qw input; then
  exec sg input -c "$(printf '%q ' "$PWD/run.sh" "$@")"
fi

exec .venv/bin/python -m clip_overlay_ai "$@"
