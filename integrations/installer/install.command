#!/bin/sh
set -eu
umask 077
resources=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd -P)
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$PATH"
printf '\033]0;KiraBridge installieren\007'
printf '\nKiraBridge installieren oder aktualisieren\n\n'
"$resources/../MacOS/KiraBridgeInstaller" --verify-package > /dev/null
printf '\nDas geprüfte Installationspaket wird gestartet. Kein sudo verwenden.\n\n'
sh "$resources/Runtime/install.sh" --require-visible-terminal --desktop
printf '\nKiraBridge wurde erfolgreich installiert.\n'
