#!/bin/bash
# Human-friendly macOS launcher, preserves all existing expert commands.
set -u
SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND="${KIRABRIDGE_BACKEND:-$HOME/.local/bin/kirabridge-core}"
LABEL="com.kirabridge.bridge"
TARGET="gui/$(id -u)"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
GREEN="$(printf '\033[32m')"; RED="$(printf '\033[31m')"; YELLOW="$(printf '\033[33m')"; RESET="$(printf '\033[0m')"
line(){ printf '  %b●%b %-19s %s\n' "$1" "$RESET" "$2" "$3"; }
headup(){ printf '\n  ╭──────────────────────────────────────────────╮\n  │           K I R A  B R I D G E              │\n  │               Kommandozentrale              │\n  ╰──────────────────────────────────────────────╯\n\n'; }
health(){
  local data
  if ! data="$("$BACKEND" status 2>/dev/null)"; then return 1; fi
  printf '%s' "$data" | /usr/bin/python3 -c 'import json,sys; d=json.load(sys.stdin); assert d.get("dispatcher_active") is True; print(d.get("version","unbekannt"))' 2>/dev/null
}
show(){
  local version
  headup
  if version="$(health)"; then
    line "$GREEN" "KiraBridge" "LÄUFT ($version)"
    line "$GREEN" "MCP / Dispatcher" "ANTWORTET"
  else
    line "$RED" "KiraBridge" "NICHT ERREICHBAR"
    line "$RED" "MCP / Dispatcher" "NICHT BESTÄTIGT"
  fi
  line "$YELLOW" "ChatGPT" "LOKAL NICHT VERIFIZIERBAR"
  line "$YELLOW" "ThreadDesk" "HIER NICHT GETESTET"
  line "$YELLOW" "Codex / Grok" "NICHT GETESTET"
  printf '\n  Grün = bestätigt  Rot = Fehler  Gelb = nicht geprüft\n'
}
repair(){
  if health >/dev/null 2>&1; then return 0; fi
  printf '\n  Prüfe nur den KiraBridge-Dienst ...\n'
  if [ ! -f "$PLIST" ]; then
    printf '  Reparatur nicht möglich: LaunchAgent fehlt.\n'; return 1
  fi
  if launchctl print "$TARGET/$LABEL" >/dev/null 2>&1; then
    launchctl kickstart "$TARGET/$LABEL" >/dev/null 2>&1 || true
  else
    launchctl bootstrap "$TARGET" "$PLIST" >/dev/null 2>&1 || true
  fi
  local i
  for i in 1 2 3 4 5; do
    if health >/dev/null 2>&1; then return 0; fi
    sleep 1
  done
  return 1
}
case "${1:-}" in
  "" )
    repair || true
    show
    printf '\n  Hilfe: kirabridge -doctor\n\n'
    ;;
  -doctor|doctor )
    repair || true
    show
    if health >/dev/null 2>&1; then
      printf '\n  ✓ Dienstprüfung bestanden. Andere Verbindungen separat prüfen.\n\n'
    else
      printf '\n  ✗ Dienst antwortet nicht. Details: kirabridge service status\n\n'
      exit 1
    fi
    ;;
  * )
    exec "$BACKEND" "$@"
    ;;
esac
