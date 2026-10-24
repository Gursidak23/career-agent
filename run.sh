#!/usr/bin/env bash
# career-agent/run.sh — one-shot dev launcher for backend + frontend (macOS/Linux)
set -euo pipefail

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

if [ ! -f ".env" ]; then
  echo "==> Creating backend/.env from .env.example (fill in your keys!)"
  cp .env.example .env
fi

# ---------- Frontend bootstrap ----------
cd "$FRONTEND_DIR"
if [ ! -d "node_modules" ]; then
  echo "==> Installing frontend dependencies (npm install)"
  npm install
fi

# ---------- Run both, shut down together ------
PIDS=()
cleanup() {
  echo ""
  echo "==> Shutting down..."
  for pid in "${PIDS[@]:-}"; do
    kill "$pid" 2>/dev/null || true
  done
}
trap cleanup INT TERM EXIT

echo "==> Starting backend  -> http://127.0.0.1:8000  (docs at /docs)"
cd "$BACKEND_DIR"
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000 &
PIDS+=("$!")

echo "==> Starting frontend -> http://127.0.0.1:5173"
cd "$FRONTEND_DIR"
npm run dev &
PIDS+=("$!")

echo "==> Both running. Press Ctrl+C to stop."
wait
