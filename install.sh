#!/usr/bin/env bash
# Set up cheerbot: build the notifier app, install the LaunchAgent, start it.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "cheerbot is macOS only." >&2
  exit 1
fi

"$ROOT/bin/cheerbot" start

cat <<EOF

Installed. Handy commands:

  $ROOT/bin/cheerbot status
  $ROOT/bin/cheerbot now
  $ROOT/bin/cheerbot pause 3h

Optional, to call it from anywhere:

  ln -s "$ROOT/bin/cheerbot" /usr/local/bin/cheerbot
EOF
