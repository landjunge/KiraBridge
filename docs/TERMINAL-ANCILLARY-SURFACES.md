# Terminal.app ancillary surface proof

Development source for the existing macOS creation and isolation path. Source
tests and replay of recorded native reads do not create a window, install a
package or establish live acceptance.

## Observed failure

Terminal.app in full screen can expose complete, empty `AXUnknown` windows for
menu surfaces, plus a separate CoreGraphics toolbar surface. Treating every
non-minimized `AXWindow` as a normal terminal window rejects that inventory before
the existing creation call. `max_value_chars` limits AXValue; it does not limit
window titles, which have their own truncation flag.

`TerminalAppTransport.open` performs `TerminalWindowProof.prepare` before the
creation `try` block. A preparation error therefore carries no creation receipt;
an error after creation is wrapped as `session_open_unknown`. Existing uncertain
task statuses and their events remain unchanged. A corrected source is not
authority to replay an old attempt.

## Partition and retained evidence

All observed CoreGraphics surfaces retain the exact Terminal owner and process
start, complete title availability, on-screen state and distinct window IDs.
Normal AX standard windows are positively matched to layer-zero CG windows by
geometry and, when coherent, title. A unique geometry match permits observation
of a working foreign terminal whose spinner changes between CG and AX reads; it
does not establish an input target. Multiple possible matches are rejected.

An AXUnknown window qualifies only as passive inventory when it is non-minimized,
unfocused, untitled, untruncated, has empty identifier and description, exactly
the `AXRaise` action, finite geometry and a complete empty child list. Its geometry
multiset must match the same owner's untitled layer-26 CG cohort exactly. Unknown
interactive, incomplete or unmatched windows remain errors.

Those AX tokens and every unmatched CG surface, including a layer-zero toolbar,
are retained in an ancillary partition. Their identities, owner, layer and
geometry must remain unchanged across creation and any detach. They never enter
the own-window or shared-host candidate sets. An original ancillary identity
cannot become the new own window even if it later displays the creation nonce.

The original guards remain: exact creation receipt and nonce in both title
channels, coherent own geometry, exact logical TTY inventory, native helper and
Terminal generations, retained foreign tab identities and the final physical
partition check before command submission. No minimized window is restored or
adopted. A changed full-screen/Space inventory can still stop the operation; the
adapter does not guess a replacement or repeat creation.

## Verification and operator use

Fixtures cover stable ancillary inventory for separate and shared creation,
foreign title changes, malformed unknown surfaces, owner and geometry changes,
missing/replaced passive identities, ambiguous CG matches and attempts to reuse
an old ancillary identity as the new window. Existing isolation, minimized-window,
hidden-host, AX-transition and failure-diagnostic cases remain applicable.

The separate `SessionManager(SessionPorts)` constructor is an internal product
boundary, independent of the Bridge dispatcher. Its existing local operator
window grant and `window_dispatches` ledger retain exact task/argument binding
and single dispatch. Using reviewed source at this boundary must retain those
authorization gates and the same existing ledger; it must not instantiate a
second Bridge or queue. Read-only observation may use the authenticated existing
Bridge's `read_query` path, preserving its current native helper. The product
creation/isolation/command path and installer visibility checks remain mandatory.
This document grants no operation and supplies no new generic shell fallback.
