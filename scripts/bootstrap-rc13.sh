#!/usr/bin/env bash
# KiraBridge RC13 single-command bootstrap. Never silently overwrites an existing checkout.
set -euo pipefail
REPO="https://github.com/landjunge/KiraBridge.git"
BRANCH="fix/rc13-installer-readiness-20261021"
DEST="${KIRABRIDGE_RC13_DIR:-$HOME/.local/share/kirabridge/rc13-installer-source}"
ACTION="${1:---prepare}"
case "$ACTION" in --prepare|install|doctor|restart) ;; *) echo "Usage: bootstrap-rc13.sh [--prepare|install|doctor|restart]" >&2; exit 2;; esac
command -v git >/dev/null 2>&1 || { echo "Git missing; install macOS Command Line Tools with xcode-select --install" >&2; exit 2; }
mkdir -p "$(dirname "$DEST")"
if [[ -e "$DEST" || -L "$DEST" ]]; then
  [[ ! -L "$DEST" ]] || { echo "Refusing symlink source location: $DEST" >&2; exit 2; }
  [[ -d "$DEST/.git" && ! -L "$DEST/.git" ]] || { echo "Refusing to replace non-repository: $DEST" >&2; exit 2; }
  [[ -z "$(git -C "$DEST" status --porcelain)" ]] || { echo "Uncommitted source changes at $DEST; refusing update" >&2; exit 2; }
  [[ "$(git -C "$DEST" branch --show-current)" == "$BRANCH" ]] || { echo "Unexpected checked out branch; refusing update" >&2; exit 2; }
  [[ "$(git -C "$DEST" remote get-url origin)" == "$REPO" ]] || { echo "Unexpected origin at $DEST; refusing update" >&2; exit 2; }
  git -C "$DEST" fetch origin "$BRANCH"
  git -C "$DEST" merge --ff-only "origin/$BRANCH"
else
  git clone --depth 1 --single-branch --branch "$BRANCH" "$REPO" "$DEST"
fi
echo "KiraBridge source ready at $DEST"
exec bash "$DEST/scripts/install-rc13.sh" "$ACTION"
