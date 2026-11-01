# KiraBridge 0.8.0rc24 · terminal selection and observation failures

An explicitly selected Terminal.app tab now uses only its native catalogue.
An unrelated tmux read failure can no longer block that selection. Explicit
tmux selection likewise avoids unrelated native observations. General discovery
continues to report both transports and their individual availability.

Read-only process catalogue, identity and shell-snapshot timeouts now preserve
their responsible phase as a typed observation error. A read failure never proves
input, Return, successful execution or permission to replay an uncertain task.
Existing observation deadlines, owned-subprocess cleanup and target guards remain.

This continues the RC23 investigation. The historical pre-paste TimeoutError has
no uniquely established cause; these are independently reproducible failure paths.
Actual tests, package verification and physical acceptance are recorded separately
in [the continuation report](RC24-PREFLIGHT-20261101.md). Publication or installation
is not established by this candidate document.

Deutsch: Die Auswahl eines konkreten Terminalfensters hängt nicht mehr von
unbeteiligten tmux-Abfragen ab. Lesetimeouts melden ihre zuständige Phase.
Die Prüfungen von Prozessidentität, mehrdeutigen Ansichten und beschäftigten
Zielen bleiben bestehen. Die vollständige Prompt-/Return-Abnahme ist gesondert
nachzuweisen.
