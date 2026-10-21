#!/usr/bin/env bash
# Run from a checkout of the reviewed RC13 repair branch.
# Keeps the currently running bridge intact until the installer's readiness checks pass.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
printf '\\n'
cat <<'BANNER'
 _  ___           ____       _     _
| |/ (_)_ __ __ _| __ ) _ __(_) __| | __ _  ___
| ' /| | '__/ _` |  _ \\| '__| |/ _` |/ _` |/ _ \\
| . \\| | | | (_| | |_) | |  | | (_| | (_| |  __/
|_|\\_\\_|_|  \\__,_|____/|_|  |_|\\__,_|\\__, |\\___|
                                           |___/
BANNER
printf '  [1/3] Checking prerequisites...\\n'
if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This macOS installer requires macOS." >&2; exit 2
fi
for cmd in git uv python3; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "Missing prerequisite: $cmd (installation not started)." >&2; exit 2
  fi
done
if ! python3 -c 'import sys; assert sys.version_info >= (3, 11)' 2>/dev/null; then
  echo "Python 3.11 or newer required; installation not started." >&2; exit 2
fi
if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
  echo "Checkout has local changes; refusing to install from an ambiguous source." >&2; exit 2
fi
printf "  [2/3] Checking pinned Git revision...\\n"
REF="$(git rev-parse HEAD)"
printf 'RC13 candidate commit: %s\n' "$REF"
printf 'Current KiraBridge remains active until the installer switches under idle guard.\n'
# --prepare only builds the candidate package. Nothing is switched.
if [[ "${1:-}" == "--prepare" ]]; then
  exec python3 installer/install.py prepare --repo "$ROOT" --ref "$REF"
fi
if [[ "$#" -ne 0 ]]; then
  echo "Usage: bash scripts/install-rc13.sh [--prepare]" >&2; exit 2
fi
printf "  [3/3] Preparing and validating RC13...\\n"
exec python3 installer/install.py install --repo "$ROOT" --ref "$REF"
