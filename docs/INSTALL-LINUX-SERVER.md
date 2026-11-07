# KiraBridge as a Linux server

This build runs KiraBridge as a private MCP service in a systemd user session.
It is the KiraBridge server build, not ThreadDesk Server&Sync and not the
macOS desktop installation.

## Check the package

The archive is `KiraBridge-<version>-Linux-x86_64.tar.gz`. The same digest is
in `SHA256SUMS` and in `<archive>.sha256`.

```sh
sha256sum -c KiraBridge-*-Linux-x86_64.tar.gz.sha256
tar -xzf KiraBridge-*-Linux-x86_64.tar.gz
cd KiraBridge-*-Linux-x86_64
sha256sum -c SHA256SUMS
```

Stop if a checksum differs. The package is built for Ubuntu 24.04 on x86_64.
Other distributions are not accepted by that check.

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

## Access

The service speaks HTTP only on its configured loopback endpoint.
Every call needs `Authorization: Bearer`. A missing or wrong token gets
HTTP 401. `bridge_health` is the authenticated health call. It confirms
the local dispatcher, not a ChatGPT connection.

## Limits

This server has no macOS GUI, no Terminal.app, no native keyboard control
and no desktop session. The clipboard works only when `wl-clipboard` or
`xclip` is installed, and the server does not require it. `platform.status`
and `bridge_health` report these limits. They do not claim GUI parity.

A macOS test is not Linux acceptance. The native result is recorded
separately in `docs/evidence/linux-server-grok-20261107.json`.

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
