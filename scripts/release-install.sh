#!/bin/sh
# Packaged with pinned source. Never pipe a remote script into a shell.
set -eu
umask 077
language=de
prepare_only=false
install_dir="${HOME}/.local/share/kirabridge/releases/0.6.0rc2-@SOURCE_SHORT@"
while [ "$#" -gt 0 ]; do
  case "$1" in
    --language) language="$2"; shift 2 ;;
    --prepare-only) prepare_only=true; shift ;;
    --install-dir) install_dir="$2"; shift 2 ;;
    *) printf '%s\n' 'Usage: sh install.sh [--language de|en] [--prepare-only] [--install-dir PATH]' >&2; exit 1 ;;
  esac
done
case "$language" in de|en) ;; *) exit 1 ;; esac
say() { if [ "$language" = de ]; then printf '%s\n' "$1" >&2; else printf '%s\n' "$2" >&2; fi; }
fail() { say "$1" "$2"; exit 1; }
[ "$(id -u)" != 0 ] || fail 'Bitte als normaler Benutzer starten, ohne sudo.' 'Run as your normal user, without sudo.'
bundle=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
platform="$(uname -s)-$(uname -m)"
[ "$platform" = '@PLATFORM@' ] || fail 'Dieses Paket passt nicht zum Rechner. Passendes Release-Paket wählen.' 'This package does not match your computer. Choose the matching release package.'
case "$platform" in
  Darwin-x86_64|Darwin-arm64) case "$(sw_vers -productVersion)" in 15.*) ;; *) fail 'RC geprüft auf macOS 15.' 'RC tested on macOS 15.' ;; esac ;;
  Linux-x86_64) [ -f /etc/os-release ] && grep -q '^ID=ubuntu$' /etc/os-release && grep -q '^VERSION_ID="24.04"$' /etc/os-release || fail 'RC geprüft auf Ubuntu 24.04 x86_64.' 'RC tested on Ubuntu 24.04 x86_64.' ;;
  *) exit 1 ;;
esac
say '=== KiraBridge · 0.6.0rc2 ===' '=== KiraBridge · 0.6.0rc2 ==='
say 'Lizenz: Netzwerkpunkt Personal Use License 1.0 (beiliegende LICENSE). Private nicht geschäftliche Nutzung kostenlos; geschäftlich nur mit gesonderter schriftlicher Erlaubnis. Deutsch ist maßgeblich. Kein OSI-Standard und nicht anwaltlich geprüft.' 'License: Netzwerkpunkt Personal Use License 1.0 (included LICENSE). Private non-business use is free; business use needs separate written permission. German governs. Not an OSI standard or legal review.'
say '[1] Paket prüfen und Voraussetzungen erkennen' '[1] Verify package and detect prerequisites'
if command -v sha256sum >/dev/null 2>&1; then
  checksum() { sha256sum "$@"; }
else
  command -v shasum >/dev/null 2>&1 || fail 'SHA-256-Werkzeug fehlt: shasum oder sha256sum bereitstellen.' 'SHA-256 tool missing: provide shasum or sha256sum.'
  checksum() { shasum -a 256 "$@"; }
