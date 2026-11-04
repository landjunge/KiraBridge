# KiraBridge 0.8.0rc36

RC36 fixes a live, reproducible window-opening refusal when the existing
Terminal windows are minimized. Accessibility still lists these windows while
the on-screen CoreGraphics catalogue contains no surfaces. The old equality
check compared different populations and prevented creation of any new window.

Every minimized window is now read freshly and retained only as an opaque
identity anchor. The complete accessibility inventories must still agree.
Only non-minimized strict standard windows participate in the on-screen CG
count and own-window nonce/geometry proof. Minimized anchors must remain
unchanged throughout creation, detach and later verification. No foreign
window is restored and no input is sent to it.

All RC34 fixes and the RC35 reduction from six to four Terminal catalogues per
command are included. Native Swift code, Windows code and dependency pins are
unchanged. RC35 was published but its installation was stopped before creation;
its unknown original task is preserved. Actual RC36 installation and postrestart
verification are recorded separately. Known generic keyboard_unsupported and
external roundtrip limits are not represented as solved.
