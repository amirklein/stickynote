#!/usr/bin/env bash
# Set up stickynote: build the notifier app, install the LaunchAgent, start it.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "stickynote is macOS only." >&2
  exit 1
fi

"$ROOT/bin/stickynote" start

cat <<EOF

Installed. Handy commands:

  $ROOT/bin/stickynote status
  $ROOT/bin/stickynote now
  $ROOT/bin/stickynote pause 3h

Optional, to call it from anywhere:

  ln -s "$ROOT/bin/stickynote" /usr/local/bin/stickynote
EOF
