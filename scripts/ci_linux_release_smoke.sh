#!/bin/sh
# Ubuntu userspace on the Debian CI host; no host packages or installer guard changes.
set -eu
umask 077

[ "$(uname -s)-$(uname -m)" = Linux-x86_64 ] || {
  echo 'This helper requires the Linux x86_64 CI host.' >&2; exit 2;
}
[ "$(id -u)" != 0 ] || { echo 'Run this helper as the existing non-root runner.' >&2; exit 2; }
[ "$#" = 1 ] || { echo 'Usage: sh scripts/ci_linux_release_smoke.sh ARTIFACT_DIRECTORY' >&2; exit 2; }
command -v docker >/dev/null || { echo 'Existing Docker access is required.' >&2; exit 2; }

# Official Ubuntu 24.04 image digest independently pulled on the CI host.
ubuntu_image='ubuntu:24.04@sha256:68ee22004a9109b44973313b02ff7b1de250f1de0f5ecb628d73f579aaff33ac'
case "$ubuntu_image" in
  ubuntu:24.04@sha256:*) digest=${ubuntu_image##*@sha256:} ;;
  *) echo 'A verified Ubuntu 24.04 image digest is required.' >&2; exit 2 ;;
esac
[ "${#digest}" = 64 ] || { echo 'Invalid Ubuntu digest.' >&2; exit 2; }
case "$digest" in *[!0-9a-f]*) echo 'Invalid Ubuntu digest.' >&2; exit 2 ;; esac

repo=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd -P)
artifacts=$(CDPATH='' cd -- "$1" && pwd -P)
case "$repo$artifacts" in
  *','*|*'
'*) echo 'Docker bind paths must not contain commas or newlines.' >&2; exit 2 ;;
esac
evidence="$artifacts/smoke-Linux-x86_64.json"
environment_evidence="$artifacts/smoke-container-Linux-x86_64.json"
[ ! -e "$evidence" ] && [ ! -L "$evidence" ] \
  && [ ! -e "$environment_evidence" ] && [ ! -L "$environment_evidence" ] || {
  echo 'Existing smoke evidence is preserved; use fresh candidate artifacts.' >&2; exit 2;
}

scratch=$(mktemp -d "${TMPDIR:-/tmp}/kirabridge-linux-smoke.XXXXXXXX")
mkdir "$scratch/evidence"
nonce=${scratch##*.}
image="kirabridge-linux-smoke:$nonce-$$"
cleanup() {
  result=$?
  cleanup_failed=0
  trap - EXIT HUP INT TERM
  if [ -f "$scratch/container.cid" ]; then
    cid=$(cat "$scratch/container.cid")
    if [ "$(docker inspect --format '{{ index .Config.Labels "io.kirabridge.smoke" }}' "$cid" 2>/dev/null || true)" = "$nonce" ]; then
      docker rm -f "$cid" >/dev/null || { echo 'Owned smoke container cleanup failed.' >&2; cleanup_failed=1; }
    else
      echo 'Cannot verify ownership/removal of the smoke container.' >&2
      cleanup_failed=1
    fi
  fi
  if [ "$(docker image inspect --format '{{ index .Config.Labels "io.kirabridge.smoke" }}' "$image" 2>/dev/null || true)" = "$nonce" ]; then
    docker image rm "$image" >/dev/null || { echo 'Owned smoke image cleanup failed.' >&2; cleanup_failed=1; }
  elif [ "${image_built:-no}" = yes ]; then
    echo 'Cannot verify ownership/removal of the smoke image.' >&2
    cleanup_failed=1
  fi
  if [ "$cleanup_failed" = 0 ]; then
    rm -rf "$scratch"
  else
    echo "Cleanup not confirmed; retained own diagnostic directory: $scratch" >&2
    [ "$result" != 0 ] || result=1
  fi
  exit "$result"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

docker build --build-arg "UBUNTU_IMAGE=$ubuntu_image" \
  --build-arg "RUNNER_UID=$(id -u)" --build-arg "RUNNER_GID=$(id -g)" \
  --label "io.kirabridge.smoke=$nonce" --tag "$image" "$repo/.github/linux-smoke"
image_built=yes

proof_code='import json, os, platform
from pathlib import Path
info = platform.freedesktop_os_release()
assert (info["ID"], info["VERSION_ID"]) == ("ubuntu", "24.04")
assert os.getuid() != 0 and platform.machine() == "x86_64"
path = Path("/tmp/artifacts/smoke-Linux-x86_64.json")
evidence = json.loads(path.read_text())
evidence["ci_container"] = {
    "userspace": "Ubuntu 24.04", "uid": os.getuid(), "nonroot": True,
    "architecture": platform.machine(),
    "base_image": os.environ["KIRABRIDGE_SMOKE_UBUNTU_IMAGE"],
    "kernel_scope": "shared host kernel; no native Ubuntu kernel or macOS acceptance",
}
path.write_text(json.dumps(evidence, indent=2) + "\n")
Path("/output/smoke-container-Linux-x86_64.json").write_text(
    json.dumps(evidence["ci_container"], indent=2) + "\n")
print(json.dumps({"container_environment": evidence["ci_container"]}, indent=2))'

# Read-only inputs, isolated writable tmpfs, default bridge networking for pinned
# downloads. No Docker socket, host network, privileges or production directories.
docker run --cidfile "$scratch/container.cid" --name "kirabridge-smoke-$nonce-$$" \
  --label "io.kirabridge.smoke=$nonce" --user "$(id -u):$(id -g)" \
  --read-only --cap-drop ALL --security-opt no-new-privileges \
  --cpus 2 --memory 3g --memory-swap 3g --pids-limit 256 \
  --tmpfs /tmp:rw,nosuid,nodev,size=2g,mode=1777 \
  --mount "type=bind,src=$repo/scripts/release_smoke.py,dst=/source/release_smoke.py,readonly" \
  --mount "type=bind,src=$artifacts,dst=/input-artifacts,readonly" \
  --mount "type=bind,src=$scratch/evidence,dst=/output" \
  --env "KIRABRIDGE_SMOKE_UBUNTU_IMAGE=$ubuntu_image" --env PYTHONDONTWRITEBYTECODE=1 \
  --env UV_CACHE_DIR=/tmp/uv-cache --env UV_PYTHON_INSTALL_DIR=/tmp/uv-python --env TMPDIR=/tmp \
  "$image" sh -eu -c '
    mkdir -p /tmp/artifacts
    cp /input-artifacts/*.tar.gz /input-artifacts/*.whl /input-artifacts/LICENSE /tmp/artifacts/
    python3 /source/release_smoke.py /tmp/artifacts
    python3 -c "$1"
    cp /tmp/artifacts/smoke-Linux-x86_64.json /output/
  ' sh "$proof_code"
# Copy only successful evidence before cleanup; tmpfs is removed on container exit.
cp "$scratch/evidence/smoke-Linux-x86_64.json" "$evidence"
cp "$scratch/evidence/smoke-container-Linux-x86_64.json" "$environment_evidence"
echo 'Ubuntu 24.04 userland smoke passed on the Debian host kernel; not a macOS test.'
