#!/usr/bin/env bash
set -euo pipefail

# Run a validation command against an already usable Docker daemon.  Some
# StewardBench development hosts intentionally expose only this rootless
# daemon; do not require sudo or change host group membership to reach it.
rootless_socket=${STEWARD_ROOTLESS_DOCKER_SOCKET:-/run/user/1000/adea-rootless-docker.sock}

if docker info >/dev/null 2>&1; then
  selected_daemon=${DOCKER_HOST:-"Docker context ${DOCKER_CONTEXT:-default}"}
else
  if [[ ! -S "$rootless_socket" ]]; then
    printf 'No usable Docker daemon. Default Docker configuration failed and rootless socket is absent: %s\n' "$rootless_socket" >&2
    exit 1
  fi
  export DOCKER_HOST="unix://${rootless_socket}"
  if ! docker info >/dev/null 2>&1; then
    printf 'No usable Docker daemon. Rootless socket did not accept Docker connections: %s\n' "$DOCKER_HOST" >&2
    exit 1
  fi
  selected_daemon=$DOCKER_HOST
fi

printf 'Using Docker daemon: %s\n' "$selected_daemon"
docker info --format 'Docker server {{.ServerVersion}}; security={{json .SecurityOptions}}'

if [[ "$#" -eq 0 ]]; then
  printf 'Usage: %s <command> [args ...]\n' "${0##*/}" >&2
  exit 2
fi

exec "$@"
