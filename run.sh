#!/usr/bin/env bash
# career-agent/run.sh — start the whole system (macOS/Linux).
#
#   ./run.sh          development: API with auto-reload + worker + Vite dev server
#                     UI at http://127.0.0.1:5173
#   ./run.sh --prod   production: build the UI once, then API (serving the UI) + worker
#                     UI at http://127.0.0.1:8000
#
# The worker runs separately from the API on purpose: reloading or restarting the
# API never interrupts a send, a tailoring run, a scheduled fetch or a backup.
set -euo pipefail

MODE="dev"
[ "${1:-}" = "--prod" ] && MODE="prod"

# Resolve the directory this script lives in, so it works from anywhere.
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"

# Pick a Python 3.11+ interpreter.
PYTHON_BIN="$(command -v python3.11 || command -v python3 || command -v python || true)"
if [ -z "$PYTHON_BIN" ]; then
  echo "ERROR: Python 3.11+ not found on PATH." >&2
  exit 1
fi

echo "==> Using Python: $PYTHON_BIN ($($PYTHON_BIN --version))"

# ---------- Preflight: refuse to start a second copy ----------
# Two copies would fight over the ports and run two workers on one database.
if command -v lsof >/dev/null 2>&1; then
  PORTS="8000"
  [ "$MODE" = "dev" ] && PORTS="8000 5173"
  for port in $PORTS; do
    # lsof exits non-zero when the port is free; `|| true` keeps `set -e -o pipefail` from aborting.
    holder="$(lsof -nP -iTCP:"$port" -sTCP:LISTEN 2>/dev/null | awk 'NR==2 {print $1 " (pid " $2 ")"}' || true)"
    if [ -n "$holder" ]; then
      echo "ERROR: port $port is already in use by $holder." >&2
      echo "       Career Agent is probably already running. Stop it first (Ctrl+C in its" >&2
      echo "       terminal, or: kill <pid>), then run this again." >&2
      exit 1
    fi
  done
fi

# ---------- Backend bootstrap ----------
cd "$BACKEND_DIR"
# Recreate the venv if it is missing or has no pip (a half-created venv makes
# `pip` silently resolve to the system interpreter and install globally).
if [ ! -x ".venv/bin/python" ] || ! .venv/bin/python -m pip --version >/dev/null 2>&1; then
  echo "==> Creating backend virtualenv (.venv)"
  rm -rf .venv
  "$PYTHON_BIN" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

echo "==> Installing backend dependencies (editable)"
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -e ".[dev]"

# Your data and keys live outside the repository, in CAREER_HOME.
CAREER_HOME="${CAREER_HOME:-$HOME/.career-agent}"
export CAREER_HOME
# Older versions kept them in backend/; move them once (backed up, verified first).
if [ -e "career_agent.db" ] || [ -e ".env" ] || [ -d "data" ]; then
  echo "==> Moving your data out of the repository into $CAREER_HOME"
  career-agent migrate-home
fi
mkdir -p "$CAREER_HOME"
chmod 700 "$CAREER_HOME"
if [ ! -f "$CAREER_HOME/.env" ]; then
  echo "==> Creating $CAREER_HOME/.env from .env.example (fill in your keys!)"
  cp .env.example "$CAREER_HOME/.env"
  chmod 600 "$CAREER_HOME/.env"
fi

# Block commits containing secrets or your personal data (scripts/hooks/pre-commit).
if git -C "$ROOT_DIR" rev-parse --git-dir >/dev/null 2>&1 \
  && [ "$(git -C "$ROOT_DIR" config --get core.hooksPath || true)" != "scripts/hooks" ]; then
  echo "==> Turning on the leak check that runs before every commit"
  git -C "$ROOT_DIR" config core.hooksPath scripts/hooks
fi
if ! command -v gitleaks >/dev/null 2>&1; then
  echo "    note: install gitleaks (brew install gitleaks); commits are refused without it."
fi

# ---------- Frontend bootstrap ----------
cd "$FRONTEND_DIR"
if [ ! -d "node_modules" ]; then
  echo "==> Installing frontend dependencies (npm install)"
  npm install
fi
if [ "$MODE" = "prod" ]; then
  echo "==> Building the frontend"
  npm run build
fi

# ---------- Run everything, shut down together ------
PIDS=()
cleanup() {
  echo ""
  echo "==> Shutting down (the worker finishes running tasks first)..."
  for pid in "${PIDS[@]:-}"; do
    kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
}
trap cleanup INT TERM EXIT

cd "$BACKEND_DIR"
echo "==> Starting worker (background tasks, schedules, backups)"
career-agent worker &
PIDS+=("$!")

if [ "$MODE" = "prod" ]; then
  echo "==> Starting API + UI -> http://127.0.0.1:8000"
  career-agent api --prod &
  PIDS+=("$!")
else
  echo "==> Starting API -> http://127.0.0.1:8000  (docs at /docs)"
  career-agent api &
  PIDS+=("$!")
  echo "==> Starting frontend -> http://127.0.0.1:5173"
  cd "$FRONTEND_DIR"
  npm run dev &
  PIDS+=("$!")
fi

echo "==> Running ($MODE). Press Ctrl+C to stop."

# If any part stops (crash, port clash, a second worker refused), stop the rest
# too rather than leave a half-working system behind. (macOS bash 3.2 has no
# `wait -n`, so poll.)
while true; do
  for pid in "${PIDS[@]}"; do
    if ! kill -0 "$pid" 2>/dev/null; then
      echo "" >&2
      echo "ERROR: a component (pid $pid) stopped unexpectedly; see the messages above." >&2
      echo "       Shutting everything down." >&2
      exit 1
    fi
  done
  sleep 2
done
