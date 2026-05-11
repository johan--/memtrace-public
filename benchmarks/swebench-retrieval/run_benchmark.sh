#!/usr/bin/env bash
# run_benchmark.sh — single entry point for Phase 2.
#
# Drop your Anthropic API key into the shell:
#
#   export ANTHROPIC_API_KEY=sk-ant-...
#   bash run_benchmark.sh                      # sanity (n=25, ~$45–120)
#   bash run_benchmark.sh --full               # appendix (n=100, ~$180–600)
#   bash run_benchmark.sh --dry-run            # 3 instances per row only (~$5–15)
#   bash run_benchmark.sh --skip-memtrace      # if MCP server isn't up
#
# All other orchestrator flags pass through. See `python -m runners.orchestrate --help`.
#
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

CSV="03_instances_25.csv"
EXTRA=()
DRY=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --full)            CSV="04_instances_100.csv" ;;
    --sanity|--n25)    CSV="03_instances_25.csv" ;;
    --dry-run)         DRY="--dry-run" ;;
    --skip-memtrace)   EXTRA+=("--skip-row" "memtrace") ;;
    --skip-agentic)    EXTRA+=("--skip-row" "agentic") ;;
    --skip-vector)     EXTRA+=("--skip-row" "vector-default" "--skip-row" "vector-coderankembed") ;;
    *)                 EXTRA+=("$1") ;;
  esac
  shift
done

if [[ ! -d ".venv" ]]; then
  echo "[setup] creating .venv ..."
  python3.12 -m venv .venv
  .venv/bin/pip install --quiet --upgrade pip
  .venv/bin/pip install --quiet -r requirements.txt
fi

if [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
  echo
  echo "  >> ANTHROPIC_API_KEY is not set in this shell."
  echo "  >> export ANTHROPIC_API_KEY=sk-ant-...  and re-run."
  echo
  echo "  (Vector rows would run without it, but the orchestrator runs all four"
  echo "   rows in sequence — and agentic + memtrace need the key. Stopping early"
  echo "   keeps the bookkeeping clean.)"
  exit 1
fi

echo "=== run_benchmark.sh ==="
echo "  csv: $CSV"
echo "  dry: ${DRY:-(no — full run on the CSV)}"
echo "  extra: ${EXTRA[*]:-(none)}"
echo

exec .venv/bin/python -m runners.orchestrate --csv "$CSV" ${DRY} "${EXTRA[@]}"
