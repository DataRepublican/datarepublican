#!/bin/bash
# loop_until_fast.sh
#
# Purpose: Runs a given command repeatedly (in a loop) until one full execution completes
# in less than 60 seconds, then exits cleanly. The entire process is wrapped in macOS
# `caffeinate` to prevent the machine from sleeping (idle or system sleep).
#
# This is useful for scripts whose runtime degrades as a database fills up (e.g., a
# batch processor that eventually finishes its current work quickly once the queue
# is empty or the DB state stabilizes).
#
# Usage:
#   ./loop_until_fast.sh your_command [arg1 arg2 ...]
#
# Example:
#   ./loop_until_fast.sh ./process_db.sh --input /data/db
#
# The script itself invokes caffeinate, so you do not need to prefix it.

set -uo pipefail

# Constant for the threshold (easy to change later, follows DRY)
THRESHOLD=120

if [ $# -eq 0 ]; then
  echo "Usage: $(basename "$0") <command> [args...]"
  echo "Runs the command repeatedly until one run finishes in < ${THRESHOLD} seconds."
  exit 1
fi

# caffeinate -i (prevent idle sleep) -s (prevent system sleep) wraps the loop.
# We pass the command and its arguments safely into the inner bash -c block.
caffeinate -i -s bash -c '
  while true; do
    echo "=== Starting run at $(date "+%Y-%m-%d %H:%M:%S") ==="
    echo "Command: $*"

    # Capture wall-clock start time in seconds since epoch
    start=$(date +%s)

    # Execute the original command (preserves all arguments and quoting)
    "$@"
    status=$?

    # Capture end time
    end=$(date +%s)
    duration=$((end - start))

    echo "=== Run completed in ${duration} seconds (exit code: ${status}) at $(date "+%Y-%m-%d %H:%M:%S") ==="

    if [ "${duration}" -lt '"${THRESHOLD}"' ]; then
      echo "Run took less than ${THRESHOLD} seconds. Stopping the loop."
      break
    else
      echo "Run took ${duration} seconds (>= ${THRESHOLD}). Continuing..."
      # Optional: add a short pause between runs if your command needs it
      # sleep 5
    fi
  done
' _ "$@"

echo "Loop finished at $(date "+%Y-%m-%d %H:%M:%S")."