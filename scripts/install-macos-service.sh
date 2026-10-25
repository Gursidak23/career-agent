#!/usr/bin/env bash
# Run Career Agent (API + UI + worker) in the background on login, restarting it
# if it crashes. Uses launchd (macOS). Undo with:  scripts/install-macos-service.sh --uninstall
#
# Production mode: build the UI first (cd frontend && npm run build) and make sure
# backend/.venv exists (./run.sh once does both).
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
AGENTS="$HOME/Library/LaunchAgents"
LOGS="$HOME/Library/Logs/career-agent"

plist() { # label, subcommand args
  cat <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$1</string>
  <key>ProgramArguments</key>
  <array>
    <string>$BACKEND_DIR/.venv/bin/career-agent</string>
    $(for a in "${@:2}"; do echo "<string>$a</string>"; done)
  </array>
  <key>WorkingDirectory</key><string>$BACKEND_DIR</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>10</integer>
  <key>StandardOutPath</key><string>$LOGS/$1.log</string>
  <key>StandardErrorPath</key><string>$LOGS/$1.log</string>
</dict>
</plist>
PLIST
}

if [ "${1:-}" = "--uninstall" ]; then
  for label in com.careeragent.api com.careeragent.worker; do
    launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
    rm -f "$AGENTS/$label.plist"
  done
  echo "Removed Career Agent services."
  exit 0
fi

[ -x "$BACKEND_DIR/.venv/bin/career-agent" ] || { echo "Run ./run.sh once first (creates backend/.venv)." >&2; exit 1; }
[ -f "$ROOT_DIR/frontend/dist/index.html" ] || { echo "Build the UI first: cd frontend && npm run build" >&2; exit 1; }
mkdir -p "$AGENTS" "$LOGS"
plist com.careeragent.api api --prod > "$AGENTS/com.careeragent.api.plist"
plist com.careeragent.worker worker > "$AGENTS/com.careeragent.worker.plist"
for label in com.careeragent.api com.careeragent.worker; do
  launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$AGENTS/$label.plist"
done
echo "Career Agent runs at http://127.0.0.1:8000 (logs: $LOGS)."
