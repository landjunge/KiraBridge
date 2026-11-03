# KiraBridge 0.8.0rc25

ChatGPT reconnects automatically after its local tunnel exits, including an orderly
exit following a failed MCP child process. The user service restarts at most once
per 30 seconds. Existing matching service definitions are migrated; unrelated
jobs, credentials and profiles are preserved.

A native **KiraBridge-Installieren.app** contains the complete, exact macOS runtime.
Open it and choose **Installieren**. It opens its own visible Terminal window and
runs the existing integrity-checked installer. The desktop transaction updates the
core, matching console, companion app and already-linked ChatGPT service together,
with saved definitions and a guarded rollback. No manual app copy is required.
Python 3.11 and uv 0.11.6 must be installed; dependencies are obtained from the
hashed lock file. The current package targets Intel macOS 15/26 and is ad-hoc
signed. Apple notarization is not claimed.

The automatic profile-free keyboard features from build 34f768b are included.
Permissions, existing profiles, configuration, credentials and agent sessions
remain protected by the existing checks. The release does not create an OpenAI
account link or request macOS permissions automatically.

Validation and the exact built/installed identities are recorded separately in
`docs/BOOT-RECOVERY-INSTALLER-20261102.md`. The launchd recovery test simulates
late availability; it is not a claim that another complete computer reboot was
performed.