fi
(cd "$bundle" && checksum -c SHA256SUMS >/dev/null) || fail 'Paket-Prüfsumme falsch. Originalpaket erneut beziehen.' 'Package checksum mismatch. Obtain the original package again.'
say 'Laufzeit wird nur für deinen Benutzer installiert. Netzwerkdownloads von GitHub/PyPI und ggf. Python sind erforderlich. Keine Administratorrechte; vorhandene Zugänge bleiben erhalten.' 'Runtime is installed for your user only. Network downloads from GitHub/PyPI and possibly Python are needed. No administrator rights; existing credentials are preserved.'
say 'Fortfahren? [j/N]' 'Continue? [y/N]'
IFS= read -r answer || exit 1
case "$answer" in j|J|ja|y|Y|yes) ;; *) exit 0 ;; esac
case "$install_dir" in /*) ;; *) fail 'Installationspfad muss absolut sein.' 'Installation path must be absolute.' ;; esac
[ ! -L "$install_dir" ] || fail 'Symbolischer Installationspfad abgelehnt.' 'Symlink installation path rejected.'
mkdir -p "$(dirname "$install_dir")"
lock="${install_dir}.installer-lock"
mkdir "$lock" 2>/dev/null || fail 'Ein Installer läuft bereits. Zustand prüfen; nicht parallel starten.' 'An installer is already running. Inspect its state; do not run in parallel.'
scratch=$(mktemp -d "${TMPDIR:-/tmp}/kirabridge-install.XXXXXXXX")
trap 'rm -rf "$scratch"; rmdir "$lock"' EXIT HUP INT TERM
uv_bin=$(command -v uv || true)
if [ -z "$uv_bin" ] || [ "$("$uv_bin" --version)" != 'uv 0.11.6' ]; then
  command -v curl >/dev/null 2>&1 || fail 'curl fehlt. Bitte curl bereitstellen und erneut starten.' 'curl is missing. Provide curl and retry.'
  case "$platform" in
    Darwin-x86_64) target=x86_64-apple-darwin; uv_sha=8e0ed5035eaa28c7c8cd2a46b5b9a05bfff1ef01dbdc090a010eb8fdf193a457 ;;
    Darwin-arm64) target=aarch64-apple-darwin; uv_sha=4b69a4e366ec38cd5f305707de95e12951181c448679a00dce2a78868dfc9f5b ;;
    Linux-x86_64) target=x86_64-unknown-linux-gnu; uv_sha=0c6bab77a67a445dc849ed5e8ee8d3cb333b6e2eba863643ce1e228075f27943 ;;
  esac
  say 'uv 0.11.6 vom Originalanbieter laden und SHA-256 prüfen …' 'Downloading uv 0.11.6 from its original publisher and checking SHA-256 …'
  curl --fail --location --proto '=https' --tlsv1.2 --retry 2 --connect-timeout 15 --max-time 120 --max-filesize 50000000 \
    "https://github.com/astral-sh/uv/releases/download/0.11.6/uv-${target}.tar.gz" -o "$scratch/uv.tar.gz" || fail 'Laufzeitdownload fehlgeschlagen. Netzwerk prüfen, denselben Befehl erneut starten.' 'Runtime download failed. Check your network and rerun the same command.'
  actual=$(checksum "$scratch/uv.tar.gz"); actual=${actual%% *}
  [ "$actual" = "$uv_sha" ] || fail 'uv-Prüfsumme falsch; nichts ausgeführt.' 'uv checksum mismatch; nothing executed.'
  tar -xzf "$scratch/uv.tar.gz" -C "$scratch"
  uv_bin="$scratch/uv-${target}/uv"
fi
if [ -e "$install_dir" ]; then
  [ -f "$install_dir/.kirabridge-source" ] && [ "$(cat "$install_dir/.kirabridge-source")" = '@SOURCE@' ] || fail 'Anderer/unvollständiger Installationsordner bleibt erhalten. Zustand prüfen oder anderen --install-dir wählen.' 'Different/incomplete install folder preserved. Inspect it or choose another --install-dir.'
else
  mkdir -m 700 "$install_dir"
  cp -R "$bundle/payload/." "$install_dir/"
  printf '%s\n' '@SOURCE@' > "$install_dir/.kirabridge-source"
fi
say '[2] Gepinnte Laufzeit und KiraBridge vorbereiten …' '[2] Preparing pinned runtime and KiraBridge …'
"$uv_bin" sync --project "$install_dir" --locked --no-dev --no-build-package cryptography --python 3.11.15 || fail 'Vorbereitung fehlgeschlagen. Netzwerk/Platz prüfen. Bei fehlender Binärdatei passendes Paket verwenden; keine Compilerinstallation wird erzwungen. Derselbe Befehl kann wiederholt werden; bestehende Konfiguration bleibt erhalten.' 'Preparation failed. Check network/disk space. For a missing binary wheel use the matching package; no compiler installation is forced. You can rerun the same command; existing configuration is preserved.'
if [ "$prepare_only" = true ]; then
  say 'Vorbereitung fertig. Kein Dienst und keine Kontoeinrichtung verändert.' 'Preparation complete. No service or account configuration changed.'
  exit 0
fi
exec "$install_dir/.venv/bin/python3" -m kirabridge.cli install --language "$language" --release-root "$install_dir"
