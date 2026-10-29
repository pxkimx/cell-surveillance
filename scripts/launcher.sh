#!/bin/bash
# Starts the Cell Surveillance app and opens it in the default browser.
# If it is already running, this only opens the browser.
# The app quits by itself when its browser tab is closed (cellsurveillance/lifecycle.py); this script then ends,
# and the icon leaves the Dock.
PROJECT="__PROJECT__"
PORT=8531
URL="http://localhost:$PORT"
LOG="$HOME/Library/Logs/cell-surveillance.log"

alert() { osascript -e "display alert \"Cell Surveillance\" message \"$1\"" >/dev/null 2>&1; }

if curl -s -o /dev/null --max-time 1 "$URL/_stcore/health"; then
  open "$URL"
  exit 0
fi

if [ -x "$PROJECT/.venv/bin/python3" ]; then
  PY="$PROJECT/.venv/bin/python3"
elif [ -x /opt/anaconda3/bin/python3 ]; then
  PY=/opt/anaconda3/bin/python3
else
  PY="$(command -v python3)"
fi
[ -n "$PY" ] || { alert "Python 3 was not found on this computer."; exit 1; }
cd "$PROJECT" || { alert "Project folder not found: $PROJECT"; exit 1; }

echo "[$(date '+%F %T')] starting with $PY" >> "$LOG"
# The server watches this launcher: if the app is quit or force-quit from the Dock, the server stops too.
CELL_SURVEILLANCE_LAUNCHER_PID=$$ "$PY" -W ignore -m cellsurveillance app --port "$PORT" --headless >> "$LOG" 2>&1 &
PID=$!
trap 'kill $PID 2>/dev/null' EXIT INT TERM

for _ in $(seq 1 60); do
  if curl -s -o /dev/null --max-time 1 "$URL/_stcore/health"; then
    open "$URL"
    wait $PID
    exit 0
  fi
  kill -0 $PID 2>/dev/null || break
  sleep 0.5
done
alert "Cell Surveillance could not start. Details are in ~/Library/Logs/cell-surveillance.log"
exit 1
