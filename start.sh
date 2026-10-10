#!/bin/sh
# TILES entry point for macOS and Linux.
#
#   ./start.sh               API + hot-reload web app (http://localhost:5173)
#   ./start.sh app           one process, built web app (http://localhost:8000)
#   ./start.sh docker        in a container (http://localhost:8000)
#   ./start.sh --help        every option
#
# This only finds Python 3.10+; run.py does the rest (Windows: start.cmd).
set -e
ROOT=$(cd "$(dirname "$0")" && pwd)

for py in python3 python3.13 python3.12 python3.11 python3.10 python; do
  if command -v "$py" >/dev/null 2>&1 &&
     "$py" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
    exec "$py" "$ROOT/run.py" "$@"
  fi
done

echo "TILES needs Python 3.10 or newer: https://www.python.org/downloads/" >&2
exit 1
