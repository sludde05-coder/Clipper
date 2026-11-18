#!/bin/bash
# Double-click this on a Mac to open the Clipper app (Linux: run ./Clipper.command).
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  echo "The clipper isn't installed yet. Double-click install.command first."
  read -n 1 -s -r -p "Press any key to close."
  exit 1
fi
if ! .venv/bin/python -c "import clipper.app" 2>/dev/null; then
  echo "Clipper needs a quick update of its parts. Double-click install.command, then try again."
  read -n 1 -s -r -p "Press any key to close."
  exit 1
fi
echo "Opening Clipper… You can close this Terminal window; Clipper keeps running."
nohup .venv/bin/python -m clipper app >/dev/null 2>&1 &
sleep 2
