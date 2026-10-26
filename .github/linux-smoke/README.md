# Linux package smoke on the existing Debian runner

`sh scripts/ci_linux_release_smoke.sh dist/candidate` runs the packaged installer
and smoke check as the non-root runner UID inside digest-pinned official Ubuntu
24.04 **userspace**, sharing the Debian host kernel. This establishes neither
native Ubuntu-kernel nor macOS/launchd acceptance. The installer's Ubuntu guard
remains intact; Debian installation support is not claimed.

Docker must already be available to the runner. Only the image build installs
packages; the host receives no apt/sudo changes. The container has a read-only
filesystem, a read-only smoke script and candidate mount, a bounded executable
temporary filesystem and a separate private evidence output directory. No host
Docker socket, credentials, host networking or privileged mode is passed inside.
Pinned installer downloads use Docker's normal bridge network.

The helper removes its exact labelled container/image and propagates failures.
It retains diagnostics and fails if cleanup cannot be confirmed. Docker's normal
shared build cache and the official base image are not globally pruned. Only
successful `smoke-Linux-x86_64.json` and separate container-environment evidence are copied into the candidate output,
including the observed userspace, non-root UID, architecture and base-image pin.
The macOS workflow still runs its smoke check natively.

The package lane uses label `kirabridge-linux-smoke`, separate from the existing
`kirabridge` Verify runners. A runner must already possess Docker access; the
workflow grants no group, socket or sudo permissions. For this acceptance an
ephemeral single-job runner under the already authorized server user is used,
with only this label and no default labels/service. Remove/observe its ephemeral
registration after that job; do not leave a permanent additional worker implicitly.
