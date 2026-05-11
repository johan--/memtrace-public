#!/usr/bin/env bash
# run_benchmark.sh — single entry point for Phase 2.
#
# *** Phase 2 is currently deferred. See README.md "Run status" + 01_methodology.md §10
#     for the methodology gates that need to clear first. The harness is fully wired
#     and ready — re-enable below by removing the early-exit guard once gates are met. ***
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

# ── Phase 2 run guard ─────────────────────────────────────────────────────────
# Set MEMTRACE_BENCH_ALLOW_PHASE2=1 to override once methodology gates clear.
# See README.md "Run status" + 01_methodology.md §10 for what those gates are.
if [[ "${MEMTRACE_BENCH_ALLOW_PHASE2:-0}" != "1" ]]; then
  cat <<'GATE'
Phase 2 run is intentionally deferred at this commit.

  Why: the methodology has known gaps a brutal reviewer would (rightly)
       call out — see README.md "Run status" + 01_methodology.md §10.

  Gates before running:
    G1  Independent commodity vector baseline (ChromaDB / sentence-transformers)
    G2  Sample size >= 300 (current pre-registration: n=25 + n=100)
    G3  Hunk-level recall in addition to file-level
    G4  Train/test contamination probe
    G5  Independent runner or co-author from outside the Memtrace team

  Override (when the gates are honestly met):
    MEMTRACE_BENCH_ALLOW_PHASE2=1 bash run_benchmark.sh --dry-run

The harness is fully wired. Repo cloner, three runners, scorer with Wilson
+ bootstrap CIs, aggregator — all committed. The pre-registration commit
locks instance IDs + methodology before any retrieval. Resuming is a flip
of the env var; deferring is the right call until the gates are real.
GATE
  exit 2
fi


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
