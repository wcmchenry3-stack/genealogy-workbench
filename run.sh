#!/usr/bin/env bash
# Genealogy Workbench -- ./run.sh to start.
set -e
cd "$(dirname "$0")"
if [ ! -x ".venv/bin/python" ]; then
  echo "Creating a private Python environment (one time, takes a minute)..."
  python3 -m venv .venv
  ./.venv/bin/python -m pip install --upgrade pip --quiet
  echo "Installing dependencies..."
  ./.venv/bin/python -m pip install -r requirements.txt --quiet
fi
echo "Starting Genealogy Workbench..."
exec ./.venv/bin/python -m app.server
