# KiraBridge RC21: installation and help

[Deutsch](INSTALL-RC21.de.md) · [README](../README.md)

This guide follows the [published RC21 package instructions](https://github.com/landjunge/KiraBridge/releases/download/v0.8.0rc21/INSTALLIEREN-RC21-INTEL.txt). Download source: `7ea0f24ae6c36f689d0889d41071fa8bca8aaf65`.

## Requirements

Intel Mac, tested on macOS 15.7.4; Python 3.11 and uv 0.11.6 available in Terminal. Downloads require a GitHub account with access to the private repository. Dependencies are downloaded as needed. No Swift compiler is required. The app is ad-hoc signed and not Apple-notarized. This package has not been accepted for Apple Silicon or other macOS versions.

## Install or update

1. Download and fully extract the [app and service installer ZIP](https://github.com/landjunge/KiraBridge/releases/download/v0.8.0rc21/KiraBridge-0.8.0rc21-Intel-macOS.zip). Compare its checksum with [SHA256SUMS-INTEL](https://github.com/landjunge/KiraBridge/releases/download/v0.8.0rc21/SHA256SUMS-INTEL).
2. Open `KiraBridge-Installieren.command`. The installer runs in a visible Terminal window. Use your regular user account without sudo, and do not install inside a working Codex/Grok session.
3. Copy `KiraBridge.app` into `~/Applications` and open it. Close an existing app before replacing it. The app needs the service installed in step 2.
4. Follow the [ChatGPT connection guide](CHATGPT.md#english-connect-then-confirm-the-actual-task). Grok Build or Codex need their own installation, sign-in and a configured terminal session as a target.

The installer preserves existing configuration and credentials, checks running work and prepares a recovery path. An already running installation of the same source does not need reinstalling.

## Known limits and help

The [RC21 release notes](https://github.com/landjunge/KiraBridge/releases/tag/v0.8.0rc21) document the verified scope and limits. Short wrapped inputs can be refused before Return with `visible_paste_unconfirmed`. Historical uncertain handoffs are not automatically replayed. Delivery, agent reply and completed work remain separate. Chat approval does not grant missing OS permissions. Not all Live/Voice workflows have been accepted.

The [detailed previous guide](INSTALL-EN.md) preserves RC20 diagnostics and recovery. Use its older download commands only when deliberately selecting that earlier version. [Developer documentation](DEVELOPERS.md).
