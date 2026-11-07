# KiraBridge as a Linux server

This build runs KiraBridge as a private MCP service in a systemd user session.
It is the KiraBridge server build, not ThreadDesk Server&Sync and not the
macOS desktop installation.

## Download and prerequisites

RC41 uses the separate `linux-v0.8.0rc41` prerelease. The repository is private:
Dirk needs a GitHub account with repository access (`gh auth login`), or an
operator must provide the unchanged archive and checksums. No credentials are
included in the package.

```sh
gh release download linux-v0.8.0rc41 -R landjunge/KiraBridge \
  -p 'KiraBridge-0.8.0rc41-Linux-x86_64.tar.gz*' -p SHA256SUMS
```

Debian 13 or Ubuntu 24.04 x86_64, a normal user, `sh`, `tar`, `curl`, CA
certificates and `sha256sum` are required. For the default service, the user's
systemd manager must be running (`systemctl --user is-system-running`).
The bootstrap downloads hash-checked uv 0.11.6, CPython 3.11.15 and locked Python
dependencies from GitHub/PyPI. The host Python is not replaced. This is an
online installer, not a fully offline distribution. There is no automatic
administrator/package-manager, firewall, permissions or linger change.
With `Linger=no`, service lifetime follows the host's user-session policy;
unattended operation across logout/reboot needs an operator-managed user manager.

## Check the package

The archive is `KiraBridge-<version>-Linux-x86_64.tar.gz`. The same digest is
in `SHA256SUMS` and in `<archive>.sha256`.

```sh
sha256sum -c KiraBridge-*-Linux-x86_64.tar.gz.sha256
tar -xzf KiraBridge-*-Linux-x86_64.tar.gz
cd KiraBridge-*-Linux-x86_64
sha256sum -c SHA256SUMS
```

Stop if a checksum differs. The package accepts Debian 13 and Ubuntu 24.04 on x86_64.

## Install and update

Run as your normal user, without `sudo`:

```sh
sh install.sh --yes --language en
```

Prepare the runtime without a service: `sh install.sh --prepare-only --yes --language en`.
Install the launcher without a service: `sh install.sh --yes --language en --service none`.

`install.sh` checks the package, places the pinned runtime under
`~/.local/share/kirabridge/releases/<version>-<commit>`, and runs
`installer/install.py`. An existing configuration and existing credentials
are kept. New tasks, results and UNKNOWN states stay in the current database.
Rollback does not copy an old database backup over that data.

The service is the user unit `kirabridge.service`:

```sh
systemctl --user status kirabridge.service
systemctl --user restart kirabridge.service
```

The unit follows `examples/kirabridge.service`. `secrets.env` is optional.
If that file is missing, the service still starts. The installer does not
enable linger and does not install a system-wide unit.

For an update, download and verify the new archive, extract it into a new
folder, and run the same `sh install.sh --yes --language en` there. Keep the
previous runtime folder for rollback. Repeating installation of the same source
is supported. Existing configuration, port, credentials and permission policy
are preserved. A fresh installation uses `127.0.0.1:8765`; `--port NUMBER`
selects a different port for a fresh configuration only.

An isolated installation may supply `--install-dir`, `--prefix`, `--config`,
`--launcher`, `--unit` (a user-unit path under `~/.config/systemd/user/`) and
`--workspace`. Supply the same paths for updates and the corresponding
`--plist` path to the Python rollback command. Never point test commands at an
existing production configuration or unit.

## Access

The service speaks HTTP only on its configured loopback endpoint.
Every call needs `Authorization: Bearer`. A missing or wrong token gets
HTTP 401. Keep the loopback binding; use an SSH tunnel from a trusted client
if remote transport is needed, for example `ssh -N -L 18765:127.0.0.1:8765 user@host`.
The client endpoint is then `http://127.0.0.1:18765/mcp`. Retrieve the bearer
credential locally from the private `~/.config/kirabridge/credentials.json`;
never put it in a URL, command history or report. A ChatGPT connection, public
HTTPS endpoint and account linking require separate configuration and are not
established by this installation. `bridge_health` is the authenticated health call. It confirms
the local dispatcher, not a ChatGPT connection.

## Limits

This server has no macOS GUI, no Terminal.app, no native keyboard control
and no desktop session. The clipboard works only when `wl-clipboard` or
`xclip` is installed, and the server does not require it. `platform.status`
and `bridge_health` report these limits. They do not claim GUI parity.

Native Debian package results are supplied as the prerelease's evidence and
JUnit assets and tracked in `docs/evidence/debian-dirktest-release-20261107.json`.
Groks earlier `linux-server-grok-20261107.json` describes the unaccepted RC40
baseline. A macOS test or Ubuntu container run is not native Debian acceptance.

## Rollback

Use the same paths as the installation:

```sh
~/.local/share/kirabridge/releases/<version>-<commit>/.venv/bin/python3 \
  installer/install.py rollback \
  --prefix "${XDG_DATA_HOME:-$HOME/.local/share}/kirabridge/install" \
  --config "${XDG_CONFIG_HOME:-$HOME/.config}/kirabridge/config.toml" \
  --launcher "$HOME/.local/bin/kirabridge" \
  --service systemd-user
```

Rollback restores the previous launcher and unit. Configuration, credentials,
tasks and UNKNOWN states remain the current files.
