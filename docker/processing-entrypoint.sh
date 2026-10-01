#!/bin/sh
set -eu
mkdir -p "${PROMETHEUS_MULTIPROC_DIR:-/tmp/prometheus}"
exec "$@"
