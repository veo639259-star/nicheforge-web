#!/usr/bin/env bash
# ============================================================
#  NicheForge - Linux / macOS launcher
#  Make executable: chmod +x start.sh
#  Then run: ./start.sh  (or double-click in your file manager)
# ============================================================
set -euo pipefail

# Always run from the script's own directory, wherever it is.
cd "$(dirname "$0")"

echo "Installing dependencies (this may take a moment)..."
python3 -m pip install -q -r requirements.txt

# Load the master password automatically if .master-password exists
# (created by tools/migrate_fb_tokens.py). No password typing needed.
if [ -z "${NICHEFORGE_PASSWORD:-}" ] && [ -f ".master-password" ]; then
    export NICHEFORGE_PASSWORD
    NICHEFORGE_PASSWORD="$(cat .master-password)"
fi

URL="http://127.0.0.1:5057/"
echo "Opening NicheForge in your browser..."
if command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$URL" >/dev/null 2>&1 &
elif command -v open >/dev/null 2>&1; then
    open "$URL" >/dev/null 2>&1 &
else
    echo "Could not auto-open a browser; visit $URL manually."
fi

echo "Starting NicheForge server..."
exec python3 app.py
