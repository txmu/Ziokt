#!/usr/bin/env bash
# Standalone native launcher for Ziokt Desktop Client
set -e
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT=8190

echo ">> Starting Ziokt Unified Graphical Client..."
if command -v python3 >/dev/null 2>&1; then
    python3 -m http.server $PORT -d "$DIR" >/dev/null 2>&1 &
    PID=$!
    trap "kill $PID" EXIT INT TERM
    sleep 0.5
    TARGET_URL="http://127.0.0.1:$PORT"
    if command -v xdg-open >/dev/null 2>&1; then
        xdg-open "$TARGET_URL"
    elif command -v open >/dev/null 2>&1; then
        open "$TARGET_URL"
    else
        echo "Please open $TARGET_URL in your browser."
    fi
    wait $PID
elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$DIR/index.html"
elif command -v open >/dev/null 2>&1; then
    open "$DIR/index.html"
else
    echo "Please open $DIR/index.html in your browser."
fi
