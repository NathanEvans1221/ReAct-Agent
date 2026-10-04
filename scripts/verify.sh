#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python="${PYTHON:-.venv/bin/python}"
if [[ "${1:-}" == "--core" ]]; then
  "$python" -m unittest -v tests/test_agent.py tests/test_integration.py
else
  "$python" -m unittest discover -s tests -v
fi
"$python" -m pip check
"$python" -m compileall -q main.py tests
git -c core.autocrlf=true diff --check
