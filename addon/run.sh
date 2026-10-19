#!/bin/sh
# Optional entrypoint for the OpenSonoffMQTT add-on.
# Reads the add-on option "log_level" from /data/options.json (written by the
# Home Assistant Supervisor) and starts the FastAPI app with uvicorn.
set -e

LOG_LEVEL="info"
if [ -f /data/options.json ]; then
    parsed="$(sed -n 's/.*"log_level"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' /data/options.json | head -n 1)"
    if [ -n "$parsed" ]; then
        LOG_LEVEL="$parsed"
    fi
fi
export LOG_LEVEL

exec python -m uvicorn app.main:app --host 0.0.0.0 --port 8099 --log-level "$LOG_LEVEL"
