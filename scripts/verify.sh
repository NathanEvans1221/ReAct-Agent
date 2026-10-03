#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
"${PYTHON:-.venv/bin/python}" -m unittest discover -s tests -v
git -c core.autocrlf=true diff --check
