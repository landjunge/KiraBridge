#!/usr/bin/env bash
# KiraBridge Doctor: scoped diagnostics, explicit restart only.
set -euo pipefail
LABEL="com.kirabridge.bridge"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
TARGET="gui/$(id -u)"
CLI="$HOME/.local/bin/kirabridge"
usage(){ echo "Usage: bash scripts/kirabridge-doctor.sh [check|restart]"; }
case "${1:-check}" in check|restart) MODE="${1:-check}";; *) usage; exit 2;; esac
[[ "$(uname -s)" == "Darwin" ]] || { echo "macOS required"; exit 2; }
echo "KiraBridge Doctor — $MODE"
[[ -f "$PLIST" ]] || { echo "FAIL: launchd plist missing: $PLIST"; exit 1; }
[[ -x "$CLI" ]] || { echo "FAIL: launcher missing: $CLI"; exit 1; }
if [[ "$MODE" == "restart" ]]; then
  echo "Restarting only $LABEL (not all ports or network services)"
  if launchctl print "$TARGET/$LABEL" >/dev/null 2>&1; then
    launchctl bootout "$TARGET/$LABEL"
  fi
  launchctl bootstrap "$TARGET" "$PLIST"
fi
if ! launchctl print "$TARGET/$LABEL" >/dev/null 2>&1; then
  echo "FAIL: KiraBridge launchd service not registered"; exit 1
fi
echo "launchd: registered"
# 'status' performs an authenticated MCP bridge_health roundtrip to the local daemon.
# A successful launchd registration by itself cannot prove MCP responsiveness.
if ! "$CLI" status; then
  echo "FAIL: authenticated MCP health check did not succeed" >&2
  exit 1
fi
echo "PASS: local MCP health responded (inspect dispatcher_active above)."
echo "NOTE: This does not prove the external ChatGPT connector or public tunnel is reachable."
echo "Doctor finished. Review the reported health before making changes."
