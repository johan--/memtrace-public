#!/usr/bin/env bash
# 05_repro.sh — one-shot reproduction of the SWE-bench retrieval round.
#
# Phase 1 (pre-registration): generates 03_instances_25.csv + 04_instances_100.csv
#   from the pinned data/verified_500.parquet. Deterministic; no network if
#   parquet is already cached. No API spend.
#
# Phase 2 (run): executes the three retrieval rows (vector / agentic / memtrace)
#   against the pre-registered samples. Needs ANTHROPIC_API_KEY and a Memtrace
#   install >= 0.3.87. NOT executed by default — uncomment the run block at
#   the bottom or call `bash 05_repro.sh run`.
#
# Usage:
#   bash 05_repro.sh             # Phase 1 only (default)
#   bash 05_repro.sh sample      # same as default
#   bash 05_repro.sh run         # Phase 2 (requires env + Memtrace)
#   bash 05_repro.sh clean       # remove venv + generated artefacts (keeps CSVs)
#
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

VENV_DIR=".venv"
PYTHON_BIN="python3.12"

cmd_setup_venv() {
  if [[ ! -d "$VENV_DIR" ]]; then
    echo "[venv] creating $VENV_DIR with $PYTHON_BIN"
    "$PYTHON_BIN" -m venv "$VENV_DIR"
    "$VENV_DIR/bin/pip" install --quiet --upgrade pip
    "$VENV_DIR/bin/pip" install --quiet -r requirements.txt
  fi
}

cmd_sample() {
  cmd_setup_venv
  echo "[phase-1] regenerating pre-registered CSVs from data/verified_500.parquet"
  "$VENV_DIR/bin/python" 02_sampling.py

  echo ""
  echo "[verify] expected sha256s (committed at pre-registration):"
  echo "  data/verified_500.parquet: 43ed5a3d1d98da36472c1ade65ddd2085d7b4ff694fcaf6a023a07c5c1f32f21"
  echo "  03_instances_25.csv:       693286f2965c1e1adf4040d71df838ded26291e31e73cf5c20a60a655c880145"
  echo "  04_instances_100.csv:      572798b64641754d99e03fcc21c5cb6a1996b23b3bcb9726af5dd8cdd4f710f9"
  echo ""
  echo "  computed:"
  for f in data/verified_500.parquet 03_instances_25.csv 04_instances_100.csv; do
    if [[ -f "$f" ]]; then
      printf "    %-40s %s\n" "$f" "$(shasum -a 256 "$f" | awk '{print $1}')"
    fi
  done
}

cmd_run() {
  echo "[phase-2] not implemented in this commit — Phase 2 runners land separately."
  echo "          required env: ANTHROPIC_API_KEY, MEMTRACE >= 0.3.87"
  echo "          will write results/ subdirs: vector/, agentic/, memtrace/"
  exit 2
}

cmd_clean() {
  echo "[clean] removing $VENV_DIR and results/*/run_meta.json"
  rm -rf "$VENV_DIR"
  find results -type f -name 'run_meta.json' -delete 2>/dev/null || true
  echo "[keep ] CSVs, methodology, prompts, data/verified_500.parquet"
}

case "${1:-sample}" in
  sample) cmd_sample ;;
  run)    cmd_run ;;
  clean)  cmd_clean ;;
  *) echo "unknown subcommand: ${1}"; echo "usage: bash 05_repro.sh {sample|run|clean}"; exit 1 ;;
esac
