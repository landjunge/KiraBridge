# Dedicated KiraBridge CI / Eigene KiraBridge-Testrechner

## Verified inventory, 2026-10-25

This change is stacked on integration PR37, source `481eb32`. It changes CI routing
and a deployment guard, not KiraBridge's runtime or production configuration.

| Lane | Actual host | Selection | State |
| --- | --- | --- | --- |
| Python 3.11 / 3.13 | Debian 13.6 x86_64, existing runner IDs 21/22 | `self-hosted`, `Linux`, `X64`, `kirabridge`, `debian` | Online; retained |
| Intel macOS | iMac, macOS 15.7.4 x86_64, 32 GB, four physical cores | `kirabridge-macos-intel` only | Prepared; **not registered** |
| Apple Silicon | No available ARM Mac | Existing hosted `macos-15` | Required; billing/capacity blocker, **not passed** |
| Linux installer | Pinned Ubuntu 24.04 container on Debian host | Existing `kirabridge-linux-smoke` single-job runner contract | No permanent Docker-capable runner added |

The existing Linux Verify check names still say `ubuntu-24.04`; the actual hosts
are Debian, not native Ubuntu. Existing tests, check names, action SHA pins,
RC14 fixture checksum, reproducible builds, installer checks, launchd lifecycle,
restart/data preservation/rollback checks, and artifact retention remain intact.
The release matrix additionally gains Intel; its existing ARM/Linux lanes remain.
No required check is removed, disabled, marked successful or replaced by a skip.

## Trust boundary / Schutz vor fremden PRs

The repository is private. API inspection found exactly one collaborator,
`landjunge` (admin). Private-fork workflow execution is **disabled**, with neither
write tokens nor secrets sent to forks. These platform settings must stay disabled:

```sh
gh api repos/landjunge/KiraBridge/actions/permissions/fork-pr-workflows-private-repos
gh api repos/landjunge/KiraBridge/collaborators --jq '.[].login'
```

Jobs also require the owner as actor and, for PRs, the owner as author and a head
from this repository. This is defense in depth, **not a sandbox**: a PR can edit its
own `pull_request` workflow. The real admission boundary is the private repository,
disabled fork execution and sole trusted writer. Reassess before adding writers,
enabling forks, or making the repository public. Untrusted PRs must be reviewed and
transferred deliberately to an isolated trusted branch before running; their skipped
jobs do not count as acceptance. No `pull_request_target` checkout of foreign code.
No new access token or account credential is stored in Git or logs. All checkouts
disable persisted credentials; workflow tokens remain `contents: read`.

Self-hosted jobs can persist changes under their account. Use a disposable VM for
untrusted code; a separate macOS account is sufficient here only for the sole-owner
trusted-code boundary. It cannot defend against kernel exploits or replace trust
review. [GitHub security guidance](https://docs.github.com/en/actions/reference/security/secure-use).

## Intel Mac: prerequisite deliberately unmet

The current console user is `landjunge`, UID 501, with production KiraBridge,
Codex sessions and private data. **Do not configure a runner as that user.** There
is no dedicated account or VM, and `sudo -n -l` requires a password. No password,
OS permission change, production service action or billing change was attempted.
Consequently there is no registered Intel runner and no new macOS Actions pass.

An administrator must first create a **standard, non-admin** account named
`kirabridge-ci`, real home `/Users/kirabridge-ci`, private mode 0700, separate GUI
login. Keep `/Users/landjunge` private (observed mode 0700); do not weaken existing
permissions. Do not give this account Full Disk Access, Accessibility, Automation,
sudo, SSH keys, GitHub PATs, production credentials, or access to user directories.
The package tests need only their own GUI launchd domain, private work/config/data,
temporary loopback ports, downloads and build tools, not control of real terminals.
Set up `/usr/local/bin/python3.11`, Git, gh and normal network access; uv 0.11.6 and
Python 3.11 runtimes are selected by the workflow. Never override HOME.

The administrator must validate account separation and the separate GUI domain
before registration. In its private reviewed checkout, run:

```sh
/usr/local/bin/python3.11 scripts/check_macos_ci_host.py
```

This guard checks actual OS/architecture, NSS identity/home, non-admin membership,
home mode/ownership, production-home inaccessibility, private workspace and GUI
domain. It changes no rights or services. It must refuse the production account.

## Repository-only registration after account preparation

Use the repository's **Settings → Actions → Runners → New self-hosted runner**;
choose macOS x64, not ARM or an organization-wide runner. Verified current upstream
archive: `actions-runner-osx-x64-2.338.0.tar.gz`, SHA-256
`dea7a58796ce215fc424a8b27c0fdd9b813fa5fc03d109a4a1d38131d6bfa1a3`.
Get the actual URL/checksum from the authenticated runner-downloads API and verify
before extraction. Do not execute downloaded shell via a pipe.

Prepare `/Users/kirabridge-ci/actions-runner` under that account with mode 0700.
Generate a short-lived **repository registration token** from the owner session;
deliver it through protected stdin to the dedicated account, never shell history,
argv, a file, Git or a pasted chat message. In that account, the protected bootstrap
can consume it without echo and configure the extracted official runner:

```sh
set +x
IFS= read -r ACTIONS_RUNNER_INPUT_TOKEN
export ACTIONS_RUNNER_INPUT_TOKEN
./config.sh --unattended --url https://github.com/landjunge/KiraBridge \
  --name kirabridge-intel-macos --labels kirabridge-macos-intel \
  --no-default-labels --work _work
unset ACTIONS_RUNNER_INPUT_TOKEN
```

Only this repository and custom label are permitted; omitting broad default labels
prevents unrelated generic jobs using the host. The official runner's protected
registration files are local machine credentials; keep their directory private,
out of artifacts and logs. Do not put a long-lived owner `gh auth` session in this
account. Start the official runner **in that account**, then verify its API identity,
labels and actual UID. Configure any automatic login/LaunchAgent only for that
separate account after approval; never install a root service or edit KiraBridge's
LaunchAgent. One runner executes one job at a time, limiting iMac load.

Required acceptance after setup: actual owner PR must select the new runner;
guard and Intel Verify must pass, then the unchanged real launchd package acceptance
and native release smoke. Record exact source SHA, runner ID, run/job links and cleanup
proof. No ARM claims from an Intel result. Failures remain failures. Administrative
setup and full end-to-end Intel Actions execution are **open**, not completed here.

## Costs, tests and release gates / Kosten und Abnahme

Existing Debian capacity handles Python tests; no new server service, Docker group
grant or billing change. Intel work will use the Mac after the account prerequisite.
Hosted ARM remains explicit and may require separate authorized billing resolution
or real ARM hardware. Self-hosting cannot make an ARM check pass on Intel/Linux.

For this CI-only change, necessary new checks are workflow syntax/expression lint,
host-guard security branches and real refusal under UID 501. No application suite,
installer rebuild or release is repeated locally: application code is unchanged and
the parent PR already records its exact results. Normal mandatory GitHub checks still
run after push/PR; missing Mac capacity/billing must be reported, never bypassed.
No merge or release until the agreed checks are genuinely satisfied. Parent PR37's
passed Linux results belong to its SHA, not automatically to this workflow commit.

Next step: administrative creation/login of the isolated account, then guarded
repository-only runner registration and the existing Intel jobs. Do not modify the
productive installation to obtain a test result.
