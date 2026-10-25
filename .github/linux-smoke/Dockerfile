# Only this small directory is sent as build context; no checkout or credentials.
ARG UBUNTU_IMAGE
FROM ${UBUNTU_IMAGE}
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        ca-certificates curl git python3 \
    && rm -rf /var/lib/apt/lists/*
ARG RUNNER_UID
ARG RUNNER_GID
RUN test "$RUNNER_UID" -gt 0 && test "$RUNNER_GID" -gt 0 \
    && (getent group "$RUNNER_GID" >/dev/null || groupadd --gid "$RUNNER_GID" smoke) \
    && if getent passwd "$RUNNER_UID" >/dev/null; then \
         usermod --gid "$RUNNER_GID" "$(getent passwd "$RUNNER_UID" | cut -d: -f1)"; \
       else \
         useradd --uid "$RUNNER_UID" --gid "$RUNNER_GID" --home-dir /home/smoke \
           --create-home --shell /bin/sh smoke; \
       fi
USER ${RUNNER_UID}:${RUNNER_GID}
WORKDIR /tmp
