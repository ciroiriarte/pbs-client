#!/bin/bash
# Helper pushed into the test CT. Reads `proxmox-backup-client snapshot list
# --output-format json` on stdin and prints the LATEST matching snapshot's time
# as RFC3339 UTC (the form PBS wants: host/<id>/2026-01-02T03:04:05Z).
# Pure coreutils — no python (openSUSE minimal images ship none, and the client
# itself has no python dependency).
#
# Usage: <json> | snaptime.sh <backup-id>
bid="$1"
epoch=$(tr '{}' '\n' \
  | grep "\"backup-id\":\"$bid\"" \
  | grep -oE '"backup-time":[0-9]+' | grep -oE '[0-9]+' \
  | sort -n | tail -1)
[ -n "$epoch" ] && date -u -d "@$epoch" +%Y-%m-%dT%H:%M:%SZ
