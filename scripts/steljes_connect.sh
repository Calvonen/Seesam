#!/usr/bin/env bash
set -euo pipefail

DEVICE_MAC="04:FE:A1:46:BA:AA"
DEVICE_NAME="Steljes audio NS3"
VOLUME="40%"

fail() {
  echo "Steljes NS3 connection failed: $*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "missing required command '$1'"
}

require_command bluetoothctl
require_command wpctl

echo "Turning Bluetooth on..."
bluetoothctl power on >/dev/null || fail "could not turn Bluetooth on"

echo "Connecting to $DEVICE_NAME ($DEVICE_MAC)..."
bluetoothctl connect "$DEVICE_MAC" >/dev/null || fail "could not connect to $DEVICE_MAC"

echo "Waiting for PipeWire/WirePlumber to expose the audio sink..."
sleep 3

sink_id="$(
  wpctl status |
    awk -v name="$DEVICE_NAME" '
      index($0, name) {
        line = $0
        sub(/^.*[[:space:]]([0-9]+)\..*$/, "\\1", line)
        if (line ~ /^[0-9]+$/) {
          print line
          exit
        }
      }
    '
)"

if [ -z "$sink_id" ]; then
  echo "Steljes NS3 connection failed: could not find '$DEVICE_NAME' in wpctl status." >&2
  echo "Current wpctl status:" >&2
  wpctl status >&2 || true
  exit 1
fi

echo "Setting $DEVICE_NAME sink $sink_id as default output..."
wpctl set-default "$sink_id" || fail "could not set sink $sink_id as default"

echo "Setting $DEVICE_NAME volume to $VOLUME..."
wpctl set-volume "$sink_id" "$VOLUME" || fail "could not set volume for sink $sink_id"

echo "Steljes NS3 connected. Default output is '$DEVICE_NAME' at $VOLUME."
