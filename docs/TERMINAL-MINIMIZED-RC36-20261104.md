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

Five new cases and29 existing window/diagnostic cases passed. Two new synthetic
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
