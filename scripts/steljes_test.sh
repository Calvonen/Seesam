#!/usr/bin/env bash
set -euo pipefail

if ! command -v speaker-test >/dev/null 2>&1; then
  echo "Steljes NS3 audio test failed: missing required command 'speaker-test'." >&2
  exit 1
fi

echo "Running a short stereo speaker test..."
speaker-test -t wav -c 2 -l 1
echo "Steljes NS3 audio test finished."
