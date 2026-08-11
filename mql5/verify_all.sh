#!/usr/bin/env bash
# One-command MITEMSHUB verify: compile every Phase suite in MetaEditor and run
# each in the MT5 Strategy Tester headlessly, printing PASS/FAIL per suite.
# Usage:  bash mql5/verify_all.sh   (optionally pass -Symbol R_100 etc.)
set -euo pipefail
cd "$(dirname "$0")"
exec powershell -NoProfile -ExecutionPolicy Bypass -File "$(pwd)/verify_all.ps1" "$@"
