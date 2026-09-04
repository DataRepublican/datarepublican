#!/bin/bash

# Script to send SIGUSR1 to a running 'python irs990processor.py' process
# Uses ps -wwax for process listing and awk to extract PIDs matching both 'python' and script name

PIDS=$(ps -wwax | awk '/python/ && /irs990processor\.py/ && $2 != "?" {print $1}')

if [ -n "$PIDS" ]; then
    echo "Found PIDs: $PIDS"
    kill $PIDS
else
    echo "No matching 'python irs990processor.py' process found"
    exit 1
fi