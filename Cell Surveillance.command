#!/bin/bash
# Same as double-clicking Cell Surveillance.app, but shows the log in a Terminal window.
cd "$(dirname "$0")"
PYTHON="/opt/anaconda3/bin/python3"
[ -x "$PYTHON" ] || PYTHON="$(command -v python3)"
exec "$PYTHON" -W ignore -m cellsurveillance app
