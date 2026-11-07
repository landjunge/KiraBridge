# KiraBridge 0.8.0rc33

RC33 consolidates Windows dev3 keyboard, shortcut and guarded window control
with the macOS RC31 native-read/event-index and RC32 accessibility batching
changes. The complete development histories are retained. Three version
conflicts were resolved without changing third-party dependencies.

The shared runtime passed 622 focused integration tests on Intel macOS; four
real Windows core tests were skipped there. Independent Windows and macOS
reviews found no blocking integration defects. The native Swift and Windows
backend sources remain unchanged from their separately accepted predecessors.
The additional win32 native-read refusal case verifies platform separation.

Windows operations retain exact handle/process-generation guards and serialized
desktop transactions. A close task confirms one accepted WM_CLOSE request,
not application termination. macOS native.read remains a separate six-operation
read-only contract, with fresh authorization and bounded accessibility trees.

Final RC33 platform packages require source-bound native acceptance, independent
package inspection and verified release downloads. Installation requires backup,
controlled visibility and preservation of existing data and running sessions.
This source note alone claims none of those steps complete. Current outcomes
are recorded in the dated RC33 delivery evidence and integration report.

Known limits remain: Windows global-key shortcuts, native stdio, Windows10 and
external ChatGPT/Voice are outside previous positive Windows acceptance; native
insertion is not an application acknowledgement. macOS accessibility snapshots
are not atomic; historical local summary timings are not cloud/Voice timings.

See [integration decisions and boundaries](INTEGRATION-DEV3-RC32-20261104.md),
[Windows dev3 baseline](WINDOWS-DESKTOP-20261104.md) and
[macOS RC32 baseline](RC32-NATIVE-ATTRIBUTE-BATCHING-20261103.md).
