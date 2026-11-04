# Windows RC33 installer: native acceptance · 4 November 2026

The exact production Setup.exe was compiled in the existing Windows 11 x64 VM
and accepted through the evidence chain below. The three original instances were
preserved. Successful phases were retained across test harness corrections;
the three original failed receipts remain failed and were not overwritten.

Artifact: `KiraBridge-0.8.0rc33-Windows-x64-Setup.exe`, **25,018,593 bytes**,
SHA256 `41203ce70d31795d7dc1ace80a40a462f5f834c7fea02165544cc3c7f7e83d91`.
Native Inno Setup 6.7.4 compilation passed; its portable compiler had a valid
Pyrsys B.V. signature and did not add an installed compiler registry identity.
Runtime source is RC33 `ce0687dd8831dae261bf285922a146bcf3aedc41`.

| Area | Observed result |
| --- | --- |
| First install and same-version reinstall | Both Setup exit 0; expected current pointer/version/data location; configuration preserved. |
| Concurrent maintenance | A native held mutex made Setup and uninstaller refuse with exit 1; current pointer remained unchanged. |
| Start Menu and launcher | Three actual default-group targets point to the owned app; shipped PowerShell launcher Status returned the expected state. |
| Installed runtime | HTTP 401 without credentials; authenticated health, eight capabilities, five Windows operations, zero tasks. Owned process stopped with CTRL_BREAK and independently absent. |
| Busy application | Upgrade exit 7 and uninstall exit 1; live process generation, pointer and credentials preserved. |
| Invalid configuration and downgrade | Exit 7; malformed configuration and synthetic newer-version pointer preserved. |
| Upgrade | Actual reinstall plus explicitly synthetic prior-version metadata upgrade passed. No historical Windows installer existed for a genuine older-package upgrade. |
| Rollback | Distinct owned runtime prepared and committed; journal recovery restored the prior pointer and preserved data. |
| Data retention | Reinstall retained closed/checkpointed SQLite bytes, credentials, configuration and user file; integrity `ok`, one sentinel row, zero tasks. |
| Configuration form | Root opened the real form, observed endpoint/port/data location, cancelled without saving and checked retained hashes. |
| Final uninstall | Root used a separately named Inno log, retained the process handle, waited for observed exit 0, and returned to the owned prompt. |
| Final independent observer | Registry in both views, current pointer, launch script, uninstaller and Start Menu group absent. Four data hashes equal the closed baseline. Existing dev2/dev3/RC33 module trees, credentials, launchers, process generations and listeners unchanged. |

## Corrections retained in the evidence

1. The initial harness assumed `/GROUP` changed a group while
   `DisableProgramGroupPage=yes`. Inno ignores that argument in this case.
   The actual default folder and three targets were observed with creation times
   belonging to the fresh test installation; only the remaining cases continued.
2. The next run observed clean-uninstall exit 0 but failed an immediate combined
   absence/hash assertion. Later individual observations confirmed removal.
   The harness had also kept SQLite open: `with sqlite3.connect(...)` commits,
   but does not close. Closing/checkpointing changed the main-file hash while
   preserving the sentinel and zero tasks. The old main-file-only baseline was
   therefore not treated as a stable closed database snapshot. A new own FULL
   checkpoint (busy 0), explicit close and four-file baseline passed reinstall
   and final readback. Both harness connection scopes now close explicitly.
3. A tail harness log collision made the last uninstall return 1: process stdout
   and Inno `/LOG` named the same open file. Root completed only that remaining
   uninstall with a distinct log. Stdout paths now end in `-stdout.log`; a host
   guard rejects equal/case-colliding paths. Its focused regression test passed.

Raw wrapper receipt SHA256s remain:

- Initial failure: `cf00895e0b8872573353404523bd061c8dc01b7417cff4cb65090b8c0c9b8630`
- Continuation failure: `59c02bcbce8ee83431b1a4327c3ef7cebd611fe21b598222132e078f3c8557cc`
- Tail failure: `d6786e5348ba3cf79b4f2f1a09d2ad537fab750b08c1e9052d1999f357b9f9f9`
- Final successful read-only observation: `fe42a6b1fb77e7397b6be55503d3172b1c7072861400e44684a514b327a6af90`

The final observer finished at **16:13:09 UTC**. Program components and product
references were removed; an **empty application test directory remains**.
The separate retained data directory is intentional. Raw logs, screenshots,
tokens, credentials and user paths remain private. Machine-readable results,
child receipt hashes and visual evidence hashes are in
[the curated native evidence](../evidence/windows-installer-native-20261104.json).
Root closed the confirmed idle owned guest tab; a fresh independent display showed only the original historical tab. All eight task-owned host staging/artifact helpers were stopped after command-identity checks and independently absent. The VM remains running.

## Boundaries

The configuration form was observed natively; the German Setup wizard and a
full interactive wizard click-through were not accepted. Windows 10, ARM,
downloaded-file SmartScreen/signing reputation, power-failure recovery and a
historical older Windows installer upgrade were not tested. The runtime smoke
used the installed Python/lifecycle entry; no Start Menu launch click-through
is claimed. RC33 retains its desktop development-preview feature scope.
No hosted CI, ARM build, VM rebuild/reconfiguration or productive upgrade was
performed by this acceptance.
