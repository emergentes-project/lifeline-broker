#!/usr/bin/env bash
set -euo pipefail
/opt/lifeline-broker/export-certificate.sh
cd /opt/lifeline-broker
docker compose -f compose.yml restart artemis
