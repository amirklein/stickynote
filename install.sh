#!/usr/bin/env bash
# Install Sticky Note.
#
# Works two ways, because a script piped from curl has no checkout around it:
#
#   curl -fsSL https://raw.githubusercontent.com/amirklein/stickynote/main/install.sh | bash
#   ./install.sh          # from a clone, installs that clone in place
#
set -euo pipefail

REPO_URL="${STICKYNOTE_REPO:-https://github.com/amirklein/stickynote.git}"
PREFIX="${STICKYNOTE_PREFIX:-$HOME/.local/share/stickynote}"
BIN_DIR="${STICKYNOTE_BIN:-$HOME/.local/bin}"

say() { printf '%s\n' "$*"; }
die() { printf '%s\n' "$*" >&2; exit 1; }

[[ "$(uname -s)" == "Darwin" ]] || die "Sticky Note is macOS only."

command -v python3 >/dev/null 2>&1 || die \
  "python3 not found. Install the Xcode Command Line Tools: xcode-select --install"

# Badges and the settings window are compiled locally, which is also why this
# never trips Gatekeeper: nothing is downloaded already built. Without swiftc
# the AppleScript applet still delivers plain notifications.
if ! command -v swiftc >/dev/null 2>&1; then
  say "swiftc not found, so notification badges and the settings window are off."
  say "To enable them: xcode-select --install, then re-run this script."
  say ""
fi

# Find the source. A clone next to this script wins; otherwise fetch one.
SOURCE=""
if [[ -n "${BASH_SOURCE[0]:-}" && -f "$(dirname "${BASH_SOURCE[0]}")/pyproject.toml" ]]; then
  SOURCE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  say "Installing from this checkout: $SOURCE"
else
  command -v git >/dev/null 2>&1 || die "git not found, and no local checkout to install from."
  if [[ -d "$PREFIX/.git" ]]; then
    say "Updating $PREFIX ..."
    git -C "$PREFIX" pull --ff-only --quiet
  else
    say "Fetching Sticky Note into $PREFIX ..."
    mkdir -p "$(dirname "$PREFIX")"
    git clone --depth 1 --quiet "$REPO_URL" "$PREFIX"
  fi
  SOURCE="$PREFIX"
fi

mkdir -p "$BIN_DIR"
ln -sf "$SOURCE/bin/stickynote" "$BIN_DIR/stickynote"
say "Linked $BIN_DIR/stickynote"

if ! printf '%s' ":$PATH:" | grep -q ":$BIN_DIR:"; then
  say ""
  say "$BIN_DIR is not on your PATH. Add this to your shell profile:"
  say "    export PATH=\"$BIN_DIR:\$PATH\""
fi

say ""
"$SOURCE/bin/stickynote" setup --first-run
