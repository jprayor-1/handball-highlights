#!/bin/bash

# Exit on error
set -e

echo "Starting Handball Highlights API..."

# Get port from environment or default to 5000
PORT=${PORT:-5000}

# Number of worker processes
WORKERS=${WORKERS:-2}

# Timeout for long-running video processing (10 minutes)
TIMEOUT=${TIMEOUT:-600}

# Start Gunicorn
exec gunicorn app:app \
  --bind 0.0.0.0:$PORT \
  --workers $WORKERS \
  --timeout $TIMEOUT \
  --access-logfile - \
  --error-logfile - \
  --log-level info
