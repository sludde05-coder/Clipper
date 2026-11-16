#!/bin/bash
# Double-click this on a Mac to open the clipper (Linux: run ./Clipper.command).
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  echo "The clipper isn't installed yet. Double-click install.command first."
  read -n 1 -s -r -p "Press any key to close."
  exit 1
fi
.venv/bin/python -m clipper "$@"
