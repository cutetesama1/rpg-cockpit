#!/usr/bin/env bash
# POSIX 一键开发：API(8787) + Vite(5173)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python -m uvicorn main:app --app-dir "$ROOT/api" --port 8787 --reload &
API_PID=$!
trap 'kill "$API_PID" 2>/dev/null || true' EXIT

echo "API  http://127.0.0.1:8787/api/health"
echo "UI   http://127.0.0.1:5173"
cd "$ROOT/ui"
npm run dev
