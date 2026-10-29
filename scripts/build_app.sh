#!/bin/bash
# Builds "Cell Surveillance.app" in the project folder and copies it to ~/Desktop/Toolbox.
# Run again after moving or renaming the project folder: the app stores the folder's location.
set -e
PROJECT="$(cd "$(dirname "$0")/.." && pwd)"
APP="$PROJECT/Cell Surveillance.app"
TOOLBOX="$HOME/Desktop/Toolbox"
PY=/opt/anaconda3/bin/python3; [ -x "$PY" ] || PY="$(command -v python3)"
VERSION="$("$PY" -c "import sys; sys.path.insert(0, '$PROJECT'); import cellsurveillance; print(cellsurveillance.__version__)")"

"$PY" "$PROJECT/scripts/make_icon.py" >/dev/null
SET="$(mktemp -d)/CellSurveillance.iconset"; mkdir -p "$SET"
for s in 16 32 128 256 512; do
  sips -z $s $s "$PROJECT/assets/icon.png" --out "$SET/icon_${s}x${s}.png" >/dev/null
  sips -z $((s*2)) $((s*2)) "$PROJECT/assets/icon.png" --out "$SET/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$SET" -o "$PROJECT/assets/CellSurveillance.icns"

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
sed "s/__VERSION__/$VERSION/g" "$PROJECT/scripts/Info.plist" > "$APP/Contents/Info.plist"
sed "s|__PROJECT__|$PROJECT|g" "$PROJECT/scripts/launcher.sh" > "$APP/Contents/MacOS/CellSurveillance"
chmod +x "$APP/Contents/MacOS/CellSurveillance"
cp "$PROJECT/assets/CellSurveillance.icns" "$APP/Contents/Resources/"
touch "$APP"
echo "built $APP"

if [ -d "$TOOLBOX" ]; then
  rm -rf "$TOOLBOX/Cell Surveillance.app"
  cp -R "$APP" "$TOOLBOX/"
  touch "$TOOLBOX/Cell Surveillance.app"
  echo "copied to $TOOLBOX"
fi
