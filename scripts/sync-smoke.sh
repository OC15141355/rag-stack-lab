#!/usr/bin/env bash
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
cp lab/smoke/smoke.py lab/envs/base/smoke.py
