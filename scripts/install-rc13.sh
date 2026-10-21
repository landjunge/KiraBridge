#!/usr/bin/env bash
# RC13 macOS entry point. No switch in --prepare mode.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# Fixed-width, portable ASCII (no escaped backslashes printed).
cat <<'BANNER'

  +------------------------------------------------------+
  |                                                      |
  |   K I R A   B R I D G E              RC13            |
  |                                                      |
  |            Installer / Doctor Preview                |
  +------------------------------------------------------+
BANNER

info() { printf '  [INFO] %s\n' "$*"; }
fail() { printf '  [ERROR] %s\n' "$*" >&2; exit 2; }
mode="${1:-install}"
[[ "$#" -le 1 && ( "$mode" == "install" || "$mode" == "--prepare" || "$mode" == "doctor" || "$mode" == "restart" || "$mode" == "--check" ) ]] || fail "Usage: bash scripts/install-rc13.sh [--prepare|--check|doctor|restart]"
if [[ "$mode" == "doctor" ]]; then
  exec bash "$ROOT/scripts/kirabridge-doctor.sh" check
elif [[ "$mode" == "restart" ]]; then
  printf '  Restart only KiraBridge service? [y/N] '
  read -r answer
  [[ "$answer" == y || "$answer" == Y ]] || fail "Restart cancelled."
  exec bash "$ROOT/scripts/kirabridge-doctor.sh" restart
fi
[[ "$(uname -s)" == Darwin ]] || fail "Only macOS is supported by this entry point."

info "1/3 Checking environment"
command -v git >/dev/null 2>&1 || fail "Git is required. Install Apple's Command Line Tools first: xcode-select --install"
if ! command -v uv >/dev/null 2>&1; then
  if ! command -v brew >/dev/null 2>&1; then
    fail "uv is missing and Homebrew is unavailable. Install uv from https://docs.astral.sh/uv/getting-started/installation/ and retry."
  fi
  printf '  uv is missing. Install it via Homebrew? [y/N] '
  read -r answer
  [[ "$answer" == y || "$answer" == Y ]] || fail "Declined uv installation. Nothing switched."
  brew install uv
fi
[[ -z "$(git status --porcelain --untracked-files=no)" ]] || fail "Working tree has modifications. No installation started."

# uv can provision isolated Python 3.11 without replacing the Mac's system Python.
if command -v python3 >/dev/null 2>&1 && python3 -c 'import sys; assert sys.version_info >= (3,11)' 2>/dev/null; then
  PYTHON="$(command -v python3)"
else
  info "System Python is older than 3.11. Finding isolated Python via uv..."
  if ! PYTHON="$(uv python find '>=3.11,<3.14' 2>/dev/null)"; then
    printf '  Python 3.11+ is missing. Install isolated Python 3.11 using uv? [y/N] '
    read -r answer
    [[ "$answer" == y || "$answer" == Y ]] || fail "Declined isolated Python installation. RC11 unchanged."
    uv python install 3.11
    PYTHON="$(uv python find 3.11)" || fail "Could not locate newly installed Python 3.11."
  fi
fi

info "2/3 Checking source revision"
REF="$(git rev-parse HEAD)"
info "Candidate: $REF"
info "Python: $("$PYTHON" --version 2>&1)"
if [[ "$mode" == "--check" ]]; then
  info "3/3 Checking RC13 compatibility without switching services"
  exec "$PYTHON" installer/install.py preflight --repo "$ROOT" --ref "$REF"
fi
if [[ "$mode" == "--prepare" ]]; then
  info "3/3 Preparing only (RC11 remains running)"
  exec "$PYTHON" installer/install.py prepare --repo "$ROOT" --ref "$REF"
fi
info "3/3 Installing with health check and rollback"
info "WARNING: This step attempts to switch the active KiraBridge service."
exec "$PYTHON" installer/install.py install --repo "$ROOT" --ref "$REF"
