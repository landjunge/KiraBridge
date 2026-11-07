> Update: RC36 was subsequently installed and its tab-switch failure reproduced.
> The local RC37 repair is installed and natively verified on Intel; see
> [current recovery evidence](TERMINAL-RECOVERY-20261104.md). Historical tasks below remain unchanged.

# RC36 · create an owned window while existing windows are minimized

The RC35 install bootstrap task `terminal_rc35_install_20261104` failed before
creation in the running RC34 Core, as `unknown / session_window_inventory_pending`.
No CreationReceipt or installation-start marker existed. The original task is
preserved and was not replayed.

Two subsequent authorized native reads showed the same Terminal process birth
and worker generation: zero on-screen CG windows, three AXWindow list entries,
and three AXWindow root children all freshly marked minimized=true. Their
AXDialog subrole is valid for this opaque minimized state. Treating every AX
window as a visible CG surface caused a persistent false refusal. This was not
a transient count race and was not treated with blind retries.

The fix preserves complete AX enumeration and fresh per-token minimized proof,
keeps those anchors opaque and unchanged across all phases, and compares CG only
with strict visible standard groups. A wholly minimized baseline does not
activate or restore existing windows. A newly owned visible window still needs
all process/helper/TTY/nonce/geometry proofs. Automatic restoration or anchor
change stops creation/isolation; no arbitrary minimized state is accepted.

Five new cases and 29 existing window/diagnostic cases passed. Two new synthetic
AX fixtures initially lacked an existing pagination field; only those fixtures
were corrected and those cases rerun. Independent implementation review found
no blocker. Native code and OS permissions were not changed.

Because the old production window opener cannot handle this baseline, one
verified candidate standard session.open task may bootstrap the single owned
installation window using a private state database, no production listener,
and rights copied from and narrowed below the existing principal policy. This
private bootstrap is not a production installation proof. The regular visible
installer and subsequent actual production source/function checks remain
mandatory. No historical unknown request is repeated.

## Published package and actual installation limit

RC36 is published at https://github.com/landjunge/KiraBridge/releases/tag/v0.8.0rc36,
source `d4aebdd89a206045731f2692a3f363fddaa15ee0`. All ten published downloads
match the local assets and GitHub digests; package smoke, independent code/package
review, native source pin and strict signature passed.

RC36 is not installed. The private bootstrap created one owned logical window,
then stopped before argv because focus was unconfirmed. Fresh independent CG
evidence does not place its nonce on a visible surface. One exact own-window menu
selection stopped with macOS -1728; its menu effect is uncertain and was not replayed.
No installer-launch marker or install result exists. Production remains verified
RC34. The original eleven protected process identities and four configuration/
credential hashes remain unchanged. Further input requires positive physical
window identity; no broad failure-to-detach fallback is permitted.

See the [complete chain report and minimal test plan](TERMINAL-KETTE-20261104.md)
and [machine-readable delivery status](evidence/rc36-delivery-status-20261104.json).
