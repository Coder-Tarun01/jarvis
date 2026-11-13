#!/usr/bin/env bash
# JARVIS — one-command local start (macOS / Linux)
#
#   ./run.sh
#
# Creates .venv, installs deps, runs the API on :8000 and Vite on :5173.

set -euo pipefail
cd "$(dirname "$0")"
ROOT="$(pwd)"

if [ ! -f .env ]; then
  echo "No .env found — copying .env.example."
  cp .env.example .env
  echo "Fill in OPENAI_API_KEY and JARVIS_AUTH_TOKEN in .env, then re-run."
fi

if [ ! -d .venv ]; then
  echo "Creating virtual environment…"
  python3 -m venv .venv
fi

# shellcheck disable=SC1091
. .venv/bin/activate

echo "Installing backend dependencies…"
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r backend/requirements.txt

if [ ! -d frontend/node_modules ]; then
  echo "Installing frontend dependencies…"
  (cd frontend && npm install --no-audit --no-fund)
fi

echo "Starting backend on http://127.0.0.1:8000 …"
(cd backend && python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000) &
BACKEND_PID=$!
echo "$BACKEND_PID" > .backend.pid

cleanup() {
  echo
  echo "Shutting down…"
  kill "$BACKEND_PID" 2>/dev/null || true
  rm -f .backend.pid
}
trap cleanup EXIT INT TERM

sleep 2
echo "Starting frontend on http://localhost:5173 …"
(cd frontend && npm run dev)
