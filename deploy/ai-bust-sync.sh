#!/usr/bin/env bash
# Fetch the nightly simulation files that the GitHub Action commits and publish them atomically.
# /root/paper is not a git checkout, so this downloads just the two data files from the public repo.
set -euo pipefail
DEST="${AI_BUST_DIR:-/root/paper}/public/data"
BASE="https://raw.githubusercontent.com/YassinKhalil/when-the-buildout-breaks/main/public/data"
mkdir -p "$DEST"; tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
curl -fsS --max-time 30 -o "$tmp/latest_run.json" "$BASE/latest_run.json"
curl -fsS --max-time 30 -o "$tmp/historical_risk.csv" "$BASE/historical_risk.csv"
python3 -c "import json,sys; d=json.load(open('$tmp/latest_run.json')); assert d['model_d'] and d['model_f']" # refuse a corrupt file
head -1 "$tmp/historical_risk.csv" | grep -q '^date,' 
chmod 644 "$tmp"/*
mv "$tmp/latest_run.json" "$DEST/latest_run.json"; mv "$tmp/historical_risk.csv" "$DEST/historical_risk.csv"
