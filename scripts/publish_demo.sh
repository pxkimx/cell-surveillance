#!/bin/bash
# Rebuild the website demo with the real calibration and put it on the site branch.
#
#   scripts/publish_demo.sh <minutes between frames> <scale bar length in micrometres>
#
# It stops before going live. The last lines it prints are the two commands that publish.
set -euo pipefail
[ $# -eq 2 ] || { echo "usage: $0 <minutes between frames> <scale bar length in um>"; exit 1; }
HERE="$(cd "$(dirname "$0")/.." && pwd)"
SITE="${CS_SITE_REPO:-$HOME/Documents/GitHub/paul-h-kim-site}"   # the website repository
PY=/opt/anaconda3/bin/python3
export PATH="$HOME/.local/node/bin:$PATH"

cd "$SITE"
git checkout cell-surveillance-card
git merge --no-edit main
"$PY" -W ignore "$HERE/scripts/make_demo.py" --interval-min "$1" --scale-bar-um "$2"
./node_modules/.bin/vinext build
git add app public/images/tools/cell-surveillance-report public/images/tools/cell-surveillance.jpg \
        public/tools/cell-surveillance-demo.mp4 public/tools/cell-surveillance-report-example.html
git commit -m "Offline tools: Cell Surveillance demo with confirmed calibration ($1 min per frame, $2 um scale bar)" || true
git push origin cell-surveillance-card
echo
echo "The branch is updated and has a preview build. To publish to paul-h-kim.com:"
echo "  cd \"$SITE\" && git checkout main && git merge --no-edit cell-surveillance-card && git push origin main"
