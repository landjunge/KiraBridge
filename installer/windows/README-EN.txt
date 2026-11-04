KiraBridge RC33 for Windows 11 x64

Setup installs KiraBridge and a private Python runtime entirely offline for
your Windows user. Any existing Python installation remains independent.
Start menu: Start KiraBridge, Configure KiraBridge, Uninstall KiraBridge.
Close the KiraBridge console to stop it before an upgrade or uninstallation.

Configure shows the local MCP endpoint and data directory, and lets you select
a port from 1024 upwards. Default port: 8768. Configuration, credentials and
task history normally live under %LOCALAPPDATA%\KiraBridge\Data. Upgrades and
uninstallation preserve them. Reinstallation reuses them. Previous Dev Kit
installations are not migrated or stopped automatically.

Installation failures restore the previously selected runtime. After a power
failure, rerun Setup with the same directory. Damaged packages, active
KiraBridge sessions and downgrades are rejected. Setup writes a log in the
Windows temporary directory. Keyboard and window actions are never retried
automatically.

RC33 remains a development preview: authenticated local MCP, native keyboard,
shortcuts and guarded window control. General file/process/terminal tools and
a Windows service are outside its scope. No startup item, firewall or PATH
changes. Use only in your own active Windows desktop. Unsigned preview builds
may show a Windows publisher warning; checksums are not publisher signatures.

License: included LICENSE.txt. Third-party licenses remain in the runtime.
